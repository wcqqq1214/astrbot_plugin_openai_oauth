"""Bounded Claude session checkpoints; no subscription credentials are stored."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path


def claim(directory: Path):
    """Hold an OS lease so reloads and other providers cannot resume a live CLI."""
    try:
        handle = (directory / "lease").open("a+b")
        if os.name == "nt":
            import msvcrt

            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        if "handle" in locals():
            handle.close()
        return None


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def message_hashes(messages: list[dict]) -> list[str]:
    """Ignore transport-only cache markers and unsigned reasoning in history."""

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k != "cache_control"}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    hashes = []
    for message in messages:
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        content = [
            clean(p)
            for p in content
            if p.get("type") not in {"thinking", "redacted_thinking"}
            and not (p.get("type") == "text" and not p.get("text"))
        ]
        hashes.append(digest({"role": message["role"], "content": content}))
    return hashes


class SessionStore:
    """Only completed turns are eligible for recovery after a process restart."""

    def __init__(self, root: Path, ttl: float = 86400, limit: int = 32):
        self.root = root.resolve()
        self.work = self.root / "work"
        self.records = self.root / "sessions"
        self.transcripts = self.root / "transcripts"
        self.ttl, self.limit = ttl, limit
        for path in (self.root, self.work, self.records, self.transcripts):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)

    def prepare(self, host) -> bool:
        """Redirect only this bridge's native project to AstrBot's data directory.

        Keep the CLI's credential directory unchanged. If the platform cannot
        create directory links, live reuse still works without disk recovery.
        """
        config = Path(
            host.environment().get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
        )
        project = re.sub(r"[^a-zA-Z0-9]", "-", str(self.work))
        link = config / "projects" / project
        try:
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.is_symlink():
                return link.resolve() == self.transcripts
            if link.exists():
                return False
            link.symlink_to(self.transcripts, target_is_directory=True)
            return True
        except OSError:
            return False

    def directory(self, session: str) -> Path:
        if str(uuid.UUID(session)) != session:
            raise ValueError("Invalid Claude session ID")
        return self.records / session

    def new(self) -> str:
        session = str(uuid.uuid4())
        self.directory(session).mkdir(mode=0o700)
        return session

    def invalidate(self, session: str) -> None:
        (self.directory(session) / "state.json").unlink(missing_ok=True)

    def save(self, session: str, key: str, history: list[str]) -> None:
        directory = self.directory(session)
        pending = directory / "state.tmp"
        with pending.open("w", encoding="utf-8") as f:
            pending.chmod(0o600)
            json.dump(
                {"version": 1, "key": key, "history": history, "updated": time.time()},
                f,
            )
            f.flush()
            os.fsync(f.fileno())
        pending.replace(directory / "state.json")

    def discard(self, session: str) -> None:
        shutil.rmtree(self.directory(session), ignore_errors=True)
        (self.transcripts / (session + ".jsonl")).unlink(missing_ok=True)
        shutil.rmtree(self.transcripts / session, ignore_errors=True)

    def saved(self, active: set[str]) -> list[tuple[str, dict]]:
        records = []
        for directory in self.records.iterdir():
            session = directory.name
            if session in active or directory.is_symlink():
                continue
            try:
                self.directory(session)
            except ValueError:
                continue
            lease = claim(directory)
            if lease is None:
                continue
            try:
                state = json.loads((directory / "state.json").read_text())
                valid = (
                    state.get("version") == 1
                    and isinstance(state.get("key"), str)
                    and isinstance(state.get("history"), list)
                    and all(isinstance(h, str) for h in state["history"])
                    and isinstance(state.get("updated"), (int, float))
                    and 0 <= time.time() - state["updated"] < self.ttl
                    and (self.transcripts / (session + ".jsonl")).is_file()
                )
            except (OSError, ValueError, AttributeError, TypeError):
                valid = False
            finally:
                lease.close()
            if valid:
                records.append((session, state))
            else:
                self.discard(session)
        records.sort(key=lambda item: item[1]["updated"], reverse=True)
        for session, _ in records[self.limit :]:
            lease = claim(self.directory(session))
            if lease is not None:
                try:
                    self.invalidate(session)
                finally:
                    lease.close()
                self.discard(session)
        return records[: self.limit]
