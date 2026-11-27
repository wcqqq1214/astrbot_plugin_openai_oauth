"""Forward provider-hosted web search activity to the current ChatUI run."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field
from time import time
from typing import Any

from . import chatui_citations, messages


@dataclass
class _SearchCall:
    started_at: float = field(default_factory=time)
    args: dict = field(default_factory=dict)
    status: str = "running"
    finished_at: float | None = None


@asynccontextmanager
async def track_web_search(stream: Any, get: Callable, language: str | None):
    publish = chatui_citations.web_search_publisher()
    if publish is None:
        yield stream
        return

    calls: dict[str, _SearchCall] = {}

    async def update(item_id: str, status: str, args: dict) -> None:
        call = calls.get(item_id)
        new_card = call is None
        if call is None:
            call = calls[item_id] = _SearchCall()
        if status in ("in_progress", "searching"):
            status = call.status

        # Lifecycle events carry a status; output items carry the actual action.
        arguments = {**call.args, **args}
        if call.args == arguments and call.status == status and not new_card:
            return
        call.args, call.status = arguments, status
        if status != "running" and call.finished_at is None:
            call.finished_at = time()
        label = messages.text(f"search.{status}", lang=language)
        frame = {
            "id": f"codex-web-search:{item_id}",
            "name": f"OpenAI web_search · {label}",
            "args": arguments,
            "ts": call.started_at,
        }
        if call.finished_at is not None:
            frame["finished_ts"] = call.finished_at
        await publish("tool_call", frame)

    async def observe_item(item: Any) -> None:
        if get(item, "type") != "web_search_call":
            return
        action = get(item, "action")
        args = {
            key: value
            for key in ("query", "queries", "url", "pattern")
            if (value := get(action, key))
        }
        if kind := get(action, "type"):
            args["action"] = kind
        await update(get(item, "id"), get(item, "status"), args)

    async def events() -> AsyncIterator[Any]:
        async for event in stream:
            event_type = get(event, "type")
            if event_type.startswith("response.web_search_call."):
                await update(get(event, "item_id"), event_type.rsplit(".", 1)[1], {})
            elif event_type in (
                "response.output_item.added",
                "response.output_item.done",
            ):
                await observe_item(get(event, "item"))
            elif event_type in (
                "response.completed",
                "response.incomplete",
                "response.failed",
            ):
                for item in get(get(event, "response"), "output") or []:
                    await observe_item(item)
            yield event

    try:
        async with aclosing(events()) as tracked:
            yield tracked
    finally:
        for item_id, call in calls.items():
            if call.finished_at is None:
                await update(item_id, "interrupted", {})
            await publish(
                "tool_call_result",
                {
                    "id": f"codex-web-search:{item_id}",
                    "result": "",
                    "ts": call.finished_at,
                },
            )
