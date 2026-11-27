"""Codex provider adapter: credentials, retries and account routing."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, aclosing, asynccontextmanager
from copy import deepcopy
from typing import Any

from astrbot.api import logger
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.register import (
    provider_cls_map,
    register_provider_adapter,
)
from astrbot.core.provider.sources.openai_responses_source import (
    ProviderOpenAIResponses,
)
from astrbot.core.provider.sources.request_retry import (
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_WAIT_MAX_S,
    retry_provider_request,
)
from astrbot.core.utils.config_number import coerce_int_config

from . import (
    astrbot_image_bridge,
    codex_request,
    effort,
    image_generation,
    image_input,
    messages,
    oauth,
    runtime,
)
from . import usage as usage_service
from .codex_search import track_web_search
from .codex_stream import CodexStreamMixin
from .credential_store import (
    CredentialCooldownError,
    CredentialError,
    CredentialPersistenceError,
    CredentialRefreshError,
    CredentialSchemaError,
    CredentialSnapshot,
    CredentialsNotConfiguredError,
    CredentialSourceError,
    ProviderDisabledError,
    ReauthenticationRequiredError,
    parse_credentials,
)
from .oauth import (
    CODEX_BASE,
    CODEX_FALLBACK_MODELS,
    DEFAULT_ORIGINATOR,
    CredentialExpiredError,
)
from .provider_registry import LOCAL
from .provider_routing import (
    ROUTING_TIMEOUT_SECONDS,
    SOURCE_ATTEMPTS,
    RequestBudget,
    RoutingBudgetError,
    RoutingExhaustedError,
)
from .source_editor import HookCompatibilityError
from .transport_pool import TransportPool

try:
    from astrbot.core.provider.sources.chat_request import chat_request
except ModuleNotFoundError as exc:
    if exc.name != "astrbot.core.provider.sources.chat_request":
        raise
    chat_request = None


def _attempt_limit(request_max_retries: int | None) -> int:
    """Resolve AstrBot's request attempt setting, warning only when it is set."""
    return coerce_int_config(
        request_max_retries,
        default=REQUEST_RETRY_ATTEMPTS,
        min_value=1,
        field_name="request_max_retries",
        source="OpenAI Codex",
        warn=request_max_retries is not None,
    )


def _localize_provider_error(
    exc: BaseException, *, lang: str | None = None
) -> str | None:
    """Translate user-facing credential errors at the chat boundary."""
    if not isinstance(exc, CredentialError):
        return None
    if isinstance(exc, HookCompatibilityError):
        return messages.text("usage.incompatible", lang=lang)
    if isinstance(exc, RoutingExhaustedError):
        return messages.format_routing_exhausted(exc.reason, exc.failures, lang=lang)
    if isinstance(exc, ProviderDisabledError):
        return messages.text("provider.disabled", lang=lang)
    if isinstance(exc, CredentialsNotConfiguredError):
        return messages.text("provider.not_logged_in", lang=lang)
    if isinstance(exc, CredentialCooldownError):
        return messages.format_cooldown(exc.cooldown_until, lang=lang)
    if isinstance(exc, ReauthenticationRequiredError):
        key = (
            "provider.local_reauth_required"
            if exc.credential_origin == LOCAL
            else "provider.reauth_required"
        )
        return messages.text(key, lang=lang)
    if isinstance(exc, CredentialSchemaError):
        return messages.text("usage.unsupported", lang=lang)
    if isinstance(exc, CredentialRefreshError):
        return messages.text("provider.refresh_failed", lang=lang)
    if isinstance(exc, CredentialPersistenceError):
        return messages.text("provider.save_failed", lang=lang)
    return messages.text("provider.source_error", lang=lang)


def _register_subscription_adapter(cls: type) -> type:
    """Register the provider once and refresh its class on plugin reload.

    AstrBot keeps ``provider_cls_map`` when a plugin module is reloaded. Avoiding
    duplicate registration is necessary, but the metadata must still point to the
    newly imported class or provider instances will continue using stale code.
    The plugin creates its own source, so no manual-add template is published.
    """
    if runtime.PROVIDER_TYPE not in provider_cls_map:
        register_provider_adapter(
            runtime.PROVIDER_TYPE,
            "OpenAI 订阅登录 (Codex OAuth) Provider",
            provider_display_name="OpenAI Subscribe",
        )(cls)
    metadata = provider_cls_map[runtime.PROVIDER_TYPE]
    metadata.cls_type = cls
    metadata.default_config_tmpl = None
    return cls


