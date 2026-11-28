"""Bridge Codex citations and live search and image activity to AstrBot WebChat."""

from __future__ import annotations

import asyncio
import json
import re
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import aclosing, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from functools import wraps
from inspect import isasyncgenfunction, iscoroutinefunction, signature
from itertools import accumulate
from typing import Any
from urllib.parse import urlsplit

from astrbot.api import logger


def _display_parts(parts: list[dict], refs: Iterable[dict]) -> list[dict]:
    """Hide a URL-only link when its adjacent native card opens the same URL."""
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
        target = re.escape(url)
        # Bare URLs need their own boundaries: a URL may be part of another
        # destination, and a descriptive Markdown link ends in its URL too.
        bare = rf"(?<![^\s(（>])(?<!\]\(){target}(?=$|[\s)）。，！？]|<ref>)"
        link = rf"(?:\[(?:(?i:{label})|{target})\]\((?:{target}|<{target}>)\)|<{target}>|{bare})"
        wrapped = (
            rf"(?<![!\\\]])(?:\([ \t]*{link}[ \t]*\)|（[ \t]*{link}[ \t]*）|{link})"
        )
        other = r"<ref>codex-[0-9]+</ref>"
        cards = rf"(?:{other}[ \t]*)*<ref>{index}</ref>(?:[ \t]*{other})*"
        # The annotation may end on either side of the closing parenthesis.
        duplicate = re.compile(
            rf"(?<![!\\\]])(?P<opening>[(（])?"
            rf"(?:{wrapped}[ \t]*(?P<after>{cards})|(?P<before>{cards})[ \t]*{wrapped})"
            rf"(?P<closing>[)）])?"
        )

        def keep_cards(match: re.Match) -> str:
            opening = match["opening"] or ""
            closing = match["closing"] or ""
            tags = match["after"] or match["before"]
            if opening + closing in ("()", "（）"):
                return tags
            return opening + tags + closing

        for i, part in enumerate(rendered):
            if part.get("type") == "plain":
                text = part["text"]
                compact = duplicate.sub(keep_cards, text)
                if compact != text:
                    rendered[i] = {**part, "text": compact}
    return rendered


def _link_spans(text: str) -> Iterator[tuple[int, int]]:
    """Keep a citation inside a Markdown link from breaking its label or URL."""
    labels = []
    start = depth = 0
    for match in re.finditer(r"\\.|<https?://[^>\n]+>|\]\(|[][()]", text):
        token = match[0]
        if depth:
            if token in ("(", "]("):
                depth += 1
            elif token == ")":
                depth -= 1
                if not depth:
                    yield start, match.end()
        elif token.startswith("<"):
            yield match.span()
        elif token == "[":
            labels.append(match.start())
        elif token == "]" and labels:
            labels.pop()
        elif token == "](" and labels:
            start = labels.pop()
            depth = 1


@dataclass
class CitationText:
    """OpenAI offsets are local to one output_text content part."""

    text: str = ""
    marks: dict[tuple[int, str], None] = field(default_factory=dict)

    def positioned_marks(self) -> Iterator[tuple[int, str]]:
        spans = _link_spans(self.text)
        span = next(spans, None)
        inserted = set()
        for end, ref in sorted(self.marks, key=lambda mark: mark[0]):
            if end > len(self.text):
                continue
            while span and span[1] <= end:
                span = next(spans, None)
            if span and span[0] < end < span[1]:
                end = span[1]
            mark = (end, ref)
            if mark not in inserted:
                inserted.add(mark)
                yield mark


