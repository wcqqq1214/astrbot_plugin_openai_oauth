"""Discover and run the host's Claude Code without importing its credentials."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
from pathlib import Path
from typing import Any

from .credential_store import CredentialError

CLAUDE_PROVIDER_TYPE = "Claude Subscribe"
CLAUDE_MODE = "local_claude"


class ClaudeError(CredentialError):
    """A credential-safe error that may be shown in the dashboard."""


def default_claude_source() -> dict[str, Any]:
    return {
        "id": CLAUDE_PROVIDER_TYPE,
        "type": CLAUDE_PROVIDER_TYPE,
        "name": "Local Claude",
        "provider": "anthropic",
        "provider_type": "chat_completion",
        "credential_mode": CLAUDE_MODE,
        "key": "",
        "enable": True,
        "claude_command": "",
        "claude_config_dir": "",
        "timeout": 180,
    }


async def stop_process(process: asyncio.subprocess.Process) -> None:
    """Reap the CLI and its MCP children on timeout, cancellation, or unload."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        elif process.returncode is None:
            process.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), 3)
    except TimeoutError:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


class LocalClaude:
    def __init__(self, command: str = "", config_dir: str = "") -> None:
        self.command = command.strip()
        self.config_dir = config_dir.strip()

    def executable(self) -> str:
        if self.command:
            candidate = os.path.expanduser(self.command)
            found = shutil.which(candidate)
            if found:
                return found
            raise ClaudeError("Configured Claude Code executable is unavailable.")
        candidates = [
            "claude",
            str(Path.home() / ".local/bin/claude"),
            str(Path.home() / ".npm-global/bin/claude"),
            "/opt/homebrew/bin/claude",
            "/usr/local/bin/claude",
        ]
        for candidate in candidates:
            if found := shutil.which(candidate):
                return found
        raise ClaudeError("Install Claude Code on the AstrBot host first.")

    def environment(self) -> dict[str, str]:
        # Select the local subscription explicitly.
        # API keys, gateways and inherited agent settings must not change billing.
        blocked = {
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_PROFILE",
            "ANTHROPIC_BETAS",
            "CLAUDECODE",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CODE_ENTRYPOINT",
            "CLAUDE_CODE_SSE_PORT",
            "CLAUDE_CODE_EXTRA_BODY",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
            "CLAUDE_SECURESTORAGE_CONFIG_DIR",
            "CLAUDE_CODE_PROJECT_DIR_NAME",
            "CLAUDE_CODE_SKIP_PROMPT_HISTORY",
            "CLAUDE_CODE_CHILD_SESSION",
            "CLAUDE_CODE_RESUME_INTERRUPTED_TURN",
            "CLAUDE_CODE_RESUME_PROMPT",
            "CLAUDE_CODE_EFFORT_LEVEL",
        }
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in blocked and not k.startswith("ANTHROPIC_FEDERATION_")
        }
        if self.config_dir:
            env["CLAUDE_CONFIG_DIR"] = str(Path(self.config_dir).expanduser().resolve())
        env.update(
            ENABLE_CLAUDEAI_MCP_SERVERS="0",
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
            DISABLE_AUTO_COMPACT="1",
        )
        return env

    async def spawn(self, *args: str, cwd: str) -> asyncio.subprocess.Process:
        try:
            return await asyncio.create_subprocess_exec(
                self.executable(),
                *args,
                cwd=cwd,
                env=self.environment(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=os.name == "posix",
                limit=8 * 1024 * 1024,
            )
        except OSError:
            raise ClaudeError(
                "Could not start the configured Claude Code executable."
            ) from None

    async def status(self) -> dict[str, Any]:
        """Whitelist CLI status fields; never read or return the credential store."""
        try:
            self.executable()
        except ClaudeError:
            return {"status": "cli_missing"}
        process = await self.spawn(
            "--setting-sources", "", "auth", "status", cwd=str(Path.home())
        )
        try:
            async with asyncio.timeout(15):
                assert process.stdout and process.stdin
                process.stdin.close()
                raw = bytearray()
                while chunk := await process.stdout.read(65537 - len(raw)):
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        return {"status": "unknown"}
                await process.wait()
                data = json.loads(raw)
                if not isinstance(data, dict):
                    return {"status": "unknown"}
                if data.get("loggedIn") is not True:
                    return {"status": "not_logged_in"}
                if process.returncode != 0:
                    return {"status": "unknown"}
                if data.get("authMethod") != "claude.ai":
                    return {"status": "wrong_auth"}
                result: dict[str, Any] = {"status": "ready"}
                for key, target in (
                    ("email", "email"),
                    ("subscriptionType", "plan_type"),
                    ("orgId", "org_id"),
                ):
                    if isinstance(data.get(key), str):
                        result[target] = data[key][:200]
                return result
        except (TimeoutError, ValueError, UnicodeError):
            return {"status": "unknown"}
        finally:
            await stop_process(process)

    async def require_login(self) -> dict[str, Any]:
        status = await self.status()
        if status["status"] != "ready":
            messages = {
                "cli_missing": "Install Claude Code on the AstrBot host first.",
                "wrong_auth": "Claude Code must use a Claude subscription, not an API key or gateway.",
                "not_logged_in": "Run claude auth login as the AstrBot host user, then refresh status.",
                "unknown": "Cannot check Claude Code login. Check the CLI version and host permissions.",
            }
            raise ClaudeError(messages[status["status"]])
        return status
