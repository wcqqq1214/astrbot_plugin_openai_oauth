"""Bridge Codex citations and search activity to AstrBot WebChat."""

from __future__ import annotations

import json
import re
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from contextlib import aclosing
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from functools import wraps
from inspect import isasyncgenfunction, iscoroutinefunction, signature
from itertools import accumulate
from typing import Any
from urllib.parse import urlsplit


def _display_parts(parts: list[dict], refs: Iterable[dict]) -> list[dict]:
    """Collapse a domain-only citation link directly followed by its native card."""
    rendered = list(parts)
    for ref in refs:
        index = str(ref.get("index", ""))
        if not re.fullmatch(r"codex-[0-9]+", index):
            continue
        url = ref.get("url")
        if not isinstance(url, str):
            continue
        try:
            host = urlsplit(url).hostname
        except ValueError:
            continue
        if not host:
            continue
        label = re.escape(host.removeprefix("www."))
        if host.startswith("www."):
            label = rf"(?:www\.)?{label}"
        link = rf"\[{label}\]\({re.escape(url)}\)"
        # Multiple cards may share a citation offset. Keep their order intact.
        duplicate = re.compile(
            rf"(?<![!\\])(?:\({link}\)|（{link}）|{link})"
            rf"(?=[ \t]*(?:<ref>codex-[0-9]+</ref>)*<ref>{index}</ref>)"
        )
        for i, part in enumerate(rendered):
            if part.get("type") == "plain":
                text = part["text"]
                compact = duplicate.sub("", text)
                if compact != text:
                    rendered[i] = {**part, "text": compact}
    return rendered


@dataclass
class CitationText:
    """OpenAI offsets are local to one output_text content part."""

    text: str = ""
    marks: dict[tuple[int, str], None] = field(default_factory=dict)


@dataclass
class _CitationRun:
    """Bind live snapshots and history writes to the lifetime of one consumer."""

    service: Any
    run: Any
    sources: dict[str, dict[str, str]] = field(default_factory=dict)

    responses: list[tuple[int, dict[tuple[int, int], CitationText]]] = field(
        default_factory=list
    )
    raw_parts: list[dict] = field(default_factory=list)
    rendered_parts: list[dict] | None = None
    visible_marks: list[tuple[int, str]] = field(default_factory=list)

    def __getattr__(self, name):
        return getattr(self.service, name)

    def render(self, parts: list[dict]) -> tuple[list[dict], list[tuple[int, str]]]:
        # The host may split one output_text across several plain message parts.
        plain = [
            (i, part["text"]) for i, part in enumerate(parts) if part["type"] == "plain"
        ]
        body = "".join(text for _, text in plain)
        boundaries = list(accumulate(len(text) for _, text in plain))
        cursor = 0
        marks = []
        for response_start, response in self.responses:
            cursor = max(cursor, response_start)
            for key in sorted(response):
                content = response[key]
                start = body.find(content.text, cursor)
                if start < 0:
                    # Text deltas can be queued behind their citation event.
                    if not content.text.startswith(body[cursor:]):
                        continue
                    start = cursor
                for end, ref in content.marks:
                    if end <= len(content.text) and start + end <= len(body):
                        marks.append((start + end, ref))
                cursor = start + len(content.text)

        rendered = list(parts)
        # Insert from right to left to preserve the original character offsets.
        marks.sort(key=lambda mark: mark[0])
        for end, ref in reversed(marks):
            part = bisect_left(boundaries, end)
            i = plain[part][0]
            pos = end - (boundaries[part - 1] if part else 0)
            text = rendered[i]["text"]
            rendered[i] = {
                **parts[i],
                "text": f"{text[:pos]}<ref>{ref}</ref>{text[pos:]}",
            }
        return rendered, marks

    def refresh(self) -> bool:
        if self.run.message_parts is not self.rendered_parts:
            self.raw_parts = self.run.message_parts
        parts, marks = self.render(self.raw_parts)
        self.rendered_parts = _display_parts(parts, self.sources.values())
        self.run.message_parts = self.rendered_parts
        changed = marks != self.visible_marks
        self.visible_marks = marks
        return changed

    def publish_snapshot(self) -> None:
        run = self.run
        for snapshot in self.service.get_active_chat_runs(run.username, run.session_id):
            if snapshot["run_id"] == run.run_id:
                self.service._publish_chat_run(
                    run, {"type": "run_snapshot", "data": snapshot}
                )
                break

    def _publish_chat_run(self, run, payload):
        changed = self.sources and self.refresh()
        self.service._publish_chat_run(run, payload)
        if changed:
            self.publish_snapshot()

    async def save_bot_message(
        self, webchat_conv_id, message_parts, agent_stats, refs, *args, **kwargs
    ):
        if self.sources:
            refs = self.merge_refs(refs)
            self.run.refs = refs
            message_parts, _ = self.render(message_parts)
        return await self.service.save_bot_message(
            webchat_conv_id, message_parts, agent_stats, refs, *args, **kwargs
        )

    def merge_refs(self, refs: dict) -> dict:
        used = refs.get("used", [])
        native_indices = {source["index"] for source in self.sources.values()}
        # Keep original tool indices, even when a native citation has the same URL.
        tools = [ref for ref in used if ref.get("index") not in native_indices]
        return {**refs, "used": [*tools, *self.sources.values()]}