def _align_saved_links(text: str, indices: set[str]) -> str:
    """Recover original offsets from citation tags stored by earlier versions."""
    content = CitationText()
    cursor = 0
    for match in re.finditer(r"<ref>(codex-[0-9]+)</ref>", text):
        if match[1] in indices:
            content.text += text[cursor : match.start()]
            content.marks[len(content.text), match[1]] = None
            cursor = match.end()
    if not content.marks:
        return text
    content.text += text[cursor:]
    pieces = []
    cursor = 0
    for end, ref in content.positioned_marks():
        pieces.extend((content.text[cursor:end], f"<ref>{ref}</ref>"))
        cursor = end
    return "".join(pieces) + content.text[cursor:]


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
    hidden_chars: int = 0
    image_cards: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name):
        return getattr(self.service, name)

    def has_live_reply_image(self) -> bool:
        for run_id in self.service.chat_runs_by_session[self.run.session_id]:
            reply = self.service.chat_runs[run_id]
            if (
                reply is self.run
                or reply.username != self.run.username
                or reply.platform_history_id != self.run.platform_history_id
            ):
                continue
            if any(
                part.get("attachment_id")
                and (
                    part["type"] == "image"
                    or (part["type"] == "view" and part["name"] == "image_progress")
                )
                for part in reply.message_parts
            ):
                return True
        return False

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
                for end, ref in content.positioned_marks():
                    if start + end <= len(body):
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
            self.raw_parts = [
                p for p in self.run.message_parts if p.get("id") not in self.image_cards
            ]
        parts, marks = self.render(self.raw_parts)
        self.rendered_parts = _display_parts(parts, self.sources.values())
        self.run.message_parts = self.rendered_parts
        # A later text frame can finish a duplicate link after an existing card.
        hidden = sum(
            len(raw["text"]) - len(shown["text"])
            for raw, shown in zip(parts, self.rendered_parts)
            if raw is not shown
        )
        changed = marks != self.visible_marks or hidden != self.hidden_chars
        self.hidden_chars = hidden
        self.visible_marks = marks
        self.sync_image_indicator()
        return changed

    def sync_image_indicator(self) -> None:
        # AstrBot replaces the resumable snapshot after each frame. Its separate
        # reply accumulator handles history and never receives this image.
        present = {part.get("id") for part in self.run.message_parts}
        self.run.message_parts.extend(
            card.part for key, card in self.image_cards.items() if key not in present
        )

    def remove_card(self, card) -> None:
        self.run.message_parts[:] = [
            p for p in self.run.message_parts if p.get("id") != card.id
        ]
        self.image_cards.pop(card.id, None)
        card.ready.set()
        self.publish_image_snapshot()

    def close_cards(self) -> None:
        for card in list(self.image_cards.values()):
            self.remove_card(card)

    def publish_image_snapshot(self) -> None:
        try:
            self.publish_snapshot()
        except Exception as exc:  # noqa: BLE001 - optional UI feedback must not interrupt image delivery
            logger.debug(
                "Could not publish ChatUI image activity: %s", type(exc).__name__
            )

    def publish_snapshot(self) -> None:
        run = self.run
        for snapshot in self.service.get_active_chat_runs(run.username, run.session_id):
            if snapshot["run_id"] == run.run_id:
                self.service._publish_chat_run(
                    run, {"type": "run_snapshot", "data": snapshot}
                )
                break

    def _publish_chat_run(self, run, payload):
        if self.image_cards:
            if payload["type"] == "view":
                card = self.image_cards.pop(payload["data"]["id"], None)
                if card is not None:
                    # Replace the live placeholder with the persisted card without
                    # appending a second iframe or interrupting its download.
                    self.sync_image_indicator()
                    if self.sources:
                        self.refresh()
                    self.publish_image_snapshot()
                    return
            if payload["type"] == "end" or run.status != "running":
                self.close_cards()
            elif not self.sources:
                self.sync_image_indicator()
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

_active_runs: dict[str, _CitationRun] = {}


def active_chat_run(event: Any) -> _CitationRun | None:
    if not _active_runs:
        return None
    from astrbot.core.platform.sources.webchat.webchat_event import WebChatMessageEvent

    if isinstance(event, WebChatMessageEvent):
        return _active_runs.get(str(event.message_obj.message_id))
    return None


