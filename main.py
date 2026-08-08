"""astrbot_plugin_openai_oauth — ChatGPT 订阅 (Codex OAuth) provider.

注册一个 `OpenAI Subscribe` provider：登录 ChatGPT 账号后，AI 调用走账号订阅
额度。个人自用场景使用。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import secrets
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import astrbot.core.message.components as Comp
from astrbot import logger
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.web import json_response, request
from astrbot.core.exceptions import EmptyModelOutputError
from astrbot.core.provider.entities import LLMResponse, TokenUsage
from astrbot.core.provider.register import (
    provider_cls_map,
    register_provider_adapter,
)
from astrbot.core.provider.sources.openai_responses_source import (
    ProviderOpenAIResponses,
)
from astrbot.core.provider.sources.request_retry import retry_provider_request
from astrbot.core.utils.network_utils import create_proxy_client
from astrbot.core.workspace import API_KEY_USERNAME_PREFIX
from starlette.responses import HTMLResponse

from .oauth import (
    CODEX_BASE,
    CODEX_DEVICE_LOGIN_TIMEOUT,
    CODEX_DEVICE_VERIFY_URL,
    CODEX_FALLBACK_MODELS,
    CODEX_MODELS_URL,
    DEFAULT_ORIGINATOR,
    DEFAULT_USER_AGENT,
    CredentialExpiredError,
    DeviceAuthError,
    DeviceAuthTimeout,
    build_credentials,
    dump_credentials,
    exchange_authorization_code,
    extract_model_ids,
    fetch_rate_limits,
    load_credentials,
    poll_device_authorization,
    refresh_access_token,
    request_device_user_code,
)

_REFRESH_SKEW_SECONDS = 120

# WebUI 模型配置里展示的 provider 类型名（也是配置里的 type/id）。
_PROVIDER_TYPE = "OpenAI Subscribe"

# 由 OpenAI_OAuth_Plugin 注入，供 provider 把刷新的凭据写回 AstrBot 配置。
_config_mgr: Any = None
_allow_insecure_local_http = False


@register(
    "astrbot_plugin_openai_oauth",
    "wcqqq1214",
    "ChatGPT 订阅 (Codex OAuth) provider 插件",
    "0.1.0",
)
class OpenAI_OAuth_Plugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        global _allow_insecure_local_http, _config_mgr
        super().__init__(context)
        _config_mgr = context.astrbot_config_mgr
        self.config = config if config is not None else AstrBotConfig()
        _allow_insecure_local_http = (
            config is not None
            and config.get("allow_insecure_local_http", False) is True
        )
        # 设备登录的后端接口与页面：/api/v1/plugins/extensions/<route>
        self.context.register_web_api(
            "/astrbot_plugin_openai_oauth/device/start",
            _handle_device_start,
            ["POST"],
            "开始 Codex 设备登录",
        )
        self.context.register_web_api(
            "/astrbot_plugin_openai_oauth/device/poll",
            _handle_device_poll,
            ["POST"],
            "查询 Codex 设备登录状态",
        )
        self.context.register_web_api(
            "/astrbot_plugin_openai_oauth/login",
            _handle_login_page,
            ["GET"],
            "Codex 设备登录页面",
        )

    @filter.command("usage")
    async def usage(self, event: AstrMessageEvent) -> None:
        """查询 OpenAI 订阅剩余额度。"""
        if not _is_logged_in():
            # 未登录时命令不可用：静默拦截，不触发默认 LLM。
            event.should_call_llm(False)
            return
        await event.send(MessageChain().message(await build_usage_message()))

    async def terminate(self) -> None:
        """Cancel all outstanding device-login work during plugin unload."""
        _discard_all_login_sessions()


def _register_provider_adapter_if_absent(cls: type) -> type:
    """Register the provider once and refresh its class on plugin reload.

    AstrBot keeps ``provider_cls_map`` when a plugin module is reloaded. Avoiding
    duplicate registration is necessary, but the metadata must still point to the
    newly imported class or provider instances will continue using stale code.
    """
    if _PROVIDER_TYPE not in provider_cls_map:
        return register_provider_adapter(
            _PROVIDER_TYPE,
            "OpenAI 订阅登录 (Codex OAuth) Provider",
            provider_display_name="OpenAI Subscribe",
            default_config_tmpl={
                # provider 字段被前端 getProviderIcon 读取，映射到 OpenAI 官方图标。
                # provider_type 被前端按 tab 过滤（chat_completion），缺失会导致
                # 模型配置下拉里看不到这个 provider。
                "provider": "openai",
                "provider_type": "chat_completion",
                # key 存放凭据 JSON：{access_token, refresh_token, expires, account_id}
                "key": "",
                "model": "gpt-5.4-mini",
                "proxy": "",
                "originator": DEFAULT_ORIGINATOR,
                "user_agent": DEFAULT_USER_AGENT,
            },
        )(cls)
    provider_cls_map[_PROVIDER_TYPE].cls_type = cls
    return cls


@_register_provider_adapter_if_absent
class ProviderOpenAICodex(ProviderOpenAIResponses):
    """ChatGPT subscription provider backed by the Codex OAuth flow.

    The key field holds a credential JSON blob:
    ``{"access_token", "refresh_token", "expires", "account_id"}``
    """

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        raw_key = provider_config.get("key")
        self.creds = load_credentials(raw_key)
        if not self.creds and raw_key:
            # 允许直接粘贴裸 access_token（缺少 account_id 时模型列表等接口不可用）
            self.creds = {"access_token": str(raw_key)}
        self._originator = str(provider_config.get("originator", DEFAULT_ORIGINATOR))
        self._user_agent = str(provider_config.get("user_agent", DEFAULT_USER_AGENT))
        provider_config["api_base"] = CODEX_BASE

        if not isinstance(provider_config.get("custom_headers"), dict):
            provider_config["custom_headers"] = {}
        account_id = self.creds.get("account_id", "")
        if account_id:
            provider_config["custom_headers"]["chatgpt-account-id"] = account_id
        provider_config["custom_headers"].setdefault("originator", self._originator)
        provider_config["custom_headers"].setdefault(
            "OpenAI-Beta", "responses=experimental"
        )

        super().__init__(provider_config, provider_settings)
        # 基类用原始 key 值构建了 client，这里用解析出的 access_token 修正。
        self._sync_client_key()
        self._refresh_lock = asyncio.Lock()
        self.set_model(provider_config.get("model", "gpt-5.4-mini"))

    def _sync_client_key(self) -> None:
        token = self.creds.get("access_token", "")
        self.api_keys = [token]
        self.chosen_api_key = token
        self.client.api_key = token

    def get_keys(self) -> list[str]:
        return [self.creds.get("access_token", "")]

    def get_current_key(self) -> str:
        return self.creds.get("access_token", "")

    def set_key(self, key: str) -> None:
        creds = load_credentials(key)
        if "access_token" not in creds and key:
            creds = {"access_token": key}
        self.creds = creds
        # AsyncOpenAI 构造时持有同一个 custom_headers dict，这里就地更新
        # chatgpt-account-id，client.default_headers 下次访问时即生效。
        headers = self.provider_config.get("custom_headers")
        if isinstance(headers, dict):
            account_id = creds.get("account_id", "")
            if account_id:
                headers["chatgpt-account-id"] = account_id
            else:
                headers.pop("chatgpt-account-id", None)
        self._sync_client_key()

    def _convert_chat_messages_to_response_input(
        self, messages: list[dict]
    ) -> list[dict]:
        # The ChatGPT Codex backend rejects role:"system" items in input and
        # only accepts the Responses API roles (user/assistant/developer).
        response_input = super()._convert_chat_messages_to_response_input(messages)
        for item in response_input:
            if item.get("type") == "message" and item.get("role") == "system":
                item["role"] = "developer"
        return response_input

    async def _query_stream(
        self,
        payloads: dict,
        tools,
        *,
        request_max_retries: int | None = None,
    ) -> AsyncGenerator[LLMResponse, None]:
        """Stream from the Codex backend, which completes with an empty response
        object: the content only arrives as deltas. Assemble the final response
        from them instead of parsing the terminal event."""
        if tools:
            response_tools = []
            for tool in tools.openai_schema():
                function = tool.get("function", {})
                response_tools.append({"type": "function", **function})
            if response_tools:
                payloads["tools"] = response_tools
                payloads["tool_choice"] = payloads.get("tool_choice", "auto")

        extra_body: dict[str, Any] = {}
        custom_extra_body = self.provider_config.get("custom_extra_body", {})
        if isinstance(custom_extra_body, dict):
            extra_body.update(custom_extra_body)

        for key in list(payloads):
            if key not in self.default_params:
                extra_body[key] = payloads.pop(key)

        max_tokens = extra_body.pop("max_tokens", None)
        if max_tokens is not None and "max_output_tokens" not in extra_body:
            extra_body["max_output_tokens"] = max_tokens
        reasoning_effort = extra_body.pop("reasoning_effort", None)
        if reasoning_effort is not None and "reasoning" not in extra_body:
            extra_body["reasoning"] = {"effort": reasoning_effort}
        extra_body.pop("previous_response_id", None)
        extra_body.pop("conversation", None)
        extra_body.pop("store", None)
        payloads.pop("previous_response_id", None)
        payloads.pop("conversation", None)
        payloads["store"] = False

        stream = await retry_provider_request(
            "OpenAI Responses",
            lambda: self.client.responses.create(
                **payloads,
                stream=True,
                extra_body=extra_body,
            ),
            max_attempts=request_max_retries,
        )

        response_id: str | None = None
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        function_calls: list[dict] = []

        async for event in stream:
            event_type = self._field(event, "type", "")
            event_response = self._field(event, "response")
            if event_response is not None:
                response_id = self._field(event_response, "id", response_id)

            if event_type == "error":
                code = self._field(event, "code", "stream_error")
                message = self._field(event, "message", "Responses stream failed")
                raise RuntimeError(
                    f"Responses API stream failed: {code}: {message}. "
                    f"response_id={response_id}"
                )

            if event_type in {"response.output_text.delta", "response.refusal.delta"}:
                delta = self._field(event, "delta", "")
                if delta:
                    text_parts.append(str(delta))
                    yield LLMResponse(
                        "assistant",
                        result_chain=MessageChain(chain=[Comp.Plain(str(delta))]),
                        is_chunk=True,
                        id=response_id,
                    )
                continue

            if event_type in {
                "response.reasoning_text.delta",
                "response.reasoning_summary_text.delta",
            }:
                delta = self._field(event, "delta", "")
                if delta:
                    reasoning_parts.append(str(delta))
                    yield LLMResponse(
                        "assistant",
                        reasoning_content=str(delta),
                        is_chunk=True,
                        id=response_id,
                    )
                continue

            if event_type == "response.output_item.added":
                item = self._field(event, "item")
                if self._field(item, "type") == "function_call":
                    arguments = self._field(item, "arguments", "")
                    if isinstance(arguments, dict):
                        arguments = json.dumps(arguments, ensure_ascii=False)
                    function_calls.append(
                        {
                            "call_id": str(self._field(item, "call_id", "") or ""),
                            "name": str(self._field(item, "name", "") or ""),
                            "arguments": str(arguments or ""),
                        }
                    )
                continue

            if event_type == "response.function_call_arguments.delta":
                if function_calls:
                    function_calls[-1]["arguments"] += str(
                        self._field(event, "delta", "") or ""
                    )
                continue

            if event_type in {
                "response.completed",
                "response.incomplete",
                "response.failed",
            }:
                if event_response is not None:
                    status = self._field(event_response, "status")
                    if status == "failed":
                        error = self._field(event_response, "error")
                        code = self._field(error, "code", "unknown_error")
                        message = self._field(
                            error, "message", "Responses API request failed"
                        )
                        raise RuntimeError(
                            f"Responses API request failed: {code}: {message}. "
                            f"response_id={response_id}"
                        )
                    if (
                        self._field(
                            self._field(event_response, "incomplete_details"),
                            "reason",
                        )
                        == "content_filter"
                    ):
                        raise RuntimeError(
                            "Responses API output was rejected by the provider "
                            f"content filter. response_id={response_id}"
                        )
                    if self._field(event_response, "output"):
                        yield await self._parse_response(event_response, tools)
                        return
                final = self._assemble_streamed_response(
                    response_id,
                    text_parts,
                    reasoning_parts,
                    function_calls,
                    usage=self._extract_response_usage(event_response),
                )
                if final is not None:
                    yield final
                    return
                raise EmptyModelOutputError(
                    f"Responses stream returned no usable output. "
                    f"response_id={response_id}"
                )

        raise EmptyModelOutputError(
            f"Responses stream ended without a terminal event. response_id={response_id}"
        )

    def _assemble_streamed_response(
        self,
        response_id: str | None,
        text_parts: list[str],
        reasoning_parts: list[str],
        function_calls: list[dict],
        usage: TokenUsage | None = None,
    ) -> LLMResponse | None:
        """Build a final LLMResponse from streamed deltas like ``_parse_response``."""
        llm_response = LLMResponse("assistant", id=response_id)
        llm_response.usage = usage if usage is not None else TokenUsage()
        completion_text = "".join(text_parts)
        if completion_text:
            llm_response.result_chain = MessageChain().message(completion_text)
        if reasoning_parts:
            llm_response.reasoning_content = "\n".join(reasoning_parts)
        for call in function_calls:
            arguments = call["arguments"]
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed = {}
            elif arguments is None:
                parsed = {}
            else:
                parsed = arguments
            llm_response.tools_call_args.append(parsed)
            llm_response.tools_call_name.append(call["name"])
            llm_response.tools_call_ids.append(call["call_id"])
        if llm_response.tools_call_args:
            llm_response.role = "tool"
        has_text = bool((llm_response.completion_text or "").strip())
        has_reasoning = bool((llm_response.reasoning_content or "").strip())
        if not has_text and not has_reasoning and not llm_response.tools_call_args:
            return None
        return llm_response

    def _extract_response_usage(self, response: Any) -> TokenUsage | None:
        """Extract usage from a terminal Responses event.

        Codex may send the completed response with an empty ``output`` list while
        the actual text arrived through delta events. In that case the base
        Responses parser is intentionally skipped, so preserve the usage here.
        """
        usage = self._field(response, "usage")
        if usage is None:
            return None

        input_details = self._field(usage, "input_tokens_details")
        cached_tokens = self._field(input_details, "cached_tokens", 0) or 0
        input_tokens = self._field(usage, "input_tokens", 0) or 0
        output_tokens = self._field(usage, "output_tokens", 0) or 0
        return TokenUsage(
            input_other=max(input_tokens - cached_tokens, 0),
            input_cached=cached_tokens,
            output=output_tokens,
        )

    async def get_models(self) -> list[str]:
        token = self.creds.get("access_token", "")
        if not token:
            return list(CODEX_FALLBACK_MODELS)
        headers = {
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": self.creds.get("account_id", ""),
            "originator": self._originator,
            "User-Agent": self._user_agent,
            "accept": "application/json",
        }
        try:
            client = create_proxy_client(
                "OpenAI Codex",
                self.provider_config.get("proxy", ""),
            )
            async with client:
                resp = await client.get(
                    f"{CODEX_MODELS_URL}?client_version=1.0.0",
                    headers=headers,
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
            models = extract_model_ids(data)
            if models:
                return models
            logger.warning("OpenAI Codex /models returned no ids; using fallback.")
        except Exception as e:  # noqa: BLE001 - network/catalog failure falls back to the offline list
            logger.error(f"Failed to fetch OpenAI Codex model list: {e}")
        return list(CODEX_FALLBACK_MODELS)

    async def _ensure_fresh_token(self) -> None:
        if not self.creds.get("refresh_token"):
            return
        if self.creds.get("expires", 0) > time.time() + _REFRESH_SKEW_SECONDS:
            return
        async with self._refresh_lock:
            # 等锁期间可能已被刷新，双重检查。
            if self.creds.get("expires", 0) > time.time() + _REFRESH_SKEW_SECONDS:
                return
            try:
                self.creds = await refresh_access_token(
                    self.creds,
                    self.provider_config.get("proxy", ""),
                )
                self.provider_config["key"] = dump_credentials(self.creds)
                self._sync_client_key()
                await self._persist_key()
                logger.info("OpenAI Codex token refreshed.")
            except Exception as e:  # noqa: BLE001 - a failed refresh must not break the request
                logger.error(f"OpenAI Codex token refresh failed: {e}")

    async def _persist_key(self) -> None:
        """把当前凭据写回配置里的 provider source key，重启后免重新登录。

        合并配置里 id 是模型 id，key 属于 `provider_sources` 里的 source 配置
        （按 provider_source_id / type 匹配），不能写进 `provider` 模型列表。
        """
        cfg_mgr = _config_mgr
        if cfg_mgr is None:
            return
        source_id = self.provider_config.get("provider_source_id") or _PROVIDER_TYPE
        try:
            conf = cfg_mgr.default_conf
            for source in conf.get("provider_sources", []):
                if (
                    source.get("id") == source_id
                    or source.get("type") == _PROVIDER_TYPE
                ):
                    source["key"] = dump_credentials(self.creds)
                    await conf.save_config_async()
                    return
            logger.warning(
                f"OpenAI Codex source {source_id!r} not found in config; "
                "refreshed token not persisted."
            )
        except Exception as e:  # noqa: BLE001 - a failed persist must not break the request
            logger.error(f"OpenAI Codex failed to persist refreshed token: {e}")

    async def text_chat(self, *args, **kwargs) -> LLMResponse:
        await self._ensure_fresh_token()
        # Codex 后端只接受 stream=true，非流式路径也改走流式并聚合出完整响应。
        final_response = None
        async for chunk in super().text_chat_stream(*args, **kwargs):
            if not chunk.is_chunk:
                final_response = chunk
        if final_response is None:
            raise RuntimeError("OpenAI Codex 未返回完整响应。")
        return final_response

    async def text_chat_stream(
        self, *args, **kwargs
    ) -> AsyncGenerator[LLMResponse, None]:
        await self._ensure_fresh_token()
        async for item in super().text_chat_stream(*args, **kwargs):
            yield item


# ---- 订阅额度查询（/usage 聊天命令） ----

# /wham/usage 的 limit_window_seconds → 可读窗口名（与 Codex CLI /status、
# cc-switch 的窗口映射一致）。
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
    """把重置时间渲染成“M月d日 HH:MM”的准确本地时间。

    优先使用后端下发的 reset_at（unix 秒）；旧版 schema 只有
    reset_after_seconds 时用 now + 秒数推算。
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
    """把 fetch_rate_limits 的结果渲染成聊天回复文本。"""
    lines = ["OpenAI 订阅额度："]
    windows = usage.get("windows") or []
    if not windows:
        lines.append("当前账号暂无可用额度窗口。")
    for window in windows:
        remaining = max(0.0, 100.0 - float(window.get("used_percent", 0.0)))
        lines.append(
            f"· {_window_label(window.get('label_seconds'))}："
            f"剩余 {remaining:.0f}%"
            f"{_format_reset_at(window.get('reset_at'), window.get('reset_after_seconds'))}"
        )
    if usage.get("limit_reached"):
        lines.append("状态：已达额度上限，等待窗口重置。")
    elif not usage.get("allowed"):
        lines.append("状态：当前不可用。")
    return "\n".join(lines)