_producer: ContextVar[_CitationRun | None] = ContextVar(
    "codex_chatui_citation_producer", default=None
)


def begin_response() -> dict[tuple[int, int], CitationText] | None:
    state = _producer.get()
    if state is None:
        return None
    response: dict[tuple[int, int], CitationText] = defaultdict(CitationText)
    parts = (
        state.raw_parts
        if state.run.message_parts is state.rendered_parts
        else state.run.message_parts
    )
    start = sum(len(part["text"]) for part in parts if part["type"] == "plain")
    state.responses.append((start, response))
    return response


def publish(
    content: CitationText, citations: list[tuple[str, str, int | None]]
) -> None:
    state = _producer.get()
    if state is None or state.run.status != "running":
        return
    changed = False
    for url, title, end in citations:
        if url not in state.sources:
            state.sources[url] = {
                "index": f"codex-{len(state.sources) + 1}",
                "url": url,
                "title": title,
            }
            changed = True
        if end is not None:
            key = (end, state.sources[url]["index"])
            if key not in content.marks:
                content.marks[key] = None
                changed = True
    if changed:
        state.run.refs = state.merge_refs(state.run.refs)
        state.refresh()
        state.publish_snapshot()


def web_search_publisher() -> Callable[[str, dict], Awaitable[bool]] | None:
    """Capture the current ChatUI run for tool frames and stream cleanup."""
    state = _producer.get()
    if state is None:
        return None

    from astrbot.core.platform.sources.webchat.webchat_queue_mgr import (
        webchat_queue_mgr,
    )

    run = state.run

    async def publish_tool_frame(chain_type: str, data: dict) -> bool:
        if run.status != "running":
            return False
        return await webchat_queue_mgr.put_back_queue(
            run.run_id,
            {
                "type": "plain",
                "chain_type": chain_type,
                "streaming": True,
                "message_id": run.run_id,
                "data": json.dumps(data, ensure_ascii=False),
            },
        )

    return publish_tool_frame


def install() -> Callable[[], None]:
    """Bridge supported WebChat runs without changing AstrBot files."""
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
    from astrbot.core.platform.sources.webchat.webchat_event import WebChatMessageEvent
    from astrbot.dashboard.services import chat_service

    service = chat_service.ChatService
    runner = ToolLoopAgentRunner
    consume = service._consume_chat_run
    stream_name = (
        "_recorded_responses"
        if hasattr(runner, "_recorded_responses")
        else "_iter_llm_responses"
    )
    stream = getattr(runner, stream_name)
    if not iscoroutinefunction(consume) or not isasyncgenfunction(stream):
        raise TypeError("WebChat citation hooks are unavailable")
    signature(consume).bind(None, None)
    if stream_name == "_recorded_responses":
        signature(stream).bind(None, {}, contexts=[], streaming=True)
    else:
        signature(stream).bind(None, include_model=True)
    signature(service._publish_chat_run).bind(None, {})
    signature(service.get_active_chat_runs).bind(None, "", "")
    if not {"run_id", "username", "session_id", "status", "refs"} <= {
        field.name for field in fields(chat_service.ChatRunState)
    }:
        raise TypeError("WebChat citation state is unavailable")

    active_runs: dict[str, _CitationRun] = {}

    @wraps(consume)
    async def consume_run(self, run):
        state = _CitationRun(self, run)
        active_runs[run.run_id] = state
        try:
            return await consume(state, run)
        finally:
            active_runs.pop(run.run_id, None)

    @wraps(stream)
    async def stream_response(self, *args, **kwargs):
        context = getattr(getattr(self, "run_context", None), "context", None)
        event = getattr(context, "event", None)
        state = (
            active_runs.get(str(event.message_obj.message_id))
            if isinstance(event, WebChatMessageEvent)
            and getattr(context, "send_to_user", True)
            else None
        )
        async with aclosing(stream(self, *args, **kwargs)) as responses:
            while True:
                token = _producer.set(state)
                try:
                    response = await anext(responses)
                except StopAsyncIteration:
                    return
                finally:
                    _producer.reset(token)
                yield response

    serialize_history = chat_service.serialize_history_entry

    @wraps(serialize_history)
    def serialize_entry(history):
        entry = serialize_history(history)
        content = entry["content"]
        if content.get("type") == "bot" and content.get("refs"):
            content["message"] = _display_parts(
                content["message"], content["refs"].get("used", [])
            )
        return entry

    hooks = (
        (chat_service, "serialize_history_entry", serialize_entry, serialize_history),
        (service, "_consume_chat_run", consume_run, consume),
        (runner, stream_name, stream_response, stream),
    )

    def remove() -> None:
        for owner, name, installed, original in hooks:
            if getattr(owner, name) is installed:
                setattr(owner, name, original)

    for owner, name, installed, _ in hooks:
        setattr(owner, name, installed)
    return remove
