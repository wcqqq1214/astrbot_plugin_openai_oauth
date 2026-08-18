"""astrbot_plugin_openai_oauth — ChatGPT 订阅 (Codex OAuth) provider.

注册一个 `OpenAI Subscribe` provider：登录 ChatGPT 账号后，AI 调用走账号订阅
额度。个人自用场景使用。
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections.abc import AsyncGenerator
from copy import deepcopy
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
from astrbot.core.workspace import API_KEY_USERNAME_PREFIX

from .credential_store import (
    CredentialCooldownError,
    CredentialCoordinator,
    CredentialError,
    CredentialSchemaError,
    CredentialSnapshot,
    CredentialsNotConfiguredError,
    CredentialSourceError,
    ReauthenticationRequiredError,
    parse_credentials,
)
from .oauth import (
    CODEX_BASE,
    CODEX_DEVICE_LOGIN_TIMEOUT,
    CODEX_DEVICE_VERIFY_URL,
    CODEX_FALLBACK_MODELS,
    DEFAULT_ORIGINATOR,
    DEFAULT_USER_AGENT,
    CredentialExpiredError,
    DeviceAuthError,
    DeviceAuthTimeout,
    build_credentials,
    classify_codex_error,
    exchange_authorization_code,
    fetch_models,
    fetch_rate_limits,
    poll_device_authorization,
    refresh_access_token,
    request_device_user_code,
)

_REFRESH_SKEW_SECONDS = 120

# WebUI 模型配置里展示的 provider 类型名（也是配置里的 type/id）。
_PROVIDER_TYPE = "OpenAI Subscribe"

# Injected by OpenAI_OAuth_Plugin so provider instances can resolve current
# source-scoped credentials from AstrBot configuration.
_config_mgr: Any = None
_credential_coordinator: CredentialCoordinator | None = None
_COORDINATOR_ATTR = "_astrbot_openai_oauth_credential_coordinator"
_command_login_tasks: dict[str, asyncio.Task[Any]] = {}


def _build_default_source_config() -> dict[str, Any]:
    return {
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


def _default_provider_template() -> dict[str, Any]:
    source = _build_default_source_config()
    return {
        key: source[key]
        for key in (
            "provider",
            "provider_type",
            "key",
            "model",
            "proxy",
            "originator",
            "user_agent",
        )
        if key in source
    } | {"model": "gpt-5.4-mini"}


def _get_credential_coordinator() -> CredentialCoordinator:
    global _credential_coordinator
    cfg_mgr = _config_mgr
    if cfg_mgr is None:
        raise CredentialError("The AstrBot configuration manager is unavailable.")

    existing = getattr(cfg_mgr, _COORDINATOR_ATTR, None)
    if isinstance(existing, CredentialCoordinator):
        existing.update_refresh_credentials(refresh_access_token)
        _credential_coordinator = existing
        return existing
    if (
        _credential_coordinator is not None
        and _credential_coordinator.config_manager is cfg_mgr
    ):
        _credential_coordinator.update_refresh_credentials(refresh_access_token)
        return _credential_coordinator

    coordinator = CredentialCoordinator(
        cfg_mgr,
        provider_type=_PROVIDER_TYPE,
        default_source_id=_PROVIDER_TYPE,
        default_source_factory=_build_default_source_config,
        refresh_credentials=refresh_access_token,
        refresh_skew_seconds=_REFRESH_SKEW_SECONDS,
    )
    try:
        setattr(cfg_mgr, _COORDINATOR_ATTR, coordinator)
    except (AttributeError, TypeError):
        pass
    _credential_coordinator = coordinator
    return coordinator


@register(
    "astrbot_plugin_openai_oauth",
    "wcqqq1214",
    "ChatGPT 订阅 (Codex OAuth) provider 插件",
    "1.1.0",
)
class OpenAI_OAuth_Plugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        global _config_mgr
        super().__init__(context)
        _config_mgr = context.astrbot_config_mgr
        _get_credential_coordinator()
        self.config = config if config is not None else AstrBotConfig()
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
            "/astrbot_plugin_openai_oauth/device/cancel",
            _handle_device_cancel,
            ["POST"],
            "取消 Codex 设备登录",
        )
        self.context.register_web_api(
            "/astrbot_plugin_openai_oauth/account/status",
            _handle_account_status,
            ["POST"],
            "查询 OpenAI 登录状态",
        )
        self.context.register_web_api(
            "/astrbot_plugin_openai_oauth/account/usage",
            _handle_account_usage,
            ["POST"],
            "查询 OpenAI 订阅额度",
        )

    @filter.command("usage")
    async def usage(self, event: AstrMessageEvent) -> None:
        """查询 OpenAI 订阅剩余额度。"""
        if not _is_logged_in():
            # 未登录时命令不可用：静默拦截，不触发默认 LLM。
            event.should_call_llm(False)
            return
        await event.send(MessageChain().message(await build_usage_message()))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("openai_login")
    async def openai_login(self, event: AstrMessageEvent) -> None:
        """Start the administrator-only private-chat device login fallback."""
        event.should_call_llm(False)
        if not _is_private_login_event(event):
            await event.send(
                MessageChain().message(
                    "为保护设备码，/openai_login 仅允许在管理员私聊中使用。"
                )
            )
            return

        owner = _command_login_owner(event)
        existing_task = _command_login_tasks.get(owner)
        if existing_task is not None and not existing_task.done():
            await event.send(
                MessageChain().message(
                    "当前私聊已有一个 OpenAI 登录流程，请先完成或等待它结束。"
                )
            )
            return

        current_task = asyncio.current_task()
        if current_task is not None:
            _command_login_tasks[owner] = current_task
        try:
            proxy = _get_credential_coordinator().source_settings()["proxy"]
        except CredentialSourceError:
            proxy = ""
        try:
            try:
                device_auth_id, user_code, interval = await request_device_user_code(
                    proxy
                )
            except DeviceAuthError as exc:
                await event.send(MessageChain().message(f"无法启动设备登录：{exc}"))
                return
            except Exception as exc:  # noqa: BLE001 - keep network details out of chat
                logger.error(
                    "OpenAI Codex admin device-code request failed: %s",
                    type(exc).__name__,
                )
                await event.send(
                    MessageChain().message("无法启动设备登录，请稍后重试。")
                )
                return

            await event.send(
                MessageChain().message(
                    "请在当前私聊中打开以下 OpenAI 验证网址并输入设备码：\n"
                    f"{CODEX_DEVICE_VERIFY_URL}\n"
                    f"设备码：{user_code}\n"
                    "授权完成后，AstrBot 会在服务端自动交换并保存凭据；令牌不会发送到聊天。"
                )
            )
            task = asyncio.create_task(
                _run_command_device_login(
                    event,
                    device_auth_id,
                    user_code,
                    interval,
                    proxy,
                )
            )
            _command_login_tasks[owner] = task
            task.add_done_callback(
                lambda done: _release_command_login_task(owner, done)
            )
        finally:
            if (
                current_task is not None
                and _command_login_tasks.get(owner) is current_task
            ):
                _command_login_tasks.pop(owner, None)

    async def terminate(self) -> None:
        """Cancel all outstanding device-login work during plugin unload."""
        _discard_all_login_sessions()
        tasks = _cancel_all_command_login_tasks()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


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
            default_config_tmpl=_default_provider_template(),
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
        try:
            bootstrap_creds = parse_credentials(raw_key)
        except CredentialSchemaError:
            bootstrap_creds = {}
        self._bootstrap_access_token = str(
            bootstrap_creds.get("access_token", "") or ""
        )
        self._source_id = str(
            provider_config.get("provider_source_id") or _PROVIDER_TYPE
        )
        self._originator = str(provider_config.get("originator", DEFAULT_ORIGINATOR))
        self._user_agent = str(provider_config.get("user_agent", DEFAULT_USER_AGENT))
        raw_headers = provider_config.get("custom_headers")
        self._static_headers = (
            {
                str(key): str(value)
                for key, value in raw_headers.items()
                if isinstance(key, str)
            }
            if isinstance(raw_headers, dict)
            else {}
        )
        for header_name in list(self._static_headers):
            if header_name.lower() == "chatgpt-account-id":
                self._static_headers.pop(header_name)
        self._static_headers.setdefault("originator", self._originator)
        self._static_headers.setdefault("OpenAI-Beta", "responses=experimental")
        self._static_headers.setdefault("User-Agent", self._user_agent)
        provider_config["api_base"] = CODEX_BASE
        provider_config["key"] = "openai-oauth-request-scoped"
        provider_config["custom_headers"] = dict(self._static_headers)

        super().__init__(provider_config, provider_settings)
        self.api_keys = [self._bootstrap_access_token]
        self.chosen_api_key = self._bootstrap_access_token
        self.set_model(provider_config.get("model", "gpt-5.4-mini"))

    def get_keys(self) -> list[str]:
        return [self._bootstrap_access_token]

    def get_current_key(self) -> str:
        return self._bootstrap_access_token

    def set_key(self, key: str) -> None:
        try:
            creds = parse_credentials(key)
        except CredentialSchemaError:
            creds = {}
        self._bootstrap_access_token = str(creds.get("access_token", "") or "")
        self.api_keys = [self._bootstrap_access_token]
        self.chosen_api_key = self._bootstrap_access_token

    def _request_client(self, snapshot: CredentialSnapshot) -> Any:
        headers = dict(self._static_headers)
        if snapshot.account_id:
            headers["chatgpt-account-id"] = snapshot.account_id
        return self.client.with_options(
            api_key=snapshot.access_token,
            set_default_headers=headers,
        )

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
        request_client: Any,
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
            lambda: request_client.responses.create(
                **payloads,
                stream=True,
                extra_body=extra_body,
            ),
            retry_rate_limits=False,
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
                raise RuntimeError(
                    f"Responses API stream failed: {code}. response_id={response_id}"
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
                        raise RuntimeError(
                            f"Responses API request failed: {code}. "
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
        try:
            coordinator = _get_credential_coordinator()
            snapshot = await coordinator.get_snapshot(self._source_id)
            try:
                models = await fetch_models(
                    snapshot.access_token,
                    snapshot.account_id,
                    self._request_proxy(),
                    self._originator,
                    self._user_agent,
                )
            except CredentialExpiredError:
                snapshot = await coordinator.get_snapshot(
                    self._source_id,
                    force_refresh=True,
                    check_cooldown=False,
                )
                models = await fetch_models(
                    snapshot.access_token,
                    snapshot.account_id,
                    self._request_proxy(),
                    self._originator,
                    self._user_agent,
                )
            if models:
                return models
            logger.warning("OpenAI Codex model catalog contained no model IDs.")
        except (CredentialError, CredentialExpiredError):
            return list(CODEX_FALLBACK_MODELS)
        except Exception as exc:  # noqa: BLE001 - catalog failure uses offline fallback
            logger.error("OpenAI Codex model catalog failed: %s", type(exc).__name__)
        return list(CODEX_FALLBACK_MODELS)

    def _request_proxy(self) -> str:
        try:
            return _get_credential_coordinator().source_settings(self._source_id)[
                "proxy"
            ]
        except CredentialSourceError:
            return str(self.provider_config.get("proxy", "") or "")

    async def _fetch_usage_for_snapshot(
        self,
        snapshot: CredentialSnapshot,
    ) -> dict[str, Any]:
        return await retry_provider_request(
            "OpenAI Codex",
            lambda: fetch_rate_limits(
                snapshot.access_token,
                snapshot.account_id,
                self._request_proxy(),
                self._user_agent,
            ),
            retry_rate_limits=False,
            max_attempts=2,
        )

    async def _subscription_cooldown_error(
        self,
        snapshot: CredentialSnapshot,
    ) -> CredentialCooldownError:
        coordinator = _get_credential_coordinator()
        cooldown_until: int | None = None
        try:
            usage = await coordinator.get_usage(
                self._source_id,
                self._fetch_usage_for_snapshot,
            )
            cooldown_until = _cooldown_until_from_usage(usage)
        except Exception as exc:  # noqa: BLE001 - a failed usage lookup is non-fatal
            logger.warning(
                "OpenAI Codex quota lookup after rate limit failed: %s",
                type(exc).__name__,
            )
        if cooldown_until is None:
            cooldown_until = int(time.time()) + 300
        persisted = await coordinator.mark_cooling(
            self._source_id,
            cooldown_until,
            expected_access_token=snapshot.access_token,
        )
        return CredentialCooldownError(
            persisted.cooldown_until,
            persisted.cooldown_reason,
        )

    async def _stream_with_current_credentials(
        self,
        payloads: dict[str, Any],
        tools: Any,
        *,
        request_max_retries: int | None,
    ) -> AsyncGenerator[LLMResponse, None]:
        coordinator = _get_credential_coordinator()
        retry_after_credential_error = True
        emitted_chunk = False
        base_payloads = deepcopy(payloads)

        while True:
            snapshot = await coordinator.get_snapshot(self._source_id)
            request_client = self._request_client(snapshot)
            try:
                async for response in self._query_stream(
                    request_client,
                    deepcopy(base_payloads),
                    tools,
                    request_max_retries=request_max_retries,
                ):
                    emitted_chunk = True
                    yield response
                return
            except Exception as exc:
                error_kind = classify_codex_error(exc)
                if error_kind == "usage_limit":
                    cooldown_error = await self._subscription_cooldown_error(snapshot)
                    raise cooldown_error from exc
                if (
                    error_kind == "credential"
                    and retry_after_credential_error
                    and not emitted_chunk
                ):
                    retry_after_credential_error = False
                    await coordinator.get_snapshot(
                        self._source_id,
                        force_refresh=True,
                        check_cooldown=False,
                    )
                    continue
                raise

    async def text_chat(
        self,
        prompt=None,
        session_id=None,
        image_urls=None,
        audio_urls=None,
        func_tool=None,
        contexts=None,
        system_prompt=None,
        tool_calls_result=None,
        model=None,
        extra_user_content_parts=None,
        tool_choice="auto",
        request_max_retries: int | None = None,
        **kwargs,
    ) -> LLMResponse:
        final_response = None
        async for chunk in self.text_chat_stream(
            prompt=prompt,
            session_id=session_id,
            image_urls=image_urls,
            audio_urls=audio_urls,
            func_tool=func_tool,
            contexts=contexts,
            system_prompt=system_prompt,
            tool_calls_result=tool_calls_result,
            model=model,
            extra_user_content_parts=extra_user_content_parts,
            tool_choice=tool_choice,
            request_max_retries=request_max_retries,
            **kwargs,
        ):
            if not chunk.is_chunk:
                final_response = chunk
        if final_response is None:
            raise RuntimeError("OpenAI Codex returned no complete response.")
        return final_response

    async def text_chat_stream(
        self,
        prompt=None,
        session_id=None,
        image_urls=None,
        audio_urls=None,
        func_tool=None,
        contexts=None,
        system_prompt=None,
        tool_calls_result=None,
        model=None,
        extra_user_content_parts=None,
        tool_choice="auto",
        request_max_retries: int | None = None,
        **kwargs,
    ) -> AsyncGenerator[LLMResponse, None]:
        payloads, _ = await self._prepare_chat_payload(
            prompt,
            image_urls,
            audio_urls,
            contexts,
            system_prompt,
            tool_calls_result,
            model=model,
            extra_user_content_parts=extra_user_content_parts,
            **kwargs,
        )
        if func_tool and not func_tool.empty():
            payloads["tool_choice"] = tool_choice
        async for item in self._stream_with_current_credentials(
            payloads,
            func_tool,
            request_max_retries=request_max_retries,
        ):
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


def _is_logged_in() -> bool:
    """Return whether the default source has a credential record."""
    try:
        status = _get_credential_coordinator().status()
    except CredentialError:
        return False
    return status.state not in {"not_logged_in", "invalid"}


def _is_private_login_event(event: AstrMessageEvent) -> bool:
    """Return whether the event is a direct message, failing closed if unknown."""
    checker = getattr(event, "is_private_chat", None)
    return callable(checker) and bool(checker())


def _command_login_owner(event: AstrMessageEvent) -> str:
    """Build a non-secret owner key for one private command session."""
    try:
        owner = str(event.unified_msg_origin or "").strip()
    except (AttributeError, TypeError):
        owner = ""
    return owner or f"event:{id(event)}"


def _release_command_login_task(owner: str, task: asyncio.Task[Any]) -> None:
    if _command_login_tasks.get(owner) is task:
        _command_login_tasks.pop(owner, None)


def _cancel_all_command_login_tasks() -> list[asyncio.Task[Any]]:
    tasks = list(set(_command_login_tasks.values()))
    _command_login_tasks.clear()
    for task in tasks:
        if not task.done():
            task.cancel()
    return tasks


def _cooldown_until_from_usage(usage: dict[str, Any]) -> int | None:
    reset_times: list[int] = []
    now = time.time()
    for window in usage.get("windows") or []:
        reset_at = window.get("reset_at")
        if isinstance(reset_at, (int, float)):
            reset_times.append(int(reset_at))
            continue
        reset_after = window.get("reset_after_seconds")
        if isinstance(reset_after, (int, float)) and reset_after >= 0:
            reset_times.append(int(now + reset_after))
    return max(reset_times, default=None)


def _format_cooldown(cooldown_until: int | None) -> str:
    return f"OpenAI 订阅额度当前处于冷却状态{_format_reset_at(cooldown_until, None)}。"


async def _fetch_source_usage(source_id: str = _PROVIDER_TYPE) -> dict[str, Any]:
    coordinator = _get_credential_coordinator()

    async def fetch_usage(snapshot: CredentialSnapshot) -> dict:
        settings = coordinator.source_settings(snapshot.source_id)
        return await retry_provider_request(
            "OpenAI Codex",
            lambda: fetch_rate_limits(
                snapshot.access_token,
                snapshot.account_id,
                settings["proxy"],
                settings["user_agent"] or DEFAULT_USER_AGENT,
            ),
            retry_rate_limits=False,
            max_attempts=3,
        )

    usage = await coordinator.get_usage(source_id, fetch_usage)
    if usage.get("limit_reached") or not usage.get("allowed", True):
        cooldown_until = _cooldown_until_from_usage(usage)
        if cooldown_until is not None:
            await coordinator.mark_cooling(
                source_id,
                cooldown_until,
                expected_access_token=None,
            )
    return usage


async def build_usage_message() -> str:
    """Fetch the default source's quota through the credential coordinator."""
    try:
        usage = await _fetch_source_usage()
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


