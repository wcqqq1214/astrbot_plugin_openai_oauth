"""Render Codex URL annotations for the platform delivering an agent reply."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.event import (
    AstrMessageEvent,
    MessageChain,
    MessageEventResult,
    ResultContentType,
)
from astrbot.core.message import components as Comp

from . import messages

if TYPE_CHECKING:
    from .chatui_citations import CitationText

event_context: ContextVar[AstrMessageEvent | None] = ContextVar(
    "codex_bot_citation_event", default=None
)
_TURN_KEY = "_codex_bot_citations"
_LINK_PLATFORMS = {
    "lark",
    "telegram",
    "discord",
    "slack",
    "mattermost",
    "misskey",
    "kook",
    "dingtalk",
    "wecom_ai_bot",
}
_CARD_PLATFORMS = {"line", "qq_official", "qq_official_webhook", "wecom", "satori"}


def _link(platform: str, label: str, url: str) -> str:
    if platform == "slack":
        dest = (
            url.replace("&", "&amp;")
            .replace("<", "%3C")
            .replace(">", "%3E")
            .replace("|", "%7C")
        )
        return f"<{dest}|{label}>"
    dest = (
        url.replace("(", "%28")
        .replace(")", "%29")
        .replace(" ", "%20")
        .replace(">", "%3E")
        .replace("<", "%3C")
    )
    return f"[{label}]({dest})"


def _queue_line_sources(event, body: str, card: MessageChain, overview: str) -> None:
    """Use the reply token for the answer and its buttons in the same LINE request."""
    send = event.send

    async def send_with_sources(message: MessageChain):
        if message.type == "reasoning":
            return await send(message)
        for index, component in enumerate(message.chain):
            if isinstance(component, Comp.Plain):
                fragment = component.text.strip()
                if fragment and (body in fragment or fragment in body):
                    break
        else:
            return await send(message)

        event.send = send
        payload = await event.build_line_messages(message)
        [template] = await event.build_line_messages(card)
        if len(payload) < 5:
            native = [*payload, template]
        else:
            # LINE permits five messages per reply. Attach the same URL actions
            # to the last message when the original chain already fills the batch.
            actions = template["template"]["actions"]
            quick_reply = {
                "items": [{"type": "action", "action": action} for action in actions]
            }
            native = [*payload[:-1], {**payload[-1], "quickReply": quick_reply}]

        raw = event.message_obj.raw_message
        token = raw.get("replyToken") if isinstance(raw, dict) else None
        if token:
            sent = await event.line_api.reply_message(token, native)
        else:
            target = event.get_group_id() or event.get_sender_id()
            sent = await event.line_api.push_message(target, native)
        if sent:
            return await AstrMessageEvent.send(event, message)

        # The adapter's send() hides rejected requests. Retry with the URLs
        # beside the answer, using its normal reply/push delivery.
        if len(payload) < 5:
            return await send(message.derive([*message.chain, Comp.Plain(overview)]))
        await send(message.derive([component, Comp.Plain(overview)]))
        await send(message.derive(message.chain[:index] + message.chain[index + 1 :]))

    event.send = send_with_sources


@dataclass
class BotCitations:
    event: AstrMessageEvent
    sources: dict[str, tuple[int, str]] = field(default_factory=dict)
    pending_card: tuple[str, MessageChain, str] | None = None
    delivery_result: MessageEventResult | None = None

    def render(
        self,
        body: str,
        parts: Mapping[tuple[int, int], CitationText],
        citations: dict[str, str],
        language: str | None,
        *,
        final_answer: bool,
    ) -> str:
        if not citations and not self.sources:
            return body

        platform = self.event.get_platform_name()
        inline = platform in _LINK_PLATFORMS
        # Each end_index counts characters from the start of its output_text.
        ordered_parts = [parts[key] for key in sorted(parts)]
        linked = set()
        if "".join(part.text for part in ordered_parts) == body:
            rendered = []
            for part in ordered_parts:
                cursor = 0
                for end, url in part.positioned_marks():
                    index, _ = self.sources.setdefault(
                        url, (len(self.sources) + 1, citations[url])
                    )
                    number = f"〔{index}〕"
                    rendered.append(part.text[cursor:end])
                    rendered.append(_link(platform, number, url) if inline else number)
                    linked.add(url)
                    cursor = end
                rendered.append(part.text[cursor:])
            body = "".join(rendered)
        for url, title in citations.items():
            self.sources.setdefault(url, (len(self.sources) + 1, title))
        if not final_answer:
            return body

        heading = messages.text("search.sources", lang=language)
        lines = []
        for url, (number, title) in self.sources.items():
            if inline and url in linked:
                continue
            label = title if title == url else f"{title} {url}"
            lines.append(f"〔{number}〕 {label}")
        if not lines:
            return body
        overview = heading + "\n" + "\n".join(lines)
        if (
            body.strip()
            and hasattr(Comp, "ActionRow")
            and platform in _CARD_PLATFORMS
            and (platform != "line" or len(lines) <= self.event.BUTTONS_PER_TEMPLATE)
        ):
            buttons = [
                Comp.Button(
                    id=f"codex-source-{number}",
                    label=f"〔{number}〕 {title}",
                    action=Comp.Button.UrlAction(url=url),
                )
                for url, (number, title) in self.sources.items()
            ]
            card = MessageChain(
                chain=[Comp.ActionRow(buttons=buttons, fallback_text=heading)]
            )
            if platform == "line":
                _queue_line_sources(self.event, body, card, overview)
            else:
                self.pending_card = (body, card, overview)
            return body
        if not body or body.endswith("\n\n"):
            return body + overview
        return body + ("\n" if body.endswith("\n") else "\n\n") + overview


def for_request(tools) -> BotCitations | None:
    event = event_context.get()
    if event is None:
        return None
    if not any(
        isinstance(tool, dict)
        and tool.get("type") in {"web_search", "web_search_preview"}
        for tool in tools or []
    ):
        return None
    state = event.get_extra(_TURN_KEY)
    if state is None:
        state = BotCitations(event)
        event.set_extra(_TURN_KEY, state)
    return state


def current_turn() -> BotCitations | None:
    event = event_context.get()
    return event.get_extra(_TURN_KEY) if event is not None else None


async def deliver_card(event: AstrMessageEvent, *, after_send: bool) -> None:
    state: BotCitations | None = event.get_extra(_TURN_KEY)
    if not state or not state.pending_card:
        return
    body, card, fallback = state.pending_card
    result = event.get_result()
    if result is None:
        return
    if after_send:
        if result is not state.delivery_result:
            return
    else:
        if body not in result.get_plain_text():
            return
        if result.is_llm_result() and result.type != "reasoning":
            # Remember the reply before decorators segment or replace its text.
            state.delivery_result = result
            return
        if result.result_content_type != ResultContentType.STREAMING_FINISH:
            return
        # The response stage has already delivered the stream at this point.
    state.pending_card = None
    state.delivery_result = None
    try:
        await event.send(card)
    except Exception as exc:  # noqa: BLE001 - adapters report different delivery errors
        logger.warning(
            "Citation card delivery failed (%s); sending source URLs.",
            type(exc).__name__,
        )
        await event.send(MessageChain().message(fallback))
