"""No-network provider wiring tests for OpenAI OAuth credential isolation."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

module = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
oauth = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.oauth")
store = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.credential_store"
)
ProviderOpenAICodex = module.ProviderOpenAICodex

FAILED: list[str] = []
ACCESS_TOKEN = "sk-ant-oat01-aaaa.bbbb.cccc"
REFRESH_TOKEN = "rt-fake-refresh-token"
ACCOUNT_ID = "user-12345"


def check(condition: bool, message: str) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        FAILED.append(message)


class _FakeConfig(dict):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.saved = 0

    async def save_config_async(self) -> bool:
        self.saved += 1
        return True


class _FakeConfigManager:
    def __init__(self, conf: _FakeConfig) -> None:
        self.default_conf = conf


def credentials(*, expires: int = 9999999999) -> dict:
    return {
        "access_token": ACCESS_TOKEN,
        "refresh_token": REFRESH_TOKEN,
        "expires": expires,
        "account_id": ACCOUNT_ID,
    }


def make_source(creds: dict) -> dict:
    return {
        "id": module._PROVIDER_TYPE,
        "type": module._PROVIDER_TYPE,
        "provider": "openai",
        "provider_type": "chat_completion",
        "key": json.dumps(creds),
        "proxy": "",
        "originator": oauth.DEFAULT_ORIGINATOR,
        "user_agent": oauth.DEFAULT_USER_AGENT,
        "enable": True,
    }


def make_config(creds: dict, **overrides) -> dict:
    config = {
        "type": module._PROVIDER_TYPE,
        "provider_source_id": module._PROVIDER_TYPE,
        "key": json.dumps(creds),
        "model": "gpt-5.4-mini",
        "proxy": "",
        "originator": oauth.DEFAULT_ORIGINATOR,
        "user_agent": oauth.DEFAULT_USER_AGENT,
    }
    config.update(overrides)
    return config


def test_provider_initialization_and_request_client() -> None:
    print("=== Provider initialization and request isolation ===")
    provider = ProviderOpenAICodex(make_config(credentials()), {})
    check(
        provider.provider_config["api_base"] == oauth.CODEX_BASE,
        "api_base points at the Codex backend",
    )
    check(
        str(provider.client.base_url).rstrip("/") == oauth.CODEX_BASE,
        "root client uses CODEX_BASE",
    )
    check(
        provider.client.api_key != ACCESS_TOKEN,
        "root client does not retain the OAuth access token",
    )
    root_token = provider.client.api_key
    root_headers = provider.client.default_headers or {}
    check(
        root_headers.get("chatgpt-account-id") is None,
        "root client does not retain a mutable account header",
    )
    check(
        root_headers.get("originator") == oauth.DEFAULT_ORIGINATOR,
        "static originator is set",
    )
    check("OpenAI-Beta" in root_headers, "static Responses beta header is set")

    snapshot = store.CredentialSnapshot(
        source_id=module._PROVIDER_TYPE,
        access_token="sk-ant-oat01-new.new.new",
        refresh_token="rt-new",
        expires=9999999999,
        account_id="user-new",
        cooldown_until=None,
        cooldown_reason=None,
    )
    request_client = provider._request_client(snapshot)
    request_headers = request_client.default_headers or {}
    check(
        request_client.api_key == snapshot.access_token,
        "derived request client has the snapshot token",
    )
    check(
        request_headers.get("chatgpt-account-id") == snapshot.account_id,
        "derived request client has the snapshot account header",
    )
    check(
        provider.client.api_key == root_token,
        "derived client leaves root token unchanged",
    )
    check(
        (provider.client.default_headers or {}).get("chatgpt-account-id") is None,
        "derived client leaves root account header unchanged",
    )

    provider.set_key("sk-ant-oat01-updated.updated.updated")
    check(
        provider.get_current_key() == "sk-ant-oat01-updated.updated.updated",
        "set_key updates provider bootstrap metadata",
    )
    check(
        provider.client.api_key == root_token,
        "set_key does not mutate root client",
    )


def test_hot_reload_and_offline_models() -> None:
    print("\n=== Hot reload and offline models ===")
    metadata = module.provider_cls_map[module._PROVIDER_TYPE]
    original = metadata.cls_type

    class _StaleProvider:
        pass

    metadata.cls_type = _StaleProvider
    try:
        returned = module._register_provider_adapter_if_absent(ProviderOpenAICodex)
        check(returned is ProviderOpenAICodex, "hot reload returns the new class")
        check(
            metadata.cls_type is ProviderOpenAICodex, "hot reload replaces stale class"
        )
    finally:
        metadata.cls_type = original

    old_manager = module._config_mgr
    module._config_mgr = None
    try:
        provider = ProviderOpenAICodex(make_config({"refresh_token": "rt-only"}), {})
        models = asyncio.run(provider.get_models())
    finally:
        module._config_mgr = old_manager
    check(
        models == list(oauth.CODEX_FALLBACK_MODELS),
        "missing credentials use offline models",
    )


def test_payload_conversion_and_stream_usage() -> None:
    print("\n=== Responses payload conversion and stream usage ===")
    provider = ProviderOpenAICodex(make_config(credentials()), {})
    items = provider._convert_chat_messages_to_response_input(
        [
            {"role": "system", "content": "You are an assistant."},
            {"role": "user", "content": "hi"},
        ]
    )
    check(
        [item.get("role") for item in items if item.get("type") == "message"]
        == ["developer", "user"],
        "system messages become developer messages",
    )

    class _FakeStream:
        def __init__(self, events: list[dict]) -> None:
            self.events = events

        def __aiter__(self):
            async def iterate():
                for event in self.events:
                    yield event

            return iterate()

    class _RequestClient:
        def __init__(self, stream) -> None:
            self.responses = SimpleNamespace(create=mock.AsyncMock(return_value=stream))

    stream = _FakeStream(
        [
            {"type": "response.output_text.delta", "delta": "hello"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-usage",
                    "status": "completed",
                    "output": [],
                    "usage": {
                        "input_tokens": 123,
                        "input_tokens_details": {"cached_tokens": 23},
                        "output_tokens": 45,
                    },
                },
            },
        ]
    )
    request_client = _RequestClient(stream)
    retry_options: dict = {}

    async def retry(_label, factory, **kwargs):
        retry_options.update(kwargs)
        return await factory()

    async def collect():
        with mock.patch.object(module, "retry_provider_request", new=retry):
            return [
                response
                async for response in provider._query_stream(
                    request_client,
                    {"model": "gpt-5.4-mini", "input": []},
                    None,
                    request_max_retries=1,
                )
            ]

    responses = asyncio.run(collect())
    final = responses[-1]
    check(final.usage.input_other == 100, "stream preserves uncached input usage")
    check(final.usage.input_cached == 23, "stream preserves cached input usage")
    check(final.usage.output == 45, "stream preserves output usage")
    check(retry_options.get("retry_rate_limits") is False, "429 retries are disabled")


def test_session_effort_request_override() -> None:
    print("\n=== Session reasoning-effort request override ===")

    class _FakeStream:
        def __aiter__(self):
            async def iterate():
                yield {"type": "response.output_text.delta", "delta": "ok"}
                yield {
                    "type": "response.completed",
                    "response": {
                        "id": "resp-effort",
                        "status": "completed",
                        "output": [],
                    },
                }

            return iterate()

    class _RequestClient:
        def __init__(self) -> None:
            self.responses = SimpleNamespace(
                create=mock.AsyncMock(return_value=_FakeStream())
            )

    async def collect(provider, session_effort: str | None) -> dict:
        request_client = _RequestClient()

        async def retry(_label, factory, **_kwargs):
            return await factory()

        with mock.patch.object(module, "retry_provider_request", new=retry):
            _ = [
                item
                async for item in provider._query_stream(
                    request_client,
                    {"model": "gpt-5.4-mini", "input": []},
                    None,
                    request_max_retries=1,
                    session_effort=session_effort,
                )
            ]
        return request_client.responses.create.call_args.kwargs["extra_body"]

    provider = ProviderOpenAICodex(
        make_config(
            credentials(),
            custom_extra_body={
                "reasoning_effort": "low",
                "reasoning": {"summary": "auto"},
            },
        ),
        {},
    )
    overridden = asyncio.run(collect(provider, "max"))
    check(
        overridden.get("reasoning") == {"summary": "auto", "effort": "max"},
        "session effort overrides only the effective request effort",
    )
    check(
        "reasoning_effort" not in overridden,
        "session override removes the competing request-level shorthand",
    )
    check(
        provider.provider_config["custom_extra_body"]
        == {
            "reasoning_effort": "low",
            "reasoning": {"summary": "auto"},
        },
        "session override does not mutate model configuration",
    )

    default_provider = ProviderOpenAICodex(
        make_config(
            credentials(),
            custom_extra_body={"reasoning_effort": "high"},
        ),
        {},
    )
    default_body = asyncio.run(collect(default_provider, None))
    check(
        default_body.get("reasoning") == {"effort": "high"},
        "requests without a session override keep model-level mapping",
    )

    fake_sp = SimpleNamespace(
        get_async=mock.AsyncMock(side_effect=["low", "max", "invalid"])
    )

    async def read_session_overrides() -> tuple[str | None, str | None, str | None]:
        with mock.patch.object(module, "sp", fake_sp):
            return (
                await module._get_session_effort("umo-a"),
                await module._get_session_effort("umo-b"),
                await module._get_session_effort("umo-c"),
            )

    session_values = asyncio.run(read_session_overrides())
    check(
        session_values == ("low", "max", None),
        "session storage validates and isolates effort values",
    )
    scope_ids = [call.kwargs["scope_id"] for call in fake_sp.get_async.await_args_list]
    check(scope_ids == ["umo-a", "umo-b", "umo-c"], "effort lookup uses each UMO")

    captured_efforts: list[str | None] = []

    async def stream_with_captured_effort(
        _payloads,
        _tools,
        *,
        request_max_retries,
        session_effort=None,
    ):
        captured_efforts.append(session_effort)
        yield module.LLMResponse(
            "assistant",
            result_chain=module.MessageChain().message("ok"),
        )

    provider._stream_with_current_credentials = stream_with_captured_effort
    request_sp = SimpleNamespace(get_async=mock.AsyncMock(side_effect=["low", "max"]))

    async def run_provider_sessions() -> None:
        with mock.patch.object(module, "sp", request_sp):
            _ = [
                item
                async for item in provider.text_chat_stream(
                    prompt="first",
                    session_id="umo-a",
                )
            ]
            _ = [
                item
                async for item in provider.text_chat_stream(
                    prompt="second",
                    session_id="umo-b",
                )
            ]

    asyncio.run(run_provider_sessions())
    check(
        captured_efforts == ["low", "max"],
        "text_chat_stream forwards each UMO effort to its own request",
    )


def _provider_with_source(creds: dict) -> tuple[ProviderOpenAICodex, _FakeConfig]:
    conf = _FakeConfig({"provider_sources": [make_source(creds)]})
    module._config_mgr = _FakeConfigManager(conf)
    return ProviderOpenAICodex(make_config(creds), {}), conf


def test_pre_stream_credential_recovery() -> None:
    print("\n=== Pre-stream credential recovery ===")
    provider, conf = _provider_with_source(credentials())
    calls = 0

    class _UnauthorizedError(RuntimeError):
        status_code = 401

    async def query(
        _client, _payloads, _tools, *, request_max_retries, session_effort=None
    ):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _UnauthorizedError()
        yield module.LLMResponse(
            "assistant", result_chain=module.MessageChain().message("ok")
        )

    async def refresh(creds: dict, proxy: str | None) -> dict:
        return {
            **creds,
            "access_token": "sk-ant-oat01-refreshed.refreshed.refreshed",
            "refresh_token": "rt-refreshed",
            "expires": 9999999999,
        }

    provider._query_stream = query

    async def run():
        with mock.patch.object(module, "refresh_access_token", new=refresh):
            return [
                response
                async for response in provider._stream_with_current_credentials(
                    {"model": "gpt-5.4-mini", "input": []},
                    None,
                    request_max_retries=1,
                )
            ]

    responses = asyncio.run(run())
    stored = json.loads(conf["provider_sources"][0]["key"])
    check(calls == 2, "a pre-stream 401 is retried once after refresh")
    check(bool(responses), "retry produces a response")
    check(
        stored["access_token"] == "sk-ant-oat01-refreshed.refreshed.refreshed",
        "forced refresh persists the recovered token",
    )


def test_stream_is_not_replayed_after_output() -> None:
    print("\n=== Stream output is never replayed ===")
    provider, _ = _provider_with_source(credentials())
    calls = 0

    class _UnauthorizedError(RuntimeError):
        status_code = 401

    async def query(
        _client, _payloads, _tools, *, request_max_retries, session_effort=None
    ):
        nonlocal calls
        calls += 1
        yield module.LLMResponse(
            "assistant",
            result_chain=module.MessageChain().message("partial"),
            is_chunk=True,
        )
        raise _UnauthorizedError()

    provider._query_stream = query

    async def run() -> list:
        responses = []
        try:
            async for response in provider._stream_with_current_credentials(
                {"model": "gpt-5.4-mini", "input": []},
                None,
                request_max_retries=1,
            ):
                responses.append(response)
        except _UnauthorizedError:
            return responses
        raise AssertionError("expected stream error")

    responses = asyncio.run(run())
    check(calls == 1, "a stream with output is not replayed")
    check(len(responses) == 1 and responses[0].is_chunk, "partial output is retained")


def test_usage_limit_enters_cooldown() -> None:
    print("\n=== Subscription quota enters cooldown ===")
    provider, conf = _provider_with_source(credentials())

    class _UsageLimitError(RuntimeError):
        status_code = 429

        def __init__(self) -> None:
            self.body = {"error": {"code": "usage_limit_reached"}}

    async def query(
        _client, _payloads, _tools, *, request_max_retries, session_effort=None
    ):
        raise _UsageLimitError()
        yield

    async def usage(*_args):
        return {
            "allowed": False,
            "limit_reached": True,
            "windows": [
                {
                    "reset_at": 9999999999,
                    "reset_after_seconds": None,
                    "used_percent": 100,
                }
            ],
        }

    provider._query_stream = query

    async def run():
        with mock.patch.object(module, "fetch_rate_limits", new=usage):
            try:
                async for _ in provider._stream_with_current_credentials(
                    {"model": "gpt-5.4-mini", "input": []},
                    None,
                    request_max_retries=1,
                ):
                    pass
            except store.CredentialCooldownError as exc:
                return exc
        raise AssertionError("expected cooldown")

    error = asyncio.run(run())
    durable = json.loads(conf["provider_sources"][0]["key"])
    check(error.cooldown_until == 9999999999, "cooldown uses usage reset time")
    check(durable["cooldown_reason"] == "usage_limit_reached", "cooldown is persisted")


def main() -> int:
    old_manager = module._config_mgr
    try:
        test_provider_initialization_and_request_client()
        test_hot_reload_and_offline_models()
        test_payload_conversion_and_stream_usage()
        test_session_effort_request_override()
        test_pre_stream_credential_recovery()
        test_stream_is_not_replayed_after_output()
        test_usage_limit_enters_cooldown()
    finally:
        module._config_mgr = old_manager
    print()
    if FAILED:
        print(f"=== Provider wiring failed: {len(FAILED)} assertion(s) ===")
        for failure in FAILED:
            print(f"  - {failure}")
        return 1
    print("=== Provider wiring passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