# ---- Device-login Web API ----

_MAX_LOGIN_SESSIONS = 8
_MAX_LOGIN_SESSIONS_PER_USER = 2
_LOGIN_RESULT_TTL_SECONDS = 120
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}

# session_id -> {owner, status, device_auth_id, user_code, interval, error,
#                task, expiry_handle, expires_at}
_login_sessions: dict[str, dict] = {}


def _login_request_error() -> str | None:
    owner = str(request.username or "")
    if not owner:
        return "登录会话身份不可用"
    if owner.startswith(API_KEY_USERNAME_PREFIX):
        return "此操作仅允许已登录的 WebUI 用户，API Key 不可用"
    return None


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
    try:
        proxy = _get_credential_coordinator().source_settings()["proxy"]
    except CredentialSourceError:
        proxy = ""
    owner = str(request.username)
    _prune_expired_login_sessions()
    for existing_id, existing in _login_sessions.items():
        if existing.get("source_id") != _PROVIDER_TYPE or existing.get(
            "status"
        ) not in {"starting", "pending"}:
            continue
        if secrets.compare_digest(str(existing.get("owner", "")), owner):
            if existing.get("status") != "pending":
                return _login_error_response("设备登录正在启动，请稍后重试", 409)
            return json_response(
                {
                    "status": "pending",
                    "session_id": existing_id,
                    "verify_url": CODEX_DEVICE_VERIFY_URL,
                    "user_code": existing["user_code"],
                    "interval": existing["interval"],
                },
                headers=_NO_STORE_HEADERS,
            )
        return _login_error_response("另一位用户正在登录该 OpenAI source", 409)
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
        "source_id": _PROVIDER_TYPE,
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
    except Exception as exc:  # noqa: BLE001 - keep network details out of the response
        _discard_login_session(session_id)
        logger.error(
            "OpenAI Codex device-code request failed: %s",
            type(exc).__name__,
        )
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