@asynccontextmanager
async def image_generation_indicator(event: Any):
    state = active_chat_run(event)
    if (
        state is None
        or state.run.status != "running"
        or not hasattr(state.service, "get_chat_view")
    ):
        yield None
        return
    from . import chatui_images

    card = await chatui_images.create(state)
    state.image_cards[card.id] = card
    state.sync_image_indicator()
    state.publish_image_snapshot()
    try:
        yield card
    finally:
        if not card.submitted:
            state.remove_card(card)
            await asyncio.to_thread(chatui_images.discard_unbound, card.id)


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
    global _active_runs
    from astrbot.api.event import AstrMessageEvent
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
    from astrbot.core.message.components import Image
    from astrbot.core.pipeline.process_stage.method.agent_sub_stages import internal
    from astrbot.core.platform.sources.webchat.webchat_event import WebChatMessageEvent
    from astrbot.dashboard.services import chat_service

    from . import bot_citations, messages, runtime
    from .image_generation import ImageError
    from .provider import ProviderOpenAICodex

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

    def edits_enabled(selected: str | None, umo: str) -> bool:
        if not runtime.get_plugin_config().get("image_enabled"):
            return False
        context = runtime.get_context()
        provider = (
            context.get_provider_by_id(selected)
            if selected
            else context.get_using_provider(umo=umo)
        )
        return isinstance(provider, ProviderOpenAICodex)

    build = service.build_chat_stream
    parse = service.build_user_message_parts
    chat_request: ContextVar[tuple[str | None, str] | None] = ContextVar(
        "codex_chatui_request", default=None
    )

    async def image_error_stream(message):
        for frame in ({"type": "error", "data": message}, {"type": "end"}):
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"

    @wraps(build)
    async def build_chat_stream(self, username, post_data, **kwargs):
        session = post_data.get("session_id") or post_data.get("conversation_id")
        umo = chat_service.build_thread_unified_msg_origin(username, session)
        token = chat_request.set((post_data.get("selected_provider"), umo))
        try:
            return await build(self, username, post_data, **kwargs)
        except ImageError as exc:
            lang = await messages.resolve_language(runtime.get_context(), umo)
            return image_error_stream(messages.text(str(exc), lang=lang))
        finally:
            chat_request.reset(token)

    @wraps(parse)
    async def build_user_message_parts(self, message):
        parts = await parse(self, message)
        request = chat_request.get()
        if request and isinstance(message, list):
            resolved = {
                part["attachment_id"] for part in parts if part["type"] == "image"
            }
            missing = any(
                isinstance(part, dict)
                and part.get("type") == "image"
                and str(part.get("attachment_id")) not in resolved
                for part in message
            )
            selected, umo = request
            if missing and edits_enabled(selected, umo):
                # Reject before an attachment-less turn is saved or can be regenerated.
                raise ImageError("image.reference_unreadable")
        return parts

    capture = internal.try_capture_follow_up

    @wraps(capture)
    def capture_follow_up(event, *args, **kwargs):
        state = active_chat_run(event)
        if (
            state is not None
            and (
                any(isinstance(part, Image) for part in event.get_messages())
                or state.has_live_reply_image()
            )
            and edits_enabled(
                event.get_extra("selected_provider"), event.unified_msg_origin
            )
        ):
            # A steered tool call would see the original event and its history cutoff.
            return None
        return capture(event, *args, **kwargs)

    @wraps(consume)
    async def consume_run(self, run):
        state = _CitationRun(self, run)
        active_runs[run.run_id] = state
        try:
            return await consume(state, run)
        finally:
            active_runs.pop(run.run_id, None)
            state.close_cards()

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
        bot_event = (
            event
            if (
                isinstance(event, AstrMessageEvent)
                and event.get_platform_name() != "webchat"
                and getattr(context, "send_to_user", True)
            )
            else None
        )
        async with aclosing(stream(self, *args, **kwargs)) as responses:
            while True:
                token = _producer.set(state)
                bot_token = bot_citations.event_context.set(bot_event)
                try:
                    response = await anext(responses)
                except StopAsyncIteration:
                    return
                finally:
                    bot_citations.event_context.reset(bot_token)
                    _producer.reset(token)
                yield response

    serialize_history = chat_service.serialize_history_entry

    @wraps(serialize_history)
    def serialize_entry(history):
        entry = serialize_history(history)
        content = entry["content"]
        if content.get("type") == "bot" and content.get("refs"):
            refs = content["refs"].get("used", [])
            indices = {ref.get("index") for ref in refs}
            for part in content["message"]:
                if part.get("type") == "plain":
                    part["text"] = _align_saved_links(part["text"], indices)
            content["message"] = _display_parts(content["message"], refs)
        return entry

    from astrbot.dashboard.services.plugin_page_service import PluginPageService

    roots = PluginPageService.resolve_plugin_pages_root

    @wraps(roots)
    async def pages_root(self, plugin):
        # Some hosts discover views/ before pages/ even without chat-message
        # support. Keep the existing Providers entry and its scoped assets.
        if plugin.name == "astrbot_plugin_openai_oauth":
            root = self.get_plugin_root_dir(plugin)
            pages = (root / "pages").resolve()
            pages.relative_to(root)
            return pages
        return await roots(self, plugin)

    hooks = (
        (PluginPageService, "resolve_plugin_pages_root", pages_root, roots),
        (chat_service, "serialize_history_entry", serialize_entry, serialize_history),
        (internal, "try_capture_follow_up", capture_follow_up, capture),
        (service, "build_chat_stream", build_chat_stream, build),
        (service, "build_user_message_parts", build_user_message_parts, parse),
        (service, "_consume_chat_run", consume_run, consume),
        (runner, stream_name, stream_response, stream),
    )

    # Older supported AstrBot versions do not render chat-message views.
    if hasattr(service, "get_chat_view"):
        from . import chatui_images

        remove_views = chatui_images.install(active_runs)
    else:
        remove_views = None

    def remove() -> None:
        if remove_views:
            remove_views()
        for state in active_runs.values():
            state.close_cards()
        active_runs.clear()
        for owner, name, installed, original in hooks:
            if getattr(owner, name) is installed:
                setattr(owner, name, original)

    for owner, name, installed, _ in hooks:
        setattr(owner, name, installed)
    _active_runs = active_runs
    return remove
