"""Codex provider adapter, response streaming, retries, and source routing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing, asynccontextmanager
from copy import deepcopy
from typing import Any

import astrbot.core.message.components as Comp
from astrbot import logger
from astrbot.api.event import MessageChain
from astrbot.core.exceptions import EmptyModelOutputError
from astrbot.core.provider.entities import LLMResponse, TokenUsage
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

from . import effort, oauth, runtime
from . import usage as usage_service
from .credential_store import (
    CredentialCooldownError,
    CredentialError,
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
from .provider_routing import (
    ROUTING_TIMEOUT_SECONDS,
    SOURCE_ATTEMPTS,
    RequestBudget,
    RoutingBudgetError,
    RoutingExhaustedError,
)

# The ChatGPT backend rejects sampling knobs, output limits and explicit cache
# options that the public Responses API accepts. Codex never sends them.
_UNSUPPORTED_REQUEST_PARAMS = (
    "max_output_tokens",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "user",
    "safety_identifier",
    "prompt_cache_options",
)
# Codex's Fast mode sends "priority" and Ultrafast sends "ultrafast".
_SUPPORTED_SERVICE_TIERS = frozenset({"priority", "ultrafast"})
# Call IDs from other providers can exceed the backend's 64-character limit.
_CALL_ID_LIMIT = 64
_reported_unsupported_params: set[str] = set()


def _bound_call_id(call_id: Any) -> Any:
    """Shorten an oversized call ID the same way on every request."""
    if not isinstance(call_id, str) or len(call_id) <= _CALL_ID_LIMIT:
        return call_id
    return hashlib.sha256(call_id.strip().encode()).hexdigest()


def _drop_unsupported_params(*bodies: dict[str, Any]) -> None:
    dropped: set[str] = set()
    for body in bodies:
        for key in _UNSUPPORTED_REQUEST_PARAMS:
            if key in body:
                body.pop(key)
                dropped.add(key)
        tier = body.get("service_tier")
        if tier is not None and tier not in _SUPPORTED_SERVICE_TIERS:
            body.pop("service_tier")
            dropped.add("service_tier")
    new = dropped - _reported_unsupported_params
    if new:
        _reported_unsupported_params.update(new)
        logger.warning(
            "OpenAI Codex ignores request parameters it does not support: %s",
            ", ".join(sorted(new)),
        )


class _PooledTransport:
    __slots__ = ("client", "fingerprint", "retired", "users")

    def __init__(self, fingerprint: tuple[str, str], client: Any) -> None:
        self.fingerprint = fingerprint
        self.client = client
        self.users = 0
        self.retired = False


class _TransportPool:
    """Reuse one HTTP transport per account source between requests.

    Reusing a transport keeps its TCP and TLS connections alive. Each source
    gets its own transport, so cookies set for one account never travel with
    another. A transport is replaced when its account or proxy changes and is
    closed once the requests still using it finish.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _PooledTransport] = {}

    @property
    def clients(self) -> list[Any]:
        return [entry.client for entry in self._entries.values()]

    @asynccontextmanager
    async def lease(
        self,
        source_id: str,
        fingerprint: tuple[str, str],
        create: Callable[[], Any],
    ):
        entry = self._entries.get(source_id)
        if entry is None or entry.fingerprint != fingerprint or entry.client.is_closed:
            if entry is not None:
                await self._retire(entry)
            entry = _PooledTransport(fingerprint, create())
            self._entries[source_id] = entry
        entry.users += 1
        try:
            yield entry.client
        finally:
            entry.users -= 1
            if entry.retired and entry.users == 0:
                await entry.client.aclose()

    async def _retire(self, entry: _PooledTransport) -> None:
        entry.retired = True
        if entry.users == 0:
            await entry.client.aclose()

    async def close(self) -> None:
        entries = list(self._entries.values())
        self._entries.clear()
        for entry in entries:
            entry.retired = True
            await entry.client.aclose()


def _register_provider_adapter_if_absent(cls: type) -> type:
    """Register the provider once and refresh its class on plugin reload.

    AstrBot keeps ``provider_cls_map`` when a plugin module is reloaded. Avoiding
    duplicate registration is necessary, but the metadata must still point to the
    newly imported class or provider instances will continue using stale code.
    """
    if runtime.PROVIDER_TYPE not in provider_cls_map:
        return register_provider_adapter(
            runtime.PROVIDER_TYPE,
            "OpenAI 订阅登录 (Codex OAuth) Provider",
            provider_display_name="OpenAI Subscribe",
            default_config_tmpl=runtime._default_provider_template(),
        )(cls)
    provider_cls_map[runtime.PROVIDER_TYPE].cls_type = cls
    return cls