def _get_source() -> dict | None:
    """从 AstrBot 配置里找本插件的 provider source。"""
    cfg_mgr = _config_mgr
    if cfg_mgr is None:
        return None
    return next(
        (
            s
            for s in cfg_mgr.default_conf.get("provider_sources", [])
            if s.get("type") == _PROVIDER_TYPE or s.get("id") == _PROVIDER_TYPE
        ),
        None,
    )


def _is_logged_in() -> bool:
    """是否已登录：provider source 里存有 access_token。"""
    source = _get_source()
    if not source:
        return False
    return bool(load_credentials(source.get("key")).get("access_token"))


async def build_usage_message() -> str:
    """读取 provider 配置里的凭据并查询额度，返回要发送的文本。"""
    source = _get_source()
    creds = load_credentials(source.get("key")) if source else {}
    if not creds.get("access_token"):
        # 正常路径已被 /usage 指令的登录门槛挡住，这里仅作兜底。
        return "尚未登录。"
    proxy = str((source or {}).get("proxy", "") or "")
    try:
        usage = await retry_provider_request(
            "OpenAI Codex",
            lambda: fetch_rate_limits(
                creds.get("access_token", ""),
                creds.get("account_id", ""),
                proxy,
            ),
            max_attempts=3,
        )
    except CredentialExpiredError:
        return "凭据已失效，请在插件详情页重新登录。"
    except Exception as exc:  # noqa: BLE001 - 查询失败信息透传给用户
        logger.error(f"OpenAI Codex 额度查询失败: {exc!r}")
        # 部分异常（如 TimeoutError）str 为空，回退到类型名避免透传空白信息。
        return f"额度查询失败：{str(exc) or type(exc).__name__}"
    return format_usage(usage)


