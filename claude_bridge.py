"""Bridge Claude Code streaming and MCP tool turns into AstrBot responses."""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from aiohttp import web
from astrbot.api import logger
from astrbot.core.provider.entities import LLMResponse, TokenUsage

from .claude_sessions import SessionStore, claim, digest, message_hashes
from .local_claude import ClaudeError, LocalClaude, stop_process


def render_prompt(payload: dict, tools: list[dict]) -> list[dict]:
    """Keep the CLI preset, carrying caller instructions and history explicitly."""
    blocks = []
    system = payload.get("system", "")
    if isinstance(system, list):
        system = "\n".join(p.get("text", "") for p in system)
    if system:
        blocks.append(
            {
                "type": "text",
                "text": "<external_system_instructions>\n"
                + system
                + "\n</external_system_instructions>",
            }
        )
    names = {t["name"] for t in tools}
    for index, message in enumerate(payload["messages"]):
        label = "Assistant" if message["role"] == "assistant" else "Human"
        label = (
            "Current turn — " if index == len(payload["messages"]) - 1 else "History — "
        ) + label
        blocks.append({"type": "text", "text": label + ":"})
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for part in content:
            kind = part.get("type")
            if kind in {"text", "image", "document"}:
                blocks.append({k: v for k, v in part.items() if k != "cache_control"})
            elif kind == "tool_use":
                name = part["name"]
                if name in names:
                    name = "mcp__astrbot__" + name
                blocks.append(
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "tool_call": name,
                                "id": part["id"],
                                "arguments": part["input"],
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
            elif kind == "tool_result":
                blocks.append(
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "tool_result": part["tool_use_id"],
                                "content": part.get("content", ""),
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
            elif kind not in {"thinking", "redacted_thinking"}:
                raise ClaudeError(
                    "This content type is not supported by the Claude bridge."
                )
    return blocks


def mcp_content(content) -> list[dict]:
    """Translate Anthropic tool-result blocks into MCP's content schema."""
    if isinstance(content, str):
        return [{"type": "text", "text": content or "<empty result>"}]
    blocks = []
    for part in content:
        kind = part.get("type")
        if kind == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif kind == "image" and part.get("source", {}).get("type") == "base64":
            source = part["source"]
            blocks.append(
                {
                    "type": "image",
                    "data": source["data"],
                    "mimeType": source["media_type"],
                }
            )
        else:
            raise ClaudeError(
                "This tool result content type is not supported by the Claude bridge."
            )
    return blocks or [{"type": "text", "text": "<empty result>"}]


def tool_reply(messages: list[dict]) -> tuple[dict, list[dict]]:
    # AstrBot appends cached tool images as a separate user message after results.
    tail = []
    for message in reversed(messages):
        if message.get("role") != "user":
            break
        tail.append(message)
    results, extra = {}, []
    for message in reversed(tail):
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for part in content:
            if part.get("type") == "tool_result":
                results[part["tool_use_id"]] = part
            else:
                extra.append(part)
    return results, extra


class ClaudeRun:
    """One CLI conversation, live between turns or recoverable from a checkpoint."""

    def __init__(
        self,
        host: LocalClaude,
        store: SessionStore,
        payload: dict,
        tools: list[dict],
        owner: str | None,
        identity: dict,
        key: str,
        effort: str,
        session: str | None = None,
        lease=None,
    ) -> None:
        self.host = host
        self.payload = deepcopy(payload)
        self.tools = deepcopy(tools)
        self.owner = owner
        self.identity = identity
        self.store = store
        self.key, self.effort = key, effort
        self.session = session or store.new()
        self.directory = store.directory(self.session)
        self.lease = lease or claim(self.directory)
        if self.lease is None:
            raise ClaudeError("Claude session is already in use.")
        self.resuming = session is not None
        self.persistent = bool(owner and identity.get("email")) and store.prepare(host)
        self.history: list[str] = []
        self.idle = False
        self.used = time.monotonic()
        self.controls: dict[str, asyncio.Future] = {}
        self.token = secrets.token_urlsafe(32)
        self.events: asyncio.Queue = asyncio.Queue(maxsize=128)
        self.pending: dict[str, asyncio.Future] = {}
        self.issued: set[str] = set()
        self.process: asyncio.subprocess.Process | None = None
        self.reader: asyncio.Task | None = None
        self.expiry: asyncio.TimerHandle | None = None
        self.server: web.AppRunner | None = None
        self.closed = False
        self.lock = asyncio.Lock()

    async def rpc(self, request: web.Request) -> web.Response:
        if not secrets.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + self.token
        ):
            raise web.HTTPForbidden()
        message = await request.json()
        if not isinstance(message, dict):
            raise web.HTTPBadRequest()
        method = message.get("method")
        result: Any
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "astrbot", "version": "1.0.0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "inputSchema": t["input_schema"],
                    }
                    for t in self.tools
                ]
            }
        elif method == "ping":
            result = {}
        elif method == "tools/call":
            params = message.get("params") or {}
            name, arguments = params.get("name"), params.get("arguments", {})
            if (
                self.closed
                or name not in {t["name"] for t in self.tools}
                or not isinstance(arguments, dict)
            ):
                raise web.HTTPBadRequest()
            call_id = "claude-tool-" + secrets.token_hex(16)
            future = asyncio.get_running_loop().create_future()
            self.pending[call_id] = future
            await self.events.put(
                {
                    "type": "astrbot_tool",
                    "id": call_id,
                    "name": name,
                    "arguments": arguments,
                }
            )
            try:
                result = await future
            finally:
                self.pending.pop(call_id, None)
        else:
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
        return web.json_response(
            {"jsonrpc": "2.0", "id": message.get("id"), "result": result}
        )

    async def start(self, effort: str) -> None:
        app = web.Application(client_max_size=8 * 1024 * 1024)
        app.router.add_post("/rpc", self.rpc)
        self.server = web.AppRunner(app, access_log=None)
        await self.server.setup()
        site = web.TCPSite(self.server, "127.0.0.1", 0)
        await site.start()
        port = self.server.addresses[0][1]
        callback = self.directory / "callback.json"
        with callback.open("w", encoding="utf-8") as f:
            callback.chmod(0o600)
            json.dump({"url": f"http://127.0.0.1:{port}/rpc", "token": self.token}, f)
        mcp = json.dumps(
            {
                "mcpServers": {
                    "astrbot": {
                        "command": sys.executable,
                        "args": [
                            str(Path(__file__).with_name("claude_mcp.py")),
                            str(callback),
                        ],
                    }
                }
            }
            if self.tools
            else {"mcpServers": {}}
        )
        args = [
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--model",
            self.payload["model"],
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            mcp,
            "--setting-sources",
            "",
            "--disable-slash-commands",
        ]
        if self.resuming:
            args += ["--resume", self.session]
        else:
            args += ["--session-id", self.session]
        if not self.persistent:
            args += ["--no-session-persistence"]
        if self.tools:
            args += [
                "--allowedTools",
                ",".join("mcp__astrbot__" + t["name"] for t in self.tools),
            ]
        if effort:
            args += ["--effort", effort]
        self.process = await self.host.spawn(*args, cwd=str(self.store.work))
        self.reader = asyncio.create_task(self.read())
        if self.resuming:
            await self.initialize()

    async def tell(self, message: dict) -> None:
        assert self.process and self.process.stdin
        try:
            self.process.stdin.write(
                (json.dumps(message, ensure_ascii=False) + "\n").encode()
            )
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            raise ClaudeError("Claude Code closed its input.") from None

    async def initialize(self) -> None:
        request_id = secrets.token_hex(16)
        reply = asyncio.get_running_loop().create_future()
        self.controls[request_id] = reply
        try:
            await self.tell(
                {
                    "type": "control_request",
                    "request_id": request_id,
                    "request": {"subtype": "initialize"},
                }
            )
            async with asyncio.timeout(10):
                if not await reply:
                    raise ClaudeError(
                        "Claude Code could not restore the saved session."
                    )
        except TimeoutError:
            raise ClaudeError("Claude Code session recovery timed out.") from None
        finally:
            self.controls.pop(request_id, None)

    async def prompt(self, messages: list[dict], *, full: bool) -> None:
        payload = {**self.payload, "messages": messages}
        if not full:
            payload.pop("system", None)
        await self.tell(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": render_prompt(payload, self.tools),
                },
            }
        )

    async def read(self) -> None:
        assert self.process and self.process.stdout
        try:
            while line := await self.process.stdout.readline():
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    raise ClaudeError(
                        "Claude Code returned an invalid stream. Update the CLI and retry."
                    ) from None
                if isinstance(event, dict):
                    if event.get("type") == "control_response":
                        response = event.get("response", {})
                        future = self.controls.get(response.get("request_id"))
                        if future and not future.done():
                            future.set_result(response.get("subtype") == "success")
                    else:
                        await self.events.put(event)
            await self.events.put({"type": "bridge_error"})
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, ClaudeError):
            await self.events.put({"type": "bridge_error"})
        finally:
            for future in self.controls.values():
                if not future.done():
                    future.set_result(False)

    async def close(self, *, keep_session: bool = False) -> None:
        if self.closed:
            return
        self.closed = True
        while not self.events.empty():
            self.events.get_nowait()
        self.events.put_nowait({"type": "bridge_error"})
        if self.expiry:
            self.expiry.cancel()
        for future in list(self.pending.values()):
            if not future.done():
                future.set_result(
                    {
                        "isError": True,
                        "content": [{"type": "text", "text": "AstrBot request ended."}],
                    }
                )
        if self.process:
            await stop_process(self.process)
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        if self.server:
            await self.server.cleanup()
        (self.directory / "callback.json").unlink(missing_ok=True)
        if not keep_session:
            self.store.invalidate(self.session)
        self.lease.close()
        if not keep_session:
            self.store.discard(self.session)


