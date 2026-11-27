"""Adapt Codex citations to AstrBot's existing WebChat reference payload."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import aclosing
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from functools import wraps
from inspect import isasyncgenfunction, iscoroutinefunction, signature
from typing import Any


@dataclass
class _CitationRun:
    """Bind live snapshots and history writes to the lifetime of one consumer."""

    service: Any
    run: Any
    sources: dict[str, dict[str, str]] = field(default_factory=dict)

    # This part belongs to ChatUI. It never enters the provider's Markdown stream.
    cards: dict[str, str] = field(default_factory=lambda: {"type": "plain", "text": ""})

    def __getattr__(self, name):
        return getattr(self.service, name)

    def insert_cards(self, parts: list[dict]) -> None:
        # ChatUI folds everything through the last reasoning or tool block.
        start = len(parts)
        while start and parts[start - 1]["type"] not in ("think", "tool_call"):
            start -= 1
        if start == len(parts) or parts[start] is not self.cards:
            parts.insert(start, self.cards)

    def publish_snapshot(self) -> None:
        run = self.run
        for snapshot in self.service.get_active_chat_runs(run.username, run.session_id):
            if snapshot["run_id"] == run.run_id:
                self.service._publish_chat_run(
                    run, {"type": "run_snapshot", "data": snapshot}
                )
                break

    def _publish_chat_run(self, run, payload):
        # The host rebuilds message_parts from its accumulator before each frame.
        if self.sources:
            self.insert_cards(run.message_parts)
            if payload.get("chain_type") in (
                "reasoning",
                "tool_call",
                "tool_call_result",
            ):
                # An appended work delta would move the cards into the collapsed block.
                self.publish_snapshot()
                return
        self.service._publish_chat_run(run, payload)

    async def save_bot_message(
        self, webchat_conv_id, message_parts, agent_stats, refs, *args, **kwargs
    ):
        if self.sources:
            refs = self.merge_refs(refs)
            self.run.refs = refs
            message_parts = list(message_parts)
            self.insert_cards(message_parts)
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


def publish(citations: dict[str, str]) -> None:
    """Expose new citations in a separate native ChatUI message part."""
    state = _producer.get()
    if state is None or not citations:
        return

    run = state.run
    if run.status != "running":
        return
    added = False
    for url, title in citations.items():
        if url not in state.sources:
            state.sources[url] = {
                "index": f"codex-{len(state.sources) + 1}",
                "url": url,
                "title": title,
            }
            added = True
    if added:
        state.cards["text"] = (
            " ".join(
                f"<ref>{source['index']}</ref>" for source in state.sources.values()
            )
            + "\n\n"
        )
        run.refs = state.merge_refs(run.refs)
        state.insert_cards(run.message_parts)
        state.publish_snapshot()


def install() -> Callable[[], None]:
    """Bridge supported WebChat runs without changing AstrBot files."""
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
    from astrbot.core.platform.sources.webchat.webchat_event import WebChatMessageEvent
    from astrbot.dashboard.services import chat_service

    service = chat_service.ChatService
    runner = ToolLoopAgentRunner
    consume = service._consume_chat_run
    stream = runner._recorded_responses
    if not iscoroutinefunction(consume) or not isasyncgenfunction(stream):
        raise TypeError("WebChat citation hooks are unavailable")
    signature(consume).bind(None, None)
    signature(stream).bind(None, {}, contexts=[], streaming=True)
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

    hooks = (
        (service, "_consume_chat_run", consume_run, consume),
        (runner, "_recorded_responses", stream_response, stream),
    )

    def remove() -> None:
        for owner, name, installed, original in hooks:
            if getattr(owner, name) is installed:
                setattr(owner, name, original)

    for owner, name, installed, _ in hooks:
        setattr(owner, name, installed)
    return remove