@_register_provider_adapter_if_absent
class ProviderOpenAICodex(ProviderOpenAIResponses):
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
        self._originator = str(provider_config.get("originator", DEFAULT_ORIGINATOR))
        self._user_agent = oauth.resolve_user_agent(provider_config.get("user_agent"))
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

    @property
    def _transport_pool(self) -> _TransportPool:
        pool = self.__dict__.get("_transports")
        if pool is None:
            pool = self.__dict__["_transports"] = _TransportPool()
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

    def _request_client(
        self,
        snapshot: CredentialSnapshot,
        *,
        headers: dict[str, str] | None = None,
        http_client: Any = None,
    ) -> Any:
        headers = dict(self._static_headers if headers is None else headers)
        if snapshot.account_id:
            headers["chatgpt-account-id"] = snapshot.account_id
        return self.client.with_options(
            # The plugin owns retries, cooldowns and the cross-provider budget.
            max_retries=0,
            api_key=snapshot.access_token,
            set_default_headers=headers,
            **({"http_client": http_client} if http_client is not None else {}),
        )

    @asynccontextmanager
    async def _source_client(self, snapshot: CredentialSnapshot):
        """Build a request client on the selected source's own transport."""
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
            # The SDK wrapper shares the pooled transport; closing it would not
            # close the transport, so it is left to the garbage collector.
            yield self._request_client(
                snapshot,
                headers=headers,
                http_client=transport,
            )

    @staticmethod
    def _prompt_cache_key(session_id: Any, payloads: dict[str, Any]) -> str | None:
        """Name the conversation so the backend reuses its cached prompt prefix.

        Codex sends its thread ID. An AstrBot session is the closest stable
        equivalent and survives context truncation; without one, the start of
        the conversation (instructions and input up to the first user message),
        which every later turn repeats, identifies it. Only a hash is sent.
        """
        digest = hashlib.sha256()
        if isinstance(session_id, str) and session_id:
            digest.update(b"astrbot-session\0")
            digest.update(session_id.encode())
            digest.update(b"\0")
            digest.update(str(payloads.get("model", "")).encode())
        else:
            digest.update(str(payloads.get("instructions", "")).encode())
            found_user = False
            for item in payloads.get("input") or []:
                digest.update(
                    json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
                )
                if isinstance(item, dict) and item.get("role") == "user":
                    found_user = True
                    break
            if not found_user:
                return None
        value = digest.hexdigest()
        return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:32]}"

    def _convert_chat_messages_to_response_input(
        self, messages: list[dict]
    ) -> list[dict]:
        """Shape replayed history for a backend that stores nothing.

        Stored item IDs and message statuses refer to state the backend never
        kept, and a reasoning item can only be replayed with its encrypted
        content. The backend also rejects role "system" in input; "developer"
        carries the same meaning.
        """
        shaped: list[dict] = []
        for item in super()._convert_chat_messages_to_response_input(messages):
            item_type = item.get("type")
            if item_type == "reasoning" and not item.get("encrypted_content"):
                continue
            item.pop("id", None)
            if item_type in {None, "message", "reasoning"}:
                item.pop("status", None)
            if "call_id" in item:
                item["call_id"] = _bound_call_id(item["call_id"])
            if item_type in {None, "message"} and item.get("role") == "system":
                item["role"] = "developer"
            shaped.append(item)
        return shaped

    async def _query_stream(
        self,
        request_client: Any,
        payloads: dict,
        tools,
        *,
        request_max_retries: int | None = None,
        session_effort: str | None = None,
        before_attempt: Callable[[], None] | None = None,
        on_stream_open: Callable[[], None] | None = None,
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

        _drop_unsupported_params(payloads, extra_body)
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
        self._request_reasoning_state(payloads, extra_body)
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
        session_headers = (
            {"session-id": cache_key, "thread-id": cache_key}
            if isinstance(cache_key, str) and cache_key
            else {}
        )

        max_attempts = coerce_int_config(
            request_max_retries,
            default=REQUEST_RETRY_ATTEMPTS,
            min_value=1,
            field_name="request_max_retries",
            source="OpenAI Codex",
            warn=request_max_retries is not None,
        )
        attempts = 0
        emitted_response = False

        async def create_stream():
            nonlocal attempts
            if before_attempt is not None:
                before_attempt()
            attempts += 1
            return await request_client.responses.create(
                **payloads,
                stream=True,
                extra_body=extra_body,
                **({"extra_headers": session_headers} if session_headers else {}),
            )

        while attempts < max_attempts:
            # Creation and stream iteration share one request-attempt budget.
            stream = await retry_provider_request(
                "OpenAI Responses",
                create_stream,
                retry_rate_limits=False,
                max_attempts=max_attempts - attempts,
            )
            if on_stream_open is not None:
                on_stream_open()
            try:
                async for response in self._consume_stream(stream, tools):
                    emitted_response = True
                    yield response
                return
            except Exception as exc:
                if (
                    emitted_response
                    or attempts >= max_attempts
                    or oauth.classify_codex_error(exc) != "temporary"
                ):
                    raise
            finally:
                await stream.close()

            delay = min(2 ** min(attempts - 1, 5), REQUEST_RETRY_WAIT_MAX_S)
            logger.warning(
                "OpenAI Codex stream failed before output; retrying (%s/%s) in %ss.",
                attempts + 1,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

    @staticmethod
    def _request_reasoning_state(
        payloads: dict[str, Any], extra_body: dict[str, Any]
    ) -> None:
        """Ask for reasoning the way Codex does, unless reasoning is off.

        With ``store`` disabled, the encrypted reasoning content is the only
        way to carry reasoning into the next turn or tool call. A summary lets
        the reasoning stream instead of arriving silently.
        """
        reasoning = extra_body.get("reasoning")
        if not isinstance(reasoning, dict):
            reasoning = payloads.pop("reasoning", None)
            reasoning = dict(reasoning) if isinstance(reasoning, dict) else {}
        if reasoning.get("effort") == "none":
            if reasoning:
                extra_body["reasoning"] = reasoning
            return
        reasoning.setdefault("summary", "auto")
        extra_body["reasoning"] = reasoning
        include = extra_body.get("include", payloads.pop("include", None))
        include = list(include) if isinstance(include, (list, tuple)) else []
        if "reasoning.encrypted_content" not in include:
            include.append("reasoning.encrypted_content")
        extra_body["include"] = include

    @staticmethod
    def _response_with_output(
        response: Any, response_id: str | None, items: dict[int, Any]
    ) -> dict[str, Any]:
        """Give a terminal response the output items its stream delivered.

        Codex completes with an empty ``output`` list; the items arrive in
        ``response.output_item.done`` events instead.
        """

        def field(name: str) -> Any:
            if isinstance(response, dict):
                return response.get(name)
            return getattr(response, name, None)

        return {
            "id": field("id") or response_id,
            "status": field("status"),
            "incomplete_details": field("incomplete_details"),
            "usage": field("usage"),
            "output": [items[index] for index in sorted(items)],
        }

    async def _consume_stream(
        self, stream: Any, tools: Any
    ) -> AsyncGenerator[LLMResponse, None]:
        """Keep partial response state scoped to a single stream attempt."""
        response_id: str | None = None
        text_parts: list[str] = []
        # Deltas are fragments of one text; a new item or summary part starts
        # a new segment, matching how complete responses separate them.
        reasoning_parts: list[str] = []
        reasoning_segment: tuple[Any, Any, Any] | None = None
        function_calls: list[dict] = []
        output_items: dict[int, Any] = {}

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
                    segment = (
                        self._field(event, "item_id"),
                        self._field(event, "summary_index"),
                        self._field(event, "content_index"),
                    )
                    if not reasoning_parts or segment != reasoning_segment:
                        reasoning_parts.append("")
                        reasoning_segment = segment
                    reasoning_parts[-1] += str(delta)
                    yield LLMResponse(
                        "assistant",
                        reasoning_content=str(delta),
                        is_chunk=True,
                        id=response_id,
                    )
                continue

            if event_type == "response.output_item.done":
                item = self._field(event, "item")
                if item is not None:
                    index = self._field(event, "output_index")
                    if isinstance(index, bool) or not isinstance(index, int):
                        index = max(output_items, default=-1) + 1
                    output_items[index] = item
                continue

            if event_type == "response.output_item.added":
                item = self._field(event, "item")
                if self._field(item, "type") == "function_call":
                    arguments = self._field(item, "arguments", "")
                    if isinstance(arguments, dict):
                        arguments = json.dumps(arguments, ensure_ascii=False)
                    function_calls.append(
                        {
                            "item_id": self._field(item, "id"),
                            "call_id": str(self._field(item, "call_id", "") or ""),
                            "name": str(self._field(item, "name", "") or ""),
                            "arguments": str(arguments or ""),
                        }
                    )
                continue

            if event_type == "response.function_call_arguments.delta":
                # Parallel calls stream their arguments by item ID.
                item_id = self._field(event, "item_id")
                call = next(
                    (c for c in function_calls if item_id and c["item_id"] == item_id),
                    function_calls[-1] if function_calls else None,
                )
                if call is not None:
                    call["arguments"] += str(self._field(event, "delta", "") or "")
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
                    if output_items:
                        try:
                            parsed = await self._parse_response(
                                self._response_with_output(
                                    event_response, response_id, output_items
                                ),
                                tools,
                            )
                        except EmptyModelOutputError:
                            parsed = None
                        if parsed is not None:
                            yield parsed
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
            logger.error("OpenAI Codex model catalog failed: %s", type(exc).__name__)
        return list(CODEX_FALLBACK_MODELS)

    async def _fetch_usage_for_snapshot(
        self,
        snapshot: CredentialSnapshot,
    ) -> dict[str, Any]:
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
            max_attempts=2,
        )

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
                self._fetch_usage_for_snapshot,
            )
            cooldown_until = usage_service.cooldown_until_from_usage(usage)
        except Exception as exc:  # noqa: BLE001 - a failed usage lookup is non-fatal
            logger.warning(
                "OpenAI Codex quota lookup after rate limit failed: %s",
                type(exc).__name__,
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
        session_effort: str | None = None,
    ) -> AsyncGenerator[LLMResponse, None]:
        coordinator = runtime.get_coordinator()
        candidates = coordinator.providers.candidates(self._source_id)
        automatic = coordinator.providers.routing_mode(self._source_id) == "auto"
        if not automatic:
            async with aclosing(
                self._stream_from_source(
                    self._source_id,
                    payloads,
                    tools,
                    request_max_retries=request_max_retries,
                    session_effort=session_effort,
                )
            ) as stream:
                async for response in stream:
                    yield response
            return

        budget = RequestBudget(
            coerce_int_config(
                request_max_retries,
                default=REQUEST_RETRY_ATTEMPTS,
                min_value=1,
                field_name="request_max_retries",
                source="OpenAI Codex",
                warn=request_max_retries is not None,
            )
        )
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
        session_effort: str | None = None,
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
            try:
                async with (
                    self._source_client(snapshot) as request_client,
                    aclosing(
                        self._query_stream(
                            request_client,
                            deepcopy(base_payloads),
                            tools,
                            request_max_retries=request_max_retries,
                            session_effort=session_effort,
                            before_attempt=guard,
                            on_stream_open=on_stream_open,
                        )
                    ) as stream,
                ):
                    async for response in stream:
                        emitted_chunk = True
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
                        "Sign in to this Provider again."
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
        custom_extra_body = self.provider_config.get("custom_extra_body")
        if not (
            isinstance(custom_extra_body, dict)
            and custom_extra_body.get("prompt_cache_key")
        ):
            cache_key = self._prompt_cache_key(session_id, payloads)
            if cache_key:
                payloads.setdefault("prompt_cache_key", cache_key)
        session_effort = await effort.get_session_effort(session_id)
        emitted = False
        try:
            async with aclosing(
                self._stream_with_current_credentials(
                    payloads,
                    func_tool,
                    request_max_retries=request_max_retries,
                    session_effort=session_effort,
                )
            ) as stream:
                async for item in stream:
                    emitted = True
                    yield item
        except Exception:
            if not emitted:
                raise
            # AstrBot can fall back after an exception even after a stream chunk.
            # A terminal error response preserves its no-replay branch instead.
            yield LLMResponse(
                role="err",
                completion_text="The response was interrupted after output; it was not replayed.",
            )
