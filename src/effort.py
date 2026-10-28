"""Session reasoning-effort settings and command handling."""

from __future__ import annotations

from typing import Any

from astrbot import logger
from astrbot.api import sp
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.star import Context

from . import messages, oauth, runtime

_EFFORT_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
_SESSION_EFFORT_KEY = "openai_oauth_reasoning_effort"


def normalize_effort(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "ultra":
        # Codex CLI's name for the top level, which the backend calls "max".
        normalized = "max"
    return normalized if normalized in _EFFORT_LEVELS else None


def _provider_model(provider: Any) -> str | None:
    getter = getattr(provider, "get_model", None)
    model = getter() if callable(getter) else None
    if not model:
        model = getattr(provider, "provider_config", {}).get("model")
    return model if isinstance(model, str) and model else None


def _model_efforts(provider: Any) -> tuple[str, ...] | None:
    return oauth.supported_efforts(_provider_model(provider))


async def get_session_effort(session_id: Any) -> str | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        return normalize_effort(
            await sp.get_async(
                scope="umo",
                scope_id=session_id,
                key=_SESSION_EFFORT_KEY,
                default=None,
            )
        )
    except Exception as exc:  # noqa: BLE001 - use the model default on storage failure
        logger.warning(
            "OpenAI Codex session effort lookup failed: %s",
            type(exc).__name__,
        )
        return None


def _provider_default_effort(provider: Any) -> str | None:
    extra_body = provider.provider_config.get("custom_extra_body")
    if not isinstance(extra_body, dict):
        return None
    configured = normalize_effort(extra_body.get("reasoning_effort"))
    if configured:
        return configured
    reasoning = extra_body.get("reasoning")
    return normalize_effort(
        reasoning.get("effort") if isinstance(reasoning, dict) else None
    )


async def handle_effort(
    context: Context,
    event: AstrMessageEvent,
    value: str | None = None,
) -> None:
    """View or override Codex reasoning effort for the current session."""
    event.should_call_llm(False)
    session_id = str(event.unified_msg_origin or "")
    if not session_id:
        await event.send(MessageChain().message(messages.text("effort.no_session")))
        return
    try:
        selected_provider_id = event.get_extra("selected_provider")
        if isinstance(selected_provider_id, str) and selected_provider_id:
            provider = context.get_provider_by_id(selected_provider_id)
        else:
            provider = await context.get_using_provider_async(umo=session_id)
    except Exception as exc:  # noqa: BLE001 - fail closed on provider resolution
        logger.warning(
            "OpenAI Codex effort provider lookup failed: %s",
            type(exc).__name__,
        )
        await event.send(
            MessageChain().message(messages.text("effort.provider_unknown"))
        )
        return
    if provider is None or provider.meta().type != runtime.PROVIDER_TYPE:
        await event.send(MessageChain().message(messages.text("effort.not_subscribe")))
        return

    requested = str(value or "").strip().lower()
    if not requested:
        override = await get_session_effort(session_id)
        default = _provider_default_effort(provider)
        if override:
            message = messages.text("effort.override", effort=override)
        elif default:
            message = messages.text("effort.model_default", effort=default)
        else:
            message = messages.text("effort.unset")
        await event.send(
            MessageChain().message(
                messages.text(
                    "effort.help",
                    message=message,
                    levels=", ".join(_model_efforts(provider) or _EFFORT_LEVELS),
                )
            )
        )
        return

    if requested == "default":
        try:
            await sp.remove_async("umo", session_id, _SESSION_EFFORT_KEY)
        except Exception as exc:  # noqa: BLE001 - do not hide storage failure
            logger.error(
                "OpenAI Codex session effort removal failed: %s",
                type(exc).__name__,
            )
            await event.send(
                MessageChain().message(messages.text("effort.reset_failed"))
            )
            return
        await event.send(MessageChain().message(messages.text("effort.reset")))
        return

    effort = normalize_effort(requested)
    supported = _model_efforts(provider)
    if effort is None or (supported is not None and effort not in supported):
        await event.send(
            MessageChain().message(
                messages.text(
                    "effort.unsupported",
                    value=requested,
                    levels=", ".join(supported or _EFFORT_LEVELS),
                )
            )
        )
        return
    try:
        await sp.put_async("umo", session_id, _SESSION_EFFORT_KEY, effort)
    except Exception as exc:  # noqa: BLE001 - do not claim an unsaved override
        logger.error(
            "OpenAI Codex session effort update failed: %s",
            type(exc).__name__,
        )
        await event.send(MessageChain().message(messages.text("effort.save_failed")))
        return
    await event.send(
        MessageChain().message(messages.text("effort.saved", effort=effort))
    )
