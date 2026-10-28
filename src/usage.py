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

from . import oauth, runtime
from .credential_store import (
    CredentialCooldownError,
    CredentialError,
    CredentialSchemaError,
    CredentialSnapshot,
    CredentialsNotConfiguredError,
    ReauthenticationRequiredError,
)
from .oauth import CredentialExpiredError

_WINDOW_LABELS = {18000: "5小时窗口", 604800: "7天窗口", 2592000: "30天窗口"}


def _window_label(seconds: Any) -> str:
    if seconds in _WINDOW_LABELS:
        return _WINDOW_LABELS[seconds]
    if isinstance(seconds, (int, float)) and seconds:
        if seconds % 86400 == 0:
            return f"{seconds // 86400}天窗口"
        if seconds % 3600 == 0:
            return f"{seconds // 3600}小时窗口"
    return "额度窗口"


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
    date_part = f"{dt.month}月{dt.day}日"
    if dt.year != now.year:
        date_part = f"{dt.year}年{date_part}"
    return f"，重置 {date_part} {dt:%H:%M}"


def format_usage(usage: dict) -> str:
    """Format the usage response as a chat message."""
    lines = ["OpenAI 订阅额度："]
    windows = usage.get("windows") or []
    if not windows:
        lines.append("当前账号暂无可用额度窗口。")
    for window in windows:
        used = window.get("used_percent")
        remaining = (
            f"剩余 {max(0.0, min(100.0, 100.0 - used)):.0f}%"
            if isinstance(used, (int, float))
            else "额度暂不可用"
        )
        lines.append(
            f"· {_window_label(window.get('label_seconds'))}："
            f"{remaining}"
            f"{_format_reset_at(window.get('reset_at'), window.get('reset_after_seconds'))}"
        )
    if usage.get("limit_reached"):
        lines.append("状态：已达额度上限，等待窗口重置。")
    elif not usage.get("allowed"):
        lines.append("状态：当前不可用。")
    return "\n".join(lines)


def _cooldown_until_from_usage(usage: dict[str, Any]) -> int | None:
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
    return f"OpenAI 订阅额度当前处于冷却状态{_format_reset_at(cooldown_until, None)}。"


async def _fetch_source_usage(
    source_id: str = runtime._PROVIDER_TYPE,
) -> dict[str, Any]:
    coordinator = runtime._get_credential_coordinator()
    # Cache hits belong to the current login; fresh lookups may refresh its token.
    expected_access_token = coordinator._read_snapshot(source_id).access_token

    async def fetch_usage(snapshot: CredentialSnapshot) -> dict:
        nonlocal expected_access_token
        expected_access_token = snapshot.access_token
        settings = coordinator.source_settings(snapshot.source_id)
        return await retry_provider_request(
            "OpenAI Codex",
            lambda: oauth.fetch_rate_limits(
                snapshot.access_token,
                snapshot.account_id,
                settings["proxy"],
                oauth.resolve_user_agent(settings["user_agent"]),
            ),
            retry_rate_limits=False,
            max_attempts=3,
        )

    try:
        usage = await coordinator.get_usage(source_id, fetch_usage)
    except CredentialExpiredError:
        # The backend can reject a token before its own expiry. One forced
        # refresh mends that; a second rejection means signing in again.
        await coordinator.get_snapshot(
            source_id, force_refresh=True, check_cooldown=False
        )
        usage = await coordinator.get_usage(source_id, fetch_usage)
    if usage.get("limit_reached") or not usage.get("allowed", True):
        cooldown_until = _cooldown_until_from_usage(usage)
        if cooldown_until is not None:
            await coordinator.mark_cooling(
                source_id,
                cooldown_until,
                expected_access_token=expected_access_token,
            )
    return usage


async def build_usage_message(source_id: str = runtime._PROVIDER_TYPE) -> str:
    """Fetch the selected source's quota through the credential coordinator."""
    try:
        usage = await _fetch_source_usage(source_id)
    except CredentialCooldownError as exc:
        return _format_cooldown(exc.cooldown_until)
    except (CredentialsNotConfiguredError, ReauthenticationRequiredError):
        return "凭据已失效，请在插件详情页重新登录。"
    except CredentialSchemaError:
        return "凭据配置格式不受支持，请升级插件后重新登录。"
    except CredentialExpiredError:
        return "凭据已失效，请在插件详情页重新登录。"
    except CredentialError:
        return "无法读取 OpenAI 凭据，请在插件详情页重新登录。"
    except Exception as exc:  # noqa: BLE001 - do not expose provider responses
        logger.error("OpenAI Codex usage request failed: %s", type(exc).__name__)
        return "额度查询失败，请稍后重试。"

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
    if provider is None or provider.meta().type != runtime._PROVIDER_TYPE:
        await event.send(MessageChain().message("请先选择 OpenAI Subscribe 模型。"))
        return
    await event.send(
        MessageChain().message(await build_usage_message(provider._source_id))
    )