# ---- Device-login Web API ----

_MAX_LOGIN_SESSIONS = 8
_MAX_LOGIN_SESSIONS_PER_USER = 2
_LOGIN_RESULT_TTL_SECONDS = 120
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_LOGIN_PAGE_HEADERS = {
    **_NO_STORE_HEADERS,
    "Content-Security-Policy": (
        "default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

# session_id -> {owner, status, device_auth_id, user_code, interval, error,
#                task, expiry_handle, expires_at}
_login_sessions: dict[str, dict] = {}


def _is_loopback_host(host: str | None) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    if normalized == "localhost":
        return True
    if "%" in normalized:
        normalized = normalized.split("%", 1)[0]
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _request_host() -> str:
    raw_host = str(request.headers.get("host", "") or "").strip()
    if raw_host.startswith("["):
        closing = raw_host.find("]")
        return raw_host[1:closing] if closing > 0 else ""
    if raw_host.count(":") == 1:
        return raw_host.rsplit(":", 1)[0]
    return raw_host


def _login_request_error() -> str | None:
    owner = str(request.username or "")
    if not owner:
        return "登录会话身份不可用"
    if owner.startswith(API_KEY_USERNAME_PREFIX):
        return "此操作仅允许已登录的 WebUI 用户，API Key 不可用"
    # PluginRequest does not expose a public scheme property. Read the ASGI
    # request URL selected by the server/proxy middleware; never infer it from a
    # caller-controlled forwarding header here.
    if str(request._request.url.scheme).lower() == "https":
        return None
    # A local reverse proxy can make both the peer and Host appear loopback for
    # a remote browser. HTTP therefore stays denied unless the operator opts in
    # explicitly for an isolated local-development deployment.
    if (
        _allow_insecure_local_http
        and _is_loopback_host(request.client_host)
        and _is_loopback_host(_request_host())
    ):
        return None
    return "设备登录必须通过 HTTPS 访问"


def _login_error_response(message: str, status_code: int):
    return json_response(
        {"status": "error", "message": message},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _discard_login_session(session_id: str, *, cancel_task: bool = True) -> None:
    session = _login_sessions.pop(session_id, None)
    if session is None:
        return
    expiry_handle = session.get("expiry_handle")
    if expiry_handle is not None:
        expiry_handle.cancel()
    task = session.get("task")
    if cancel_task and task is not None and not task.done():
        task.cancel()


def _discard_all_login_sessions() -> None:
    for session_id in list(_login_sessions):
        _discard_login_session(session_id)


def _schedule_login_session_expiry(session_id: str, delay: float) -> None:
    session = _login_sessions.get(session_id)
    if session is None:
        return
    old_handle = session.get("expiry_handle")
    if old_handle is not None:
        old_handle.cancel()
    session["expires_at"] = time.monotonic() + delay
    session["expiry_handle"] = asyncio.get_running_loop().call_later(
        delay, _discard_login_session, session_id
    )


def _prune_expired_login_sessions() -> None:
    now = time.monotonic()
    expired = [
        session_id
        for session_id, session in _login_sessions.items()
        if float(session.get("expires_at", 0)) <= now
    ]
    for session_id in expired:
        _discard_login_session(session_id)


async def _handle_device_start() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    body = await request.json(default={}) or {}
    if not isinstance(body, dict):
        return _login_error_response("请求格式无效", 400)
    proxy = str(body.get("proxy", "") or "")
    owner = str(request.username)
    _prune_expired_login_sessions()
    if len(_login_sessions) >= _MAX_LOGIN_SESSIONS:
        return _login_error_response("设备登录会话已达上限，请稍后重试", 429)
    owner_sessions = sum(
        secrets.compare_digest(str(session.get("owner", "")), owner)
        for session in _login_sessions.values()
    )
    if owner_sessions >= _MAX_LOGIN_SESSIONS_PER_USER:
        return _login_error_response("你的设备登录会话已达上限，请稍后重试", 429)

    # Reserve the bounded slot before the first await so concurrent starts cannot
    # race past the quota check.
    session_id = secrets.token_urlsafe(32)
    session = {
        "owner": owner,
        "status": "starting",
        "device_auth_id": None,
        "user_code": None,
        "interval": None,
        "error": None,
        "task": None,
    }
    _login_sessions[session_id] = session
    _schedule_login_session_expiry(
        session_id, CODEX_DEVICE_LOGIN_TIMEOUT + _LOGIN_RESULT_TTL_SECONDS
    )
    try:
        device_auth_id, user_code, interval = await request_device_user_code(proxy)
    except DeviceAuthError as exc:
        _discard_login_session(session_id)
        return _login_error_response(str(exc), 400)
    except Exception:  # noqa: BLE001 - keep network details out of the response
        _discard_login_session(session_id)
        logger.exception("OpenAI Codex device-code request failed.")
        return _login_error_response("无法启动设备登录，请稍后重试", 502)
    session = _login_sessions.get(session_id)
    if session is None:
        return _login_error_response("登录会话已过期", 410)
    session.update(
        {
            "status": "pending",
            "device_auth_id": device_auth_id,
            "user_code": user_code,
            "interval": interval,
        }
    )
    session["task"] = asyncio.create_task(_run_device_login(session_id, proxy))
    return json_response(
        {
            "status": "pending",
            "session_id": session_id,
            "verify_url": CODEX_DEVICE_VERIFY_URL,
            "user_code": user_code,
            "interval": interval,
        },
        headers=_NO_STORE_HEADERS,
    )


async def _persist_login_credentials(creds: dict) -> None:
    """Persist credentials produced by the server-owned device session."""
    cfg_mgr = _config_mgr
    if cfg_mgr is None:
        raise RuntimeError("配置管理器不可用")
    conf = cfg_mgr.default_conf
    sources = conf.setdefault("provider_sources", [])
    source = next(
        (
            item
            for item in sources
            if item.get("type") == _PROVIDER_TYPE or item.get("id") == _PROVIDER_TYPE
        ),
        None,
    )
    if source is None:
        source = {
            "provider": "openai",
            "type": _PROVIDER_TYPE,
            "provider_type": "chat_completion",
            "key": "",
            "api_base": CODEX_BASE,
            "proxy": "",
            "originator": DEFAULT_ORIGINATOR,
            "user_agent": DEFAULT_USER_AGENT,
            "id": _PROVIDER_TYPE,
            "enable": True,
        }
        sources.append(source)
    source["key"] = dump_credentials(creds)
    await conf.save_config_async()


async def _run_device_login(session_id: str, proxy: str) -> None:
    session = _login_sessions.get(session_id)
    if session is None:
        return
    try:
        authorization_code, code_verifier = await poll_device_authorization(
            session["device_auth_id"],
            session["user_code"],
            session["interval"],
            proxy,
        )
        tokens = await exchange_authorization_code(
            authorization_code, code_verifier, proxy
        )
        creds = build_credentials(
            tokens["access_token"],
            tokens.get("refresh_token", ""),
            tokens.get("expires_in", 3600),
        )
        await _persist_login_credentials(creds)
        session["status"] = "success"
        logger.info("OpenAI Codex device login succeeded.")
    except asyncio.CancelledError:
        raise
    except DeviceAuthTimeout as exc:
        session["status"] = "timeout"
        session["error"] = str(exc)
    except DeviceAuthError as exc:
        session["status"] = "error"
        session["error"] = str(exc)
    except Exception:  # noqa: BLE001 - report a generic error without credential data
        session["status"] = "error"
        session["error"] = "登录或保存失败，请重试"
        logger.exception("OpenAI Codex device login failed.")
    finally:
        if _login_sessions.get(session_id) is session:
            _schedule_login_session_expiry(session_id, _LOGIN_RESULT_TTL_SECONDS)


async def _handle_device_poll() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    body = await request.json(default={}) or {}
    if not isinstance(body, dict):
        return _login_error_response("请求格式无效", 400)
    session_id = str(body.get("session_id", "") or "")
    _prune_expired_login_sessions()
    session = _login_sessions.get(session_id)
    owner = str(request.username)
    if session is None or not secrets.compare_digest(
        str(session.get("owner", "")), owner
    ):
        return _login_error_response("登录会话不存在或已过期", 404)
    payload = {
        "status": session["status"],
        "error": session.get("error"),
    }
    if session["status"] in {"success", "error", "timeout"}:
        _discard_login_session(session_id, cancel_task=False)
    return json_response(payload, headers=_NO_STORE_HEADERS)


async def _handle_login_page() -> HTMLResponse:
    if message := _login_request_error():
        return HTMLResponse(
            message,
            status_code=403,
            headers=_LOGIN_PAGE_HEADERS,
        )
    return HTMLResponse(_LOGIN_PAGE_HTML, headers=_LOGIN_PAGE_HEADERS)


_LOGIN_PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenAI 订阅登录 (Codex)</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 620px; margin: 40px auto; padding: 0 16px; line-height: 1.6; }
  h1 { font-size: 20px; }
  button { font-size: 14px; padding: 8px 16px; border: none; border-radius: 8px; background: #10a37f; color: #fff; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  #steps { margin-top: 16px; }
  #steps p { margin: 8px 0; }
  .url { color: #10a37f; }
  .code { font-size: 18px; font-weight: 600; background: #f0f0f0; padding: 2px 8px; border-radius: 6px; }
  #status { margin-top: 12px; color: #666; }
  #error { margin-top: 12px; color: #c00; white-space: pre-wrap; }
  .ok { color: #0a7a3d; }
</style>
</head>
<body>
  <h1>OpenAI 订阅登录 (Codex OAuth)</h1>
  <p>用你的 ChatGPT 账号授权，生成 provider 的凭据。</p>
  <button id="start">开始登录</button>
  <div id="steps" hidden>
    <p>1. 打开链接：<a id="url" class="url" target="_blank" rel="noopener"></a></p>
    <p>2. 输入设备码：<span class="code" id="code"></span></p>
  </div>
  <div id="status"></div>
  <div id="result" hidden>
    <p class="ok" id="result-text">登录成功，凭据已写入模型配置。</p>
  </div>
  <div id="error" hidden></div>
  <script>
    const BASE = "/api/v1/plugins/extensions/astrbot_plugin_openai_oauth";
    const $ = (id) => document.getElementById(id);
    const startBtn = $("start");
    startBtn.addEventListener("click", async () => {
      startBtn.disabled = true;
      try {
        const resp = await fetch(BASE + "/device/start", { method: "POST" });
        const data = await resp.json();
        if (data.status === "error") { showError(data.message || "启动失败"); return; }
        $("steps").hidden = false;
        $("url").textContent = data.verify_url;
        $("url").href = data.verify_url;
        $("code").textContent = data.user_code;
        setStatus("等待授权：请在打开的页面完成登录……");
        poll(data.session_id, Math.max(2, Number(data.interval) || 5));
      } catch (e) { showError(String(e)); }
    });
    function poll(sessionId, interval) {
      const timer = setInterval(async () => {
        try {
          const resp = await fetch(BASE + "/device/poll", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
          });
          const data = await resp.json();
          if (data.status === "success") {
            clearInterval(timer);
            $("result").hidden = false;
            setStatus("登录成功。");
          } else if (data.status === "error" || data.status === "timeout") {
            clearInterval(timer);
            showError(data.error || "登录失败");
          }
        } catch (e) { /* 瞬时错误继续轮询 */ }
      }, interval * 1000);
    }
    function setStatus(text) {
      $("status").textContent = text;
      $("error").hidden = true;
    }
    function showError(text) {
      $("status").textContent = "";
      $("error").hidden = false;
      $("error").textContent = text;
      startBtn.disabled = false;
    }
  </script>
</body>
</html>
"""