async def _persist_login_credentials(creds: dict[str, Any]) -> None:
    """Persist credentials produced by the server-owned device session."""
    await _get_credential_coordinator().replace_credentials(_PROVIDER_TYPE, creds)


async def _complete_device_login(
    *,
    device_auth_id: str,
    user_code: str,
    interval: int,
    proxy: str,
) -> dict:
    """Poll, exchange, and build credentials for one device challenge."""
    authorization_code, code_verifier = await poll_device_authorization(
        device_auth_id,
        user_code,
        interval,
        proxy,
    )
    tokens = await exchange_authorization_code(
        authorization_code,
        code_verifier,
        proxy,
    )
    return build_credentials(
        tokens["access_token"],
        tokens.get("refresh_token", ""),
        tokens.get("expires_in", 3600),
    )


async def _run_device_login(session_id: str, proxy: str) -> None:
    session = _login_sessions.get(session_id)
    if session is None:
        return
    try:
        creds = await _complete_device_login(
            device_auth_id=session["device_auth_id"],
            user_code=session["user_code"],
            interval=session["interval"],
            proxy=proxy,
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
    except Exception as exc:  # noqa: BLE001 - report a generic error without credential data
        session["status"] = "error"
        session["error"] = "登录或保存失败，请重试"
        logger.error("OpenAI Codex device login failed: %s", type(exc).__name__)
    finally:
        if _login_sessions.get(session_id) is session:
            _schedule_login_session_expiry(session_id, _LOGIN_RESULT_TTL_SECONDS)


async def _run_command_device_login(
    event: AstrMessageEvent,
    device_auth_id: str,
    user_code: str,
    interval: int,
    proxy: str,
) -> None:
    """Complete a private-command login without exposing credential material."""
    try:
        creds = await _complete_device_login(
            device_auth_id=device_auth_id,
            user_code=user_code,
            interval=interval,
            proxy=proxy,
        )
        await _persist_login_credentials(creds)
    except asyncio.CancelledError:
        raise
    except DeviceAuthTimeout:
        await event.send(
            MessageChain().message("设备码已过期，请重新发送 /openai_login。")
        )
    except DeviceAuthError as exc:
        await event.send(MessageChain().message(f"OpenAI 登录失败：{exc}"))
    except Exception as exc:  # noqa: BLE001 - never send provider or credential details
        logger.error("OpenAI Codex admin device login failed: %s", type(exc).__name__)
        await event.send(MessageChain().message("OpenAI 登录或保存失败，请重试。"))
    else:
        await event.send(
            MessageChain().message("OpenAI 登录成功，凭据已由 AstrBot 服务端保存。")
        )


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


async def _handle_device_cancel() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    body = await request.json(default={}) or {}
    if not isinstance(body, dict):
        return _login_error_response("请求格式无效", 400)
    session_id = str(body.get("session_id", "") or "")
    session = _login_sessions.get(session_id)
    owner = str(request.username)
    if session is None or not secrets.compare_digest(
        str(session.get("owner", "")), owner
    ):
        return _login_error_response("登录会话不存在或已过期", 404)
    _discard_login_session(session_id)
    return json_response({"status": "cancelled"}, headers=_NO_STORE_HEADERS)


async def _handle_account_status() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    try:
        status = _get_credential_coordinator().status().as_dict()
    except CredentialError:
        status = {"status": "invalid"}
    return json_response(status, headers=_NO_STORE_HEADERS)


async def _handle_account_usage() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    try:
        usage = await _fetch_source_usage()
    except CredentialCooldownError as exc:
        return json_response(
            {
                "status": "cooling",
                "cooldown_until": exc.cooldown_until,
                "cooldown_reason": exc.reason,
            },
            headers=_NO_STORE_HEADERS,
        )
    except (
        CredentialsNotConfiguredError,
        ReauthenticationRequiredError,
        CredentialExpiredError,
    ):
        return json_response({"status": "reauth_required"}, headers=_NO_STORE_HEADERS)
    except CredentialSchemaError:
        return json_response({"status": "invalid"}, headers=_NO_STORE_HEADERS)
    except CredentialError:
        return json_response({"status": "invalid"}, headers=_NO_STORE_HEADERS)
    except Exception as exc:  # noqa: BLE001 - do not expose provider responses
        logger.error("OpenAI Codex usage API failed: %s", type(exc).__name__)
        return _login_error_response("额度查询失败，请稍后重试", 502)
    return json_response(
        {"status": "success", "usage": usage},
        headers=_NO_STORE_HEADERS,
    )