@_register_subscription_adapter
class ProviderOpenAICodex(CodexStreamMixin, ProviderOpenAIResponses):
    """ChatGPT subscription provider backed by the Codex OAuth flow.

    The key field holds a credential JSON blob:
    ``{"access_token", "refresh_token", "expires", "account_id"}``
    """

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        # The dashboard passes its shared source config when listing models.
        # Keep client placeholders and SDK mutations out of the credential store.
        provider_config = deepcopy(
            {
                key: value
                for key, value in provider_config.items()
                if key not in {"oauth_accounts", "oauth_routing", "oauth_gateway"}
            }
        )
        raw_key = provider_config.get("key")
        try:
            bootstrap_creds = parse_credentials(raw_key)
        except CredentialSchemaError:
            bootstrap_creds = {}
        self._bootstrap_access_token = str(
            bootstrap_creds.get("access_token", "") or ""
        )
        source_id = provider_config.get("provider_source_id")
        if not source_id and runtime._config_mgr is not None:
            sources = runtime._config_mgr.default_conf.get("provider_sources", [])
            source_id = next(
                (
                    s["id"]
                    for s in sources
                    if s.get("id") == provider_config.get("id")
                    and s.get("type") == runtime.PROVIDER_TYPE
                ),
                None,
            )
        self._source_id = str(source_id or runtime.PROVIDER_TYPE)
        originator = str(provider_config.get("originator", DEFAULT_ORIGINATOR))
        user_agent = oauth.resolve_user_agent(provider_config.get("user_agent"))
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
        self._static_headers.setdefault("originator", originator)
        self._static_headers.setdefault("OpenAI-Beta", "responses=experimental")
        self._static_headers.setdefault("User-Agent", user_agent)
        provider_config["api_base"] = CODEX_BASE
        provider_config["key"] = "openai-oauth-request-scoped"
        provider_config["custom_headers"] = dict(self._static_headers)

        super().__init__(provider_config, provider_settings)
        self.api_keys = [self._bootstrap_access_token]
        self.chosen_api_key = self._bootstrap_access_token
        self.set_model(provider_config.get("model", "gpt-5.4-mini"))

    def get_keys(self) -> list[str]:
        return [self._bootstrap_access_token]

    @property
    def _transport_pool(self) -> TransportPool:
        pool = self.__dict__.get("_transports")
        if pool is None:
            pool = self.__dict__["_transports"] = TransportPool()
        return pool

    async def terminate(self) -> None:
        await self._transport_pool.close()
        await super().terminate()

    def get_current_key(self) -> str:
        return self._bootstrap_access_token

    @property
    def _source_id(self) -> str:
        legacy = getattr(self, "_legacy_source_id", runtime.PROVIDER_TYPE)
        try:
            registry = runtime.get_coordinator().providers
        except CredentialError:
            return legacy
        return registry.resolve_model(
            getattr(self, "provider_config", {}).get("id"), legacy
        )

    @_source_id.setter
    def _source_id(self, value: str) -> None:
        self._legacy_source_id = value

    def set_key(self, key: str) -> None:
        try:
            creds = parse_credentials(key)
        except CredentialSchemaError:
            creds = {}
        self._bootstrap_access_token = str(creds.get("access_token", "") or "")
        self.api_keys = [self._bootstrap_access_token]
        self.chosen_api_key = self._bootstrap_access_token

    @asynccontextmanager
    async def _source_client(self, snapshot: CredentialSnapshot):
        """Build a request client on the selected source's own transport."""
        async with self.source_transport(snapshot) as (transport, headers):
            yield self.client.with_options(
                # The plugin owns retries, cooldowns and the cross-provider budget.
                max_retries=0,
                api_key=snapshot.access_token,
                set_default_headers=headers,
                http_client=transport,
            )

    @asynccontextmanager
    async def source_transport(self, snapshot: CredentialSnapshot):
        """Lease the selected source's transport and request headers."""
        coordinator = runtime.get_coordinator()
        source = coordinator.source(snapshot.source_id)
        settings = coordinator.source_settings(snapshot.source_id)
        # Model headers remain useful on the preferred source. Never carry another
        # source's headers or proxy into a fallback account.
        raw = source.get("custom_headers", {})
        if coordinator.providers.gateway() is not None:
            # Resolve saved model headers separately from source headers inherited
            # when this instance was constructed, before an account switch.
            model_id = self.provider_config.get("id")
            model = next(
                (
                    m
                    for m in coordinator.config().get("provider", [])
                    if m.get("id") == model_id
                ),
                {},
            )
            gateway_headers = coordinator.providers.gateway().get("custom_headers", {})
            raw = {
                **(raw if isinstance(raw, dict) else {}),
                **(gateway_headers if isinstance(gateway_headers, dict) else {}),
            }
            model_headers = model.get("custom_headers")
            if snapshot.source_id == self._source_id and isinstance(
                model_headers, dict
            ):
                raw.update(model_headers)
        elif snapshot.source_id == self._source_id:
            raw = self._static_headers
        headers = (
            {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        )
        reserved = {
            "authorization",
            "chatgpt-account-id",
            "originator",
            "user-agent",
            "version",
        }
        headers = {k: v for k, v in headers.items() if k.lower() not in reserved}
        user_agent = oauth.resolve_user_agent(settings["user_agent"])
        headers.update(
            {
                "originator": settings["originator"] or DEFAULT_ORIGINATOR,
                "User-Agent": user_agent,
                "version": oauth.client_version_header(user_agent),
                "OpenAI-Beta": "responses=experimental",
            }
        )
        if snapshot.account_id:
            headers["chatgpt-account-id"] = snapshot.account_id
        proxy = settings["proxy"]
        identity = hashlib.sha256(
            (snapshot.account_id or snapshot.access_token).encode()
        ).hexdigest()
        async with self._transport_pool.lease(
            snapshot.source_id,
            (identity, proxy),
            lambda: self._create_http_client({**self.provider_config, "proxy": proxy}),
        ) as transport:
            yield transport, headers

    def _convert_chat_messages_to_response_input(
        self, messages: list[dict]
    ) -> list[dict]:
        """Shape replayed history for a backend that stores nothing.

        Stored item IDs and message statuses refer to state the backend never
        kept, and a reasoning item can only be replayed with its encrypted
        content. The backend also rejects role "system" in input; "developer"
        carries the same meaning.
        """
        items = super()._convert_chat_messages_to_response_input(messages)
        image_input.restore_original_detail(messages, items)
        return codex_request.shape_replayed_input(items)

    async def _query_stream(
        self,
        request_client: Any,
        payloads: dict,
        tools,
        *,
        request_max_retries: int | None = None,
        conversation_id: str | None = None,
        session_effort: str | None = None,
        reply_language: str | None = None,
        before_attempt: Callable[[], None] | None = None,
        on_stream_open: Callable[[], None] | None = None,
        on_rate_limits: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> AsyncGenerator[LLMResponse, None]:
        """Stream one request shaped for the Codex backend, retrying only
        temporary failures that happen before any output. The final response is
        built by ``CodexStreamMixin`` from the stream's completed output items."""
        extra_body: dict[str, Any] = {}
        custom_extra_body = self.provider_config.get("custom_extra_body", {})
        if isinstance(custom_extra_body, dict):
            extra_body.update(deepcopy(custom_extra_body))

        if tools:
            functions = [
                {"type": "function", **tool["function"]}
                for tool in tools.openai_schema()
            ]
            if functions:
                payloads["tools"] = functions
                payloads.setdefault("tool_choice", "auto")

        if runtime.native_web_search_enabled():
            # Extend the tool list that would actually be sent by the SDK.
            configured_tools = extra_body.pop("tools", payloads.get("tools")) or []
            if not any(
                tool["type"] in {"web_search", "web_search_preview"}
                for tool in configured_tools
            ):
                configured_tools = [
                    *configured_tools,
                    {"type": "web_search", "external_web_access": True},
                ]
            payloads["tools"] = configured_tools
            if payloads.get("tool_choice", "auto") == "auto":
                payloads["tool_choice"] = extra_body.get("tool_choice", "auto")
            extra_body.pop("tool_choice", None)

        for key in list(payloads):
            if key not in self.default_params:
                extra_body[key] = payloads.pop(key)

        codex_request.drop_unsupported_params(payloads, extra_body)
        codex_request.default_tool_strict(payloads, extra_body)
        effective_session_effort = effort.normalize_effort(session_effort)
        supported = oauth.supported_efforts(payloads.get("model"))
        if (
            effective_session_effort
            and supported is not None
            and effective_session_effort not in supported
        ):
            logger.warning(
                "OpenAI Codex model %s does not support reasoning effort %s; "
                "using the model setting.",
                payloads.get("model"),
                effective_session_effort,
            )
            effective_session_effort = None
        if effective_session_effort:
            existing_reasoning = extra_body.get("reasoning")
            reasoning = (
                dict(existing_reasoning) if isinstance(existing_reasoning, dict) else {}
            )
            reasoning["effort"] = effective_session_effort
            extra_body["reasoning"] = reasoning
            extra_body.pop("reasoning_effort", None)
        else:
            reasoning_effort = extra_body.pop("reasoning_effort", None)
            if reasoning_effort is not None and "reasoning" not in extra_body:
                extra_body["reasoning"] = {"effort": reasoning_effort}
        codex_request.request_reasoning_state(payloads, extra_body)
        extra_body.pop("previous_response_id", None)
        extra_body.pop("conversation", None)
        extra_body.pop("store", None)
        payloads.pop("previous_response_id", None)
        payloads.pop("conversation", None)
        payloads["store"] = False

        # The backend finds a conversation's cached prompt by Codex's session
        # headers rather than by the body's key alone.
        cache_key = extra_body.get("prompt_cache_key") or payloads.get(
            "prompt_cache_key"
        )
        session_headers = codex_request.session_headers(cache_key)

        max_attempts = _attempt_limit(request_max_retries)
        attempts = 0
        emitted_response = False

        @asynccontextmanager
        async def open_stream():
            stream = await request_client.responses.create(
                **payloads,
                stream=True,
                extra_body=extra_body,
                **({"extra_headers": session_headers} if session_headers else {}),
            )
            try:
                yield stream
            finally:
                await stream.close()

        async def open_attempt(stack: AsyncExitStack):
            nonlocal attempts
            if before_attempt is not None:
                before_attempt()
            attempts += 1
            if chat_request is None:
                return await stack.enter_async_context(open_stream()), None
            # Credential checks and the shared retry budget belong to the plugin.
            return await stack.enter_async_context(
                chat_request(
                    self,
                    "OpenAI Codex",
                    extra_body.get("model")
                    or payloads.get("model")
                    or self.get_model(),
                    open_stream,
                    conversation_id=conversation_id,
                    max_attempts=1,
                    streaming=True,
                )
            )

        while attempts < max_attempts:
            consuming = False
            try:
                async with AsyncExitStack() as stack:
                    stream, attempt = await retry_provider_request(
                        "OpenAI Responses",
                        lambda: open_attempt(stack),
                        retry_rate_limits=False,
                        max_attempts=max_attempts - attempts,
                    )
                    if on_rate_limits is not None:
                        headers = getattr(
                            getattr(stream, "response", None), "headers", None
                        )
                        if headers is not None:
                            windows = oauth.parse_rate_limit_headers(headers)
                            if windows:
                                on_rate_limits(windows)
                    if on_stream_open is not None:
                        on_stream_open()
                    consuming = True
                    async with (
                        track_web_search(stream, self._field, reply_language) as events,
                        aclosing(
                            self._consume_stream(
                                events,
                                tools,
                                reply_language=reply_language,
                                on_rate_limits=on_rate_limits,
                                attempt=attempt,
                            )
                        ) as responses,
                    ):
                        async for response in responses:
                            emitted_response = True
                            if attempt is not None and response.is_chunk:
                                attempt.mark_first_token()
                            yield response
                    consuming = False
                return
            except Exception as exc:
                if (
                    not consuming
                    or emitted_response
                    or attempts >= max_attempts
                    or oauth.classify_codex_error(exc) != "temporary"
                ):
                    raise
                failure = oauth.safe_error_summary(exc)

            delay = min(2 ** min(attempts - 1, 5), REQUEST_RETRY_WAIT_MAX_S)
            logger.warning(
                "OpenAI Codex stream failed before output: %s; retrying (%s/%s) in %ss.",
                failure,
                attempts + 1,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

    async def get_models(self) -> list[str]:
        try:
            coordinator = runtime.get_coordinator()
            source_id = self._source_id
            settings = coordinator.source_settings(source_id)
            snapshot = await coordinator.get_snapshot(source_id)
            try:
                models = await oauth.fetch_models(
                    snapshot.access_token,
                    snapshot.account_id,
                    settings["proxy"],
                    settings["originator"] or DEFAULT_ORIGINATOR,
                    oauth.resolve_user_agent(settings["user_agent"]),
                )
            except CredentialExpiredError:
                snapshot = await coordinator.get_snapshot(
                    source_id,
                    force_refresh=True,
                    check_cooldown=False,
                )
                models = await oauth.fetch_models(
                    snapshot.access_token,
                    snapshot.account_id,
                    settings["proxy"],
                    settings["originator"] or DEFAULT_ORIGINATOR,
                    oauth.resolve_user_agent(settings["user_agent"]),
                )
            if models:
                return models
            logger.warning("OpenAI Codex model catalog contained no model IDs.")
        except (CredentialError, CredentialExpiredError):
            return list(CODEX_FALLBACK_MODELS)
        except Exception as exc:  # noqa: BLE001 - catalog failure uses offline fallback
            logger.error(
                "OpenAI Codex model catalog failed: %s", oauth.safe_error_summary(exc)
            )
        return list(CODEX_FALLBACK_MODELS)

    async def _subscription_cooldown_error(
        self,
        snapshot: CredentialSnapshot,
    ) -> CredentialCooldownError:
        coordinator = runtime.get_coordinator()
        # Retain a conservative cooldown even if the quota lookup times out or
        # the caller cancels while fetching a more precise reset time.
        provisional = await coordinator.mark_cooling(
            snapshot.source_id,
            int(time.time()) + 300,
            expected_access_token=snapshot.access_token,
        )
        cooldown_until: int | None = None
        try:
            usage = await coordinator.get_usage(
                snapshot.source_id,
                lambda current: usage_service.fetch_usage(current, attempts=2),
                force_refresh=True,
            )
            cooldown_until = usage_service.cooldown_until_from_usage(usage)
        except Exception as exc:  # noqa: BLE001 - a failed usage lookup is non-fatal
            logger.warning(
                "OpenAI Codex quota lookup after rate limit failed: %s",
                oauth.safe_error_summary(exc),
            )
        if cooldown_until is None:
            cooldown_until = provisional.cooldown_until or int(time.time()) + 300
        persisted = await coordinator.mark_cooling(
            snapshot.source_id,
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
        conversation_id: str | None = None,
        session_effort: str | None = None,
        reply_language: str | None = None,
    ) -> AsyncGenerator[LLMResponse, None]:
        coordinator = runtime.get_coordinator()
        candidates = coordinator.providers.candidates(self._source_id)
        automatic = coordinator.providers.routing_mode(self._source_id) == "auto"
        reply_kwargs = (
            {"reply_language": reply_language} if reply_language is not None else {}
        )
        if not automatic:
            async with aclosing(
                self._stream_from_source(
                    self._source_id,
                    payloads,
                    tools,
                    request_max_retries=request_max_retries,
                    session_effort=session_effort,
                    conversation_id=conversation_id,
                    **reply_kwargs,
                )
            ) as stream:
                async for response in stream:
                    yield response
            return

        budget = RequestBudget(_attempt_limit(request_max_retries))
        failures: list[tuple[str, str]] = []
        seen: set[str] = set()
        emitted = False
        try:
            async with asyncio.timeout(ROUTING_TIMEOUT_SECONDS) as deadline:
                # The deadline bounds finding a source that accepts the request.
                # Once a stream is open, the model may think for longer than the
                # deadline before its first delta. A source that fails after that
                # gives the next one a fresh window rather than an expired one.
                loop = asyncio.get_running_loop()
                startup_deadline = deadline.when()

                def stream_opened() -> None:
                    nonlocal startup_deadline
                    startup_deadline = None
                    deadline.reschedule(None)

                for source_id in candidates:
                    if startup_deadline is None:
                        startup_deadline = loop.time() + ROUTING_TIMEOUT_SECONDS
                    deadline.reschedule(startup_deadline)
                    try:
                        coordinator.ensure_inference_available(source_id)
                        initial = coordinator.read_snapshot(source_id)
                        identity = initial.account_id or initial.access_token
                        if identity and identity in seen:
                            failures.append((source_id, "duplicate_account"))
                            continue
                        if budget.remaining <= 0:
                            raise RoutingBudgetError()
                        async with aclosing(
                            self._stream_from_source(
                                source_id,
                                payloads,
                                tools,
                                request_max_retries=min(
                                    SOURCE_ATTEMPTS, budget.remaining
                                ),
                                session_effort=session_effort,
                                budget=budget,
                                seen=seen,
                                on_stream_open=stream_opened,
                                conversation_id=conversation_id,
                                **reply_kwargs,
                            )
                        ) as stream:
                            async for response in stream:
                                emitted = True
                                # Disable the startup deadline before yielding to the consumer.
                                deadline.reschedule(None)
                                yield response
                        return
                    except RoutingBudgetError:
                        failures.append((source_id, "attempt_limit"))
                        raise RoutingExhaustedError(failures, "attempt_limit") from None
                    except Exception as exc:
                        if emitted:
                            raise
                        reasons = (
                            (ProviderDisabledError, "disabled"),
                            (CredentialRefreshError, "temporary"),
                            (CredentialCooldownError, "cooling"),
                            (ReauthenticationRequiredError, "reauth_required"),
                            (CredentialsNotConfiguredError, "not_logged_in"),
                            (CredentialSchemaError, "invalid_credentials"),
                        )
                        reason = next(
                            (value for cls, value in reasons if isinstance(exc, cls)),
                            None,
                        )
                        if reason is None:
                            if isinstance(exc, CredentialError):
                                raise
                            kind = oauth.classify_codex_error(exc)
                            if kind not in {"temporary", "rate_limit"}:
                                raise
                            reason = kind
                        failures.append((source_id, reason))
                raise RoutingExhaustedError(failures) from None
        except TimeoutError:
            if emitted:
                raise
            raise RoutingExhaustedError(failures, "startup_timeout") from None

    async def _stream_from_source(
        self,
        source_id: str,
        payloads: dict[str, Any],
        tools: Any,
        *,
        request_max_retries: int | None,
        conversation_id: str | None = None,
        session_effort: str | None = None,
        reply_language: str | None = None,
        budget: RequestBudget | None = None,
        seen: set[str] | None = None,
        on_stream_open: Callable[[], None] | None = None,
    ) -> AsyncGenerator[LLMResponse, None]:
        coordinator = runtime.get_coordinator()
        retry_after_credential_error = True
        emitted_chunk = False
        base_payloads = deepcopy(payloads)
        selected_identity: str | None = None

        def guard():
            current = coordinator.ensure_inference_available(source_id)
            if (
                current.access_token != snapshot.access_token
                or current.account_id != snapshot.account_id
            ):
                raise CredentialSourceError(
                    "The Provider login changed before dispatch. Retry the request."
                )
            if budget is not None:
                budget.consume()

        while True:
            coordinator.ensure_inference_available(source_id)
            snapshot = await coordinator.get_snapshot(source_id)
            coordinator.ensure_inference_available(source_id)
            identity = snapshot.account_id or snapshot.access_token
            if seen is not None and identity != selected_identity:
                if identity in seen:
                    raise CredentialSourceError(
                        "The selected account changed to an already attempted account."
                    )
                seen.add(identity)
                selected_identity = identity

            def record_limits(
                windows: list[dict[str, Any]],
                *,
                current: CredentialSnapshot = snapshot,
            ) -> None:
                coordinator.record_passive_usage(
                    current.source_id,
                    windows,
                    expected_access_token=current.access_token,
                    expected_account_id=current.account_id,
                    expected_origin=current.credential_origin,
                )

            try:
                query_kwargs: dict[str, Any] = (
                    {"reply_language": reply_language}
                    if reply_language is not None
                    else {}
                )
                if (
                    getattr(self._query_stream, "__func__", None)
                    is ProviderOpenAICodex._query_stream
                ):
                    query_kwargs["on_rate_limits"] = record_limits
                async with (
                    self._source_client(snapshot) as request_client,
                    aclosing(
                        self._query_stream(
                            request_client,
                            deepcopy(base_payloads),
                            tools,
                            request_max_retries=request_max_retries,
                            session_effort=session_effort,
                            conversation_id=conversation_id,
                            before_attempt=guard,
                            on_stream_open=on_stream_open,
                            **query_kwargs,
                        )
                    ) as stream,
                ):
                    async for response in stream:
                        emitted_chunk = True
                        if not response.is_chunk and response.role != "err":
                            response._codex_image_account = (
                                image_generation.ChatAccount(
                                    self.provider_config.get("id", ""),
                                    source_id,
                                    image_generation.account_identity(snapshot),
                                )
                            )
                        yield response
                return
            except Exception as exc:
                error_kind = oauth.classify_codex_error(exc)
                if error_kind == "usage_limit":
                    cooldown_error = await self._subscription_cooldown_error(snapshot)
                    raise cooldown_error from exc
                if (
                    error_kind == "credential"
                    and retry_after_credential_error
                    and not emitted_chunk
                ):
                    retry_after_credential_error = False
                    coordinator.providers.ensure_enabled(source_id)
                    if budget is not None and budget.remaining <= 0:
                        raise RoutingBudgetError() from None
                    await coordinator.get_snapshot(
                        source_id,
                        force_refresh=True,
                        check_cooldown=False,
                    )
                    continue
                if error_kind == "credential" and not emitted_chunk:
                    coordinator.mark_reauthentication(snapshot)
                    raise ReauthenticationRequiredError(
                        "Sign in to this Provider again.",
                        credential_origin=snapshot.credential_origin,
                    ) from None
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
            reply_language = (
                await messages.resolve_language(runtime.get_context(), session_id)
                if messages.is_auto()
                else None
            )
            raise RuntimeError(
                messages.text("provider.no_response", lang=reply_language)
            )
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
        conversation_id = kwargs.pop("conversation_id", None)
        payloads, _ = await self._prepare_chat_payload(
            prompt,
            image_urls,
            audio_urls,
            astrbot_image_bridge.shape_messages(
                self._ensure_message_to_dicts(contexts), codex=True
            ),
            system_prompt,
            tool_calls_result,
            model=model,
            extra_user_content_parts=extra_user_content_parts,
            **kwargs,
        )
        await image_input.resize_input_images(payloads["input"])
        if (func_tool and not func_tool.empty()) or (
            runtime.native_web_search_enabled() and tool_choice != "auto"
        ):
            payloads["tool_choice"] = tool_choice
        custom_extra_body = self.provider_config.get("custom_extra_body")
        if not (
            isinstance(custom_extra_body, dict)
            and custom_extra_body.get("prompt_cache_key")
        ):
            cache_key = codex_request.prompt_cache_key(session_id, payloads)
            if cache_key:
                payloads.setdefault("prompt_cache_key", cache_key)
        session_effort = await effort.get_session_effort(session_id)
        reply_language = (
            await messages.resolve_language(runtime.get_context(), session_id)
            if messages.is_auto()
            else None
        )
        emitted = False
        try:
            async with aclosing(
                self._stream_with_current_credentials(
                    payloads,
                    func_tool,
                    conversation_id=conversation_id,
                    request_max_retries=request_max_retries,
                    session_effort=session_effort,
                    **(
                        {"reply_language": reply_language}
                        if reply_language is not None
                        else {}
                    ),
                )
            ) as stream:
                async for item in stream:
                    emitted = True
                    yield item
        except Exception as exc:
            if not emitted:
                localized = _localize_provider_error(exc, lang=reply_language)
                if localized is not None:
                    exc.args = (localized,)
                raise
            # AstrBot can fall back after an exception even after a stream chunk.
            # A terminal error response preserves its no-replay branch instead.
            yield LLMResponse(
                role="err",
                completion_text=messages.text(
                    "stream.interrupted", lang=reply_language
                ),
            )