class ClaudeBridge:
    def __init__(self, host: LocalClaude, root: Path, timeout: float = 180) -> None:
        self.host, self.root, self.timeout = host, root, timeout
        self.runs: set[ClaudeRun] = set()
        self.manager = asyncio.Lock()
        self.idle_timeout = 300
        self.max_runs = 8
        self.max_idle = 4
        self.closed = False
        self.tasks: set[asyncio.Task] = set()
        self._store: SessionStore | None = None

    @property
    def store(self) -> SessionStore:
        if self._store is None:
            self._store = SessionStore(self.root)
        return self._store

    def schedule(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)

        def completed(task):
            self.tasks.discard(task)
            if not task.cancelled() and task.exception() is not None:
                logger.warning(
                    "Claude session cleanup failed; check data directory permissions."
                )

        task.add_done_callback(completed)

    async def discard(self, run: ClaudeRun, *, keep_session: bool = False) -> None:
        try:
            await run.close(keep_session=keep_session)
        finally:
            self.runs.discard(run)

    async def shelve(self, run: ClaudeRun) -> None:
        async with self.manager:
            if run in self.runs and run.idle and not run.lock.locked():
                await self.discard(run, keep_session=run.persistent)
                self.store.saved({r.session for r in self.runs})

    async def trim_idle(self) -> None:
        async with self.manager:
            idle = sorted((r for r in self.runs if r.idle), key=lambda r: r.used)
            for run in idle[: max(0, len(idle) - self.max_idle)]:
                if not run.lock.locked():
                    await self.discard(run, keep_session=run.persistent)
            self.store.saved({r.session for r in self.runs})

    async def close(self) -> None:
        self.closed = True
        async with self.manager:
            await asyncio.gather(
                *(
                    self.discard(r, keep_session=r.idle and r.persistent)
                    for r in list(self.runs)
                )
            )
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self._store is not None:
            self.store.saved(set())

    def key(self, payload, tools, owner, identity, effort) -> str:
        return digest(
            {
                "owner": owner,
                "identity": identity,
                "effort": effort,
                "tools": tools,
                "settings": {k: v for k, v in payload.items() if k != "messages"},
                "host": self.host.executable(),
                "config": self.host.environment().get("CLAUDE_CONFIG_DIR", ""),
            }
        )

    async def select(self, payload, tools, owner, identity, effort, results):
        key = self.key(payload, tools, owner, identity, effort)
        messages = payload["messages"]
        history = message_hashes(messages)
        async with self.manager:
            if self.closed:
                raise ClaudeError("Claude provider has stopped.")
            run = next((r for r in self.runs if r.issued.intersection(results)), None)
            if results:
                if run is None:
                    raise ClaudeError(
                        "The Claude tool session has expired. Start a new turn."
                    )
                if (
                    run.closed
                    or run.lock.locked()
                    or run.key != key
                    or message_hashes(messages[: len(run.payload["messages"])])
                    != message_hashes(run.payload["messages"])
                    or not run.issued.issubset(results)
                ):
                    raise ClaudeError(
                        "Claude tool results do not match the active request or account."
                    )
                if run.expiry:
                    run.expiry.cancel()
                return run, None

            def follows(prefix):
                return (
                    bool(prefix)
                    and len(history) > len(prefix)
                    and history[: len(prefix)] == prefix
                )

            candidates = (
                [
                    r
                    for r in self.runs
                    if r.idle and not r.closed and r.key == key and follows(r.history)
                ]
                if owner and identity.get("email")
                else []
            )
            if candidates:
                run = max(candidates, key=lambda r: len(r.history))
                if run.process and run.process.returncode is not None:
                    await self.discard(run, keep_session=run.persistent)
                else:
                    run.idle = False
                    if run.expiry:
                        run.expiry.cancel()
                    self.store.invalidate(run.session)
                    return run, len(run.history)
            if len(self.runs) >= self.max_runs:
                idle = [r for r in self.runs if r.idle and not r.lock.locked()]
                if not idle:
                    raise ClaudeError(
                        "Too many active Claude requests. Wait for a running request to finish."
                    )
                old = min(idle, key=lambda r: r.used)
                await self.discard(old, keep_session=old.persistent)
            saved = self.store.saved({r.session for r in self.runs})
            matches = [
                (sid, state)
                for sid, state in saved
                if owner
                and identity.get("email")
                and state["key"] == key
                and follows(state["history"])
            ]
            session, since, lease = None, None, None
            for sid, state in sorted(
                matches, key=lambda item: len(item[1]["history"]), reverse=True
            ):
                lease = claim(self.store.directory(sid))
                if lease is not None:
                    # Another bridge may have advanced the checkpoint since scanning.
                    try:
                        current = json.loads(
                            (self.store.directory(sid) / "state.json").read_text()
                        )
                    except (OSError, ValueError):
                        current = None
                    if current != state:
                        lease.close()
                        lease = None
                        continue
                    session, since = sid, len(state["history"])
                    self.store.invalidate(session)
                    break
            run = ClaudeRun(
                self.host,
                self.store,
                payload,
                tools,
                owner,
                identity,
                key,
                effort,
                session,
                lease,
            )
            self.runs.add(run)
            return run, since

    async def stream(
        self,
        payload: dict,
        tools: list[dict],
        *,
        owner: str | None = None,
        effort: str = "",
    ):
        identity = await self.host.require_login()
        messages = payload.get("messages", [])
        results, extra = tool_reply(messages)
        run, since = await self.select(payload, tools, owner, identity, effort, results)
        parked = False
        final = LLMResponse(role="assistant", reasoning_content="")
        streamed_text = ""
        assistant_text = ""
        try:
            async with run.lock, asyncio.timeout(self.timeout):
                if run.expiry:
                    run.expiry.cancel()
                if run.process is None:
                    try:
                        await run.start(effort)
                    except (ClaudeError, OSError):
                        if not run.resuming:
                            raise
                        # No user input has been sent yet, so fallback cannot replay a turn.
                        await self.discard(run)
                        run, since = await self.select(
                            payload, tools, owner, identity, effort, {}
                        )
                        await run.start(effort)
                    await run.prompt(
                        messages[since:] if since is not None else messages,
                        full=since is None,
                    )
                elif since is not None:
                    await run.prompt(messages[since:], full=False)
                else:
                    calls = sorted(run.issued)
                    for index, call_id in enumerate(calls):
                        result = results[call_id]
                        content = mcp_content(result.get("content", ""))
                        if extra and index == len(calls) - 1:
                            content += [
                                {
                                    "type": "text",
                                    "text": "Additional user context supplied with tool results:",
                                }
                            ]
                            content += mcp_content(extra)
                        future = run.pending.get(call_id)
                        if future is None or future.done():
                            raise ClaudeError("The Claude tool session has expired.")
                        future.set_result(
                            {
                                "content": content,
                                "isError": bool(result.get("is_error")),
                            }
                        )
                    run.issued.clear()
                run.payload = deepcopy(payload)
                while True:
                    item = await run.events.get()
                    kind = item.get("type")
                    if kind == "bridge_error":
                        raise ClaudeError(
                            "Claude Code exited before completing the request. Check the host login and CLI version."
                        )
                    if kind == "astrbot_tool":
                        run.issued.add(item["id"])
                        final.completion_text = streamed_text or assistant_text
                        final.tools_call_ids = [item["id"]]
                        final.tools_call_name = [item["name"]]
                        final.tools_call_args = [item["arguments"]]
                        run.expiry = asyncio.get_running_loop().call_later(
                            300, lambda: self.schedule(self.discard(run))
                        )
                        parked = True
                        yield final
                        return
                    if kind == "stream_event":
                        event = item.get("event", {})
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            streamed_text += text
                            yield LLMResponse(
                                role="assistant", completion_text=text, is_chunk=True
                            )
                        elif delta.get("type") == "thinking_delta":
                            text = delta.get("thinking", "")
                            final.reasoning_content += text
                            yield LLMResponse(
                                role="assistant", reasoning_content=text, is_chunk=True
                            )
                    elif kind == "assistant":
                        message = item.get("message", {})
                        assistant_text += "".join(
                            p.get("text", "")
                            for p in message.get("content", [])
                            if p.get("type") == "text"
                        )
                    elif kind == "result":
                        if item.get("is_error") or item.get("subtype") != "success":
                            raise ClaudeError(
                                "Claude Code could not complete the request. Check subscription allowance and local login."
                            )
                        final.completion_text = (
                            streamed_text or assistant_text or item.get("result", "")
                        )
                        usage = item.get("usage") or {}
                        final.usage = TokenUsage(
                            input_other=usage.get("input_tokens", 0)
                            + usage.get("cache_creation_input_tokens", 0),
                            input_cached=usage.get("cache_read_input_tokens", 0),
                            output=usage.get("output_tokens", 0),
                        )
                        if not final.completion_text and not final.reasoning_content:
                            raise ClaudeError("Claude Code returned an empty response.")
                        if owner and identity.get("email"):
                            run.history = message_hashes(
                                messages
                                + [
                                    {
                                        "role": "assistant",
                                        "content": final.completion_text,
                                    }
                                ]
                            )
                            run.used = time.monotonic()
                            if run.persistent:
                                try:
                                    self.store.save(run.session, run.key, run.history)
                                except OSError:
                                    run.persistent = False
                                    logger.warning(
                                        "Claude checkpoint could not be saved; keeping live reuse only."
                                    )
                            # Publish the checkpoint only after the consumer accepts the reply.
                            parked = True
                            yield final
                            run.idle = True
                            run.expiry = asyncio.get_running_loop().call_later(
                                self.idle_timeout,
                                lambda: self.schedule(self.shelve(run)),
                            )
                            self.schedule(self.trim_idle())
                        else:
                            yield final
                        return
        except TimeoutError:
            raise ClaudeError("Claude Code request timed out.") from None
        except BaseException:
            parked = False
            raise
        finally:
            if not parked:
                await self.discard(run)
