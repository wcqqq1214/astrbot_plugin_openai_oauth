"""Subscription usage queries, cooldown calculation, and chat formatting."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.star import Context
from astrbot.core.provider.sources.request_retry import (
    retry_provider_request,
)

from . import messages, oauth, runtime
from .credential_store import (
    CredentialCooldownError,
    CredentialError,
    CredentialSchemaError,
    CredentialSnapshot,
    CredentialsNotConfiguredError,
    ReauthenticationRequiredError,
)
from .oauth import CredentialExpiredError

_WINDOW_KEYS = {18000: "window.5h", 604800: "window.7d", 2592000: "window.30d"}


def _window_label(seconds: Any) -> str:
    if seconds in _WINDOW_KEYS:
        return messages.text(_WINDOW_KEYS[seconds])
    if isinstance(seconds, (int, float)) and seconds:
        if seconds % 86400 == 0:
            return messages.text("window.days", count=int(seconds // 86400))
        if seconds % 3600 == 0:
            return messages.text("window.hours", count=int(seconds // 3600))
    return messages.text("window.generic")


def _format_reset_at(reset_at: Any, reset_after: Any) -> str:
    """Render a reset timestamp in the local time zone.

    Prefer the backend's Unix timestamp; fall back to the relative delay
    supplied by the legacy usage schema.
    """
    ts = reset_at
    if not isinstance(ts, (int, float)):
        if isinstance(reset_after, (int, float)) and reset_after >= 0:
            ts = time.time() + reset_after
        else:
            return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=UTC).astimezone()
    except (OSError, OverflowError, ValueError):
        return ""
    now = datetime.now(UTC).astimezone()
    return messages.text("usage.reset", when=messages.format_datetime(dt, now))


def format_usage(usage: dict) -> str:
    """Format the usage response as a chat message."""
    lines = [messages.text("usage.title")]
    windows = usage.get("windows") or []
    if not windows:
        lines.append(messages.text("usage.no_windows"))
    for window in windows:
        used = window.get("used_percent")
        remaining = (
            messages.text(
                "usage.remaining",
                percent=f"{max(0.0, min(100.0, 100.0 - used)):.0f}",
            )
            if isinstance(used, (int, float))
            else messages.text("usage.unavailable")
        )
        lines.append(
            messages.text(
                "usage.line",
                label=_window_label(window.get("label_seconds")),
                remaining=remaining,
                reset=_format_reset_at(
                    window.get("reset_at"), window.get("reset_after_seconds")
                ),
            )
        )
    if usage.get("limit_reached"):
        lines.append(messages.text("usage.limit_reached"))
    elif not usage.get("allowed"):
        lines.append(messages.text("usage.not_allowed"))
    return "\n".join(lines)


def cooldown_until_from_usage(usage: dict[str, Any]) -> int | None:
    """Wait for exhausted windows only; unrelated windows do not block requests."""
    reset_times: list[int] = []
    now = time.time()
    for window in usage.get("windows") or []:
        used = window.get("used_percent")
        if (
            isinstance(used, bool)
            or not isinstance(used, (int, float))
            or not math.isfinite(used)
            or used < 100
        ):
            continue
        reset_at = window.get("reset_at")
        if (
            not isinstance(reset_at, bool)
            and isinstance(reset_at, (int, float))
            and math.isfinite(reset_at)
            and reset_at > now
        ):
            reset_times.append(int(reset_at))
            continue
        reset_after = window.get("reset_after_seconds")
        if (
            not isinstance(reset_after, bool)
            and isinstance(reset_after, (int, float))
            and math.isfinite(reset_after)
            and reset_after > 0
        ):
            reset_times.append(int(now + reset_after))
    return max(reset_times, default=None)


def _format_cooldown(cooldown_until: int | None) -> str:
    return messages.text("usage.cooldown", reset=_format_reset_at(cooldown_until, None))


async def fetch_usage(
    snapshot: CredentialSnapshot, *, attempts: int = 3
) -> dict[str, Any]:
    """Query one account's allowance with its own proxy and client identity."""
    settings = runtime.get_coordinator().source_settings(snapshot.source_id)
    return await retry_provider_request(
        "OpenAI Codex",
        lambda: oauth.fetch_rate_limits(
            snapshot.access_token,
            snapshot.account_id,
            settings["proxy"],
            oauth.resolve_user_agent(settings["user_agent"]),
        ),
        retry_rate_limits=False,
        max_attempts=attempts,
    )


def failure_state(error: BaseException) -> str | None:
    """Map a quota lookup failure to a safe state shared by chat and WebUI."""
    if isinstance(error, CredentialCooldownError):
        return "cooling"
    if isinstance(
        error,
        (
            CredentialsNotConfiguredError,
            ReauthenticationRequiredError,
            CredentialExpiredError,
        ),
    ):
        return "reauth_required"
    if isinstance(error, CredentialSchemaError):
        return "unsupported"
    if isinstance(error, CredentialError):
        return "invalid"
    return None


async def fetch_source_usage(
    source_id: str = runtime.PROVIDER_TYPE,
) -> dict[str, Any]:
    coordinator = runtime.get_coordinator()
    # Cache hits belong to the current login; fresh lookups may refresh its token.
    expected_access_token = coordinator.read_snapshot(source_id).access_token

    async def fetch_for_cache(snapshot: CredentialSnapshot) -> dict:
        nonlocal expected_access_token
        expected_access_token = snapshot.access_token
        return await fetch_usage(snapshot)

    try:
        usage = await coordinator.get_usage(source_id, fetch_for_cache)
    except CredentialExpiredError:
        # The backend can reject a token before its own expiry. One forced
        # refresh mends that; a second rejection means signing in again.
        await coordinator.get_snapshot(
            source_id, force_refresh=True, check_cooldown=False
        )
        usage = await coordinator.get_usage(source_id, fetch_for_cache)
    if usage.get("limit_reached") or not usage.get("allowed", True):
        cooldown_until = cooldown_until_from_usage(usage)
        if cooldown_until is not None:
            await coordinator.mark_cooling(
                source_id,
                cooldown_until,
                expected_access_token=expected_access_token,
            )
    return usage


async def build_usage_message(source_id: str = runtime.PROVIDER_TYPE) -> str:
    """Fetch the selected source's quota through the credential coordinator."""
    try:
        usage = await fetch_source_usage(source_id)
    except Exception as exc:  # noqa: BLE001 - do not expose provider responses
        state = failure_state(exc)
        if isinstance(exc, CredentialCooldownError):
            return _format_cooldown(exc.cooldown_until)
        if state is not None:
            return messages.text(f"usage.{state}")
        logger.error("OpenAI Codex usage request failed: %s", type(exc).__name__)
        return messages.text("usage.failed")

    return format_usage(usage)


async def handle_usage(context: Context, event: AstrMessageEvent) -> None:
    """Show the selected provider's remaining subscription quota."""
    event.should_call_llm(False)
    selected = event.get_extra("selected_provider")
    provider = (
        context.get_provider_by_id(selected)
        if selected
        else await context.get_using_provider_async(umo=event.unified_msg_origin)
    )
    if provider is None or provider.meta().type != runtime.PROVIDER_TYPE:
        await event.send(MessageChain().message(messages.text("usage.select_model")))
        return
    await event.send(
        MessageChain().message(await build_usage_message(provider._source_id))
    )
