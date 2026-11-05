"""No-network provider wiring tests for OpenAI OAuth credential isolation."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from base64 import b64decode, b64encode
from contextlib import ExitStack
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = os.path.abspath(
    os.environ.get("ASTRBOT_ROOT")
    or os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

module = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
effort = importlib.import_module(f"{module.__package__}.src.effort")
oauth = importlib.import_module(f"{module.__package__}.src.oauth")
provider_module = importlib.import_module(f"{module.__package__}.src.provider")
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.star import Context
from astrbot.core import astr_main_agent
from astrbot.core.message.components import Image as ImageComponent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.provider.entities import LLMResponse
from PIL import Image

image_bridge = importlib.import_module(f"{module.__package__}.src.astrbot_image_bridge")
image_input = importlib.import_module(f"{module.__package__}.src.image_input")
runtime = importlib.import_module(f"{module.__package__}.src.runtime")
store = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.src.credential_store"
)
ProviderOpenAICodex = module.ProviderOpenAICodex

FAILED: list[str] = []
ACCESS_TOKEN = "test-jwt-aaaa.bbbb.cccc"
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
        "id": runtime.PROVIDER_TYPE,
        "type": runtime.PROVIDER_TYPE,
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
        "type": runtime.PROVIDER_TYPE,
        "provider_source_id": runtime.PROVIDER_TYPE,
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
        source_id=runtime.PROVIDER_TYPE,
        access_token="test-jwt-new.new.new",
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

    provider.set_key("test-jwt-updated.updated.updated")
    check(
        provider.get_current_key() == "test-jwt-updated.updated.updated",
        "set_key updates provider bootstrap metadata",
    )
    check(
        provider.client.api_key == root_token,
        "set_key does not mutate root client",
    )


def test_hot_reload_and_offline_models() -> None:
    print("\n=== Hot reload and offline models ===")
    metadata = provider_module.provider_cls_map[runtime.PROVIDER_TYPE]
    original = metadata.cls_type

    class _StaleProvider:
        pass

    metadata.cls_type = _StaleProvider
    try:
        returned = provider_module._register_subscription_adapter(ProviderOpenAICodex)
        check(returned is ProviderOpenAICodex, "hot reload returns the new class")
        check(
            metadata.cls_type is ProviderOpenAICodex, "hot reload replaces stale class"
        )
    finally:
        metadata.cls_type = original

    old_manager = runtime._config_mgr
    runtime._config_mgr = None
    try:
        provider = ProviderOpenAICodex(make_config({"refresh_token": "rt-only"}), {})
        models = asyncio.run(provider.get_models())
    finally:
        runtime._config_mgr = old_manager
    check(
        models == list(oauth.CODEX_FALLBACK_MODELS),
        "missing credentials use offline models",
    )


def test_source_model_listing_preserves_credentials() -> None:
    print("\n=== Dashboard source model listing preserves credentials ===")
    source = make_source(credentials())
    source["id"] = "independent-source"
    source["custom_headers"] = {"X-Test": "preserved"}
    original = deepcopy(source)
    conf = _FakeConfig(provider_sources=[source])
    manager = _FakeConfigManager(conf)
    live_models = ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna"]
    fetch = mock.AsyncMock(return_value=live_models)

    async def run() -> None:
        with (
            mock.patch.object(runtime, "_config_mgr", manager),
            mock.patch.object(runtime, "_credential_coordinator", None),
            mock.patch.object(oauth, "fetch_models", fetch),
        ):
            # The dashboard passes the actual shared source to the constructor.
            for _ in range(2):
                provider = ProviderOpenAICodex(source, {})
                try:
                    models = await provider.get_models()
                    check(models == live_models, "source listing returns live models")
                    check(source == original, "source configuration stays unchanged")
                finally:
                    await provider.terminate()

    asyncio.run(run())
    check(fetch.await_count == 2, "each source listing reaches the live catalog")
    check(
        fetch.await_args_list
        == [
            mock.call(
                ACCESS_TOKEN,
                ACCOUNT_ID,
                "",
                oauth.DEFAULT_ORIGINATOR,
                oauth.DEFAULT_USER_AGENT,
            )
        ]
        * 2,
        "repeated listings keep the original OAuth credentials",
    )
    check(conf.saved == 0, "model listing does not persist configuration changes")


def test_input_image_resize() -> None:
    print("\n=== Codex input image resizing ===")
    provider = ProviderOpenAICodex(make_config(credentials()), {})

    def data_url(fmt: str, size: tuple[int, int], mime: str) -> str:
        with Image.new("RGB", size, "red") as image, BytesIO() as output:
            image.save(output, format=fmt)
            encoded = b64encode(output.getvalue()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def image_part(url: str, **options) -> dict:
        return {"type": "image_url", "image_url": {"url": url, **options}}

    jpeg = data_url("JPEG", (320, 4096), "image/jpeg")
    gif = data_url("GIF", (4096, 320), "image/gif")
    small_gif = data_url("GIF", (2048, 320), "image/gif")
    oversized_original = data_url("PNG", (8000, 400), "image/png")
    contexts = [
        {
            "role": "user",
            "content": [
                image_part(jpeg, detail="high"),
                image_part(jpeg, detail="original"),
                image_part(gif, detail="auto"),
                image_part(small_gif),
                image_part(oversized_original, detail="original"),
            ],
        },
    ]
    original_contexts = deepcopy(contexts)
    dispatched = []

    async def capture(payloads, *_args, **_kwargs):
        dispatched.extend(payloads["input"])
        yield SimpleNamespace(is_chunk=False)

    async def run(path: Path) -> None:
        with mock.patch.object(provider, "_stream_with_current_credentials", capture):
            async for _ in provider.text_chat_stream(
                prompt="Describe these images.",
                image_urls=[str(path)],
                contexts=contexts,
            ):
                pass

    with TemporaryDirectory() as tmpdir:
        screenshot = Path(tmpdir) / "screenshot.png"
        with Image.new("RGBA", (4096, 1024), (255, 0, 0, 128)) as image:
            image.save(screenshot)
        asyncio.run(run(screenshot))
        with Image.open(screenshot) as image:
            check(image.size == (4096, 1024), "the local attachment is untouched")

    parts = [
        part
        for message in dispatched
        for part in message["content"]
        if part["type"] == "input_image"
    ]
    check(
        [part["detail"] for part in parts]
        == ["high", "original", "auto", "auto", "original", "auto"],
        "original detail survives conversion even when the same image has two modes",
    )
    check(contexts == original_contexts, "resizing does not change stored history")
    check(
        parts[1]["image_url"] == jpeg, "a JPEG within its original limit is identical"
    )
    check(
        parts[3]["image_url"] == small_gif,
        "a GIF exactly at its dimension limit is identical",
    )

    def inspect(part: dict) -> tuple:
        header, encoded = part["image_url"].split(",", 1)
        with Image.open(BytesIO(b64decode(encoded))) as image:
            return header, image.format, image.size

    for index, mime, fmt, size in [
        (0, "image/jpeg", "JPEG", (160, 2048)),
        (2, "image/png", "PNG", (2048, 160)),
        (4, "image/png", "PNG", (6000, 300)),
        (5, "image/png", "PNG", (2048, 512)),
    ]:
        check(
            inspect(parts[index]) == (f"data:{mime};base64", fmt, size),
            f"{fmt} input {index} is sent at {size} with the correct MIME type",
        )

    with (
        Image.open(
            BytesIO(b64decode(parts[0]["image_url"].split(",", 1)[1]))
        ) as resized,
        Image.new("RGB", (1, 1)) as reference,
        BytesIO() as output,
    ):
        reference.save(output, format="JPEG", quality=85)
        output.seek(0)
        with Image.open(output) as encoded_reference:
            check(
                resized.quantization == encoded_reference.quantization,
                "the resized JPEG uses quality 85 quantization tables",
            )


def test_group_chat_image_resize() -> None:
    print("\n=== Group chat images through the AstrBot agent ===")
    provider = ProviderOpenAICodex(make_config(credentials(), modalities=["image"]), {})

    async def run(screenshot: Path, small_gif: Path, bitmap: Path) -> None:
        msg = AstrBotMessage()
        msg.type = MessageType.GROUP_MESSAGE
        msg.group_id = "image-test"
        msg.sender = MessageMember(user_id="user")
        msg.self_id = "bot"
        msg.message = [
            ImageComponent.fromFileSystem(screenshot),
            ImageComponent.fromFileSystem(small_gif),
            ImageComponent.fromFileSystem(bitmap),
        ]
        msg.message_str = "Read the screenshot."
        event = AstrMessageEvent(
            msg.message_str,
            msg,
            PlatformMetadata(name="test", id="test", description="test"),
            "image-test",
        )
        original_url = "data:image/png;base64," + b64encode(
            screenshot.read_bytes()
        ).decode("ascii")
        history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": original_url, "detail": "original"},
                    }
                ],
            }
        ]
        context = mock.MagicMock(spec=Context)
        context.get_config.return_value = {}
        context.subagent_orchestrator = None
        context.conversation_manager = mock.MagicMock()
        context.conversation_manager.get_curr_conversation_id = mock.AsyncMock(
            return_value="conv"
        )
        context.conversation_manager.get_conversation = mock.AsyncMock(
            return_value=SimpleNamespace(
                cid="conv", history=json.dumps(history), persona_id=None
            )
        )
        dispatched = []

        async def capture(payloads, *_args, **_kwargs):
            dispatched.extend(payloads["input"])
            yield LLMResponse(role="assistant", completion_text="Read")

        config = astr_main_agent.MainAgentBuildConfig(
            tool_call_timeout=60,
            add_cron_tools=False,
            llm_safety_mode=False,
            provider_settings={"image_compress_options": {"max_size": 1280}},
        )
        with ExitStack() as stack:
            if hasattr(astr_main_agent, "builder"):
                builder = astr_main_agent.builder
                stack.enter_context(
                    mock.patch.object(
                        builder.persona, "apply_persona", mock.AsyncMock()
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        builder.knowledge_base, "apply_knowledge_base", mock.AsyncMock()
                    )
                )
            else:
                for name in ("_decorate_llm_request", "_apply_kb"):
                    stack.enter_context(
                        mock.patch.object(astr_main_agent, name, mock.AsyncMock())
                    )
            stack.callback(event.cleanup_temporary_local_files)
            stack.callback(image_bridge.install(runtime.PROVIDER_TYPE))
            stack.enter_context(
                mock.patch.object(provider, "_stream_with_current_credentials", capture)
            )
            result = await astr_main_agent.build_main_agent(
                event=event, plugin_context=context, config=config, provider=provider
            )
            assert result is not None
            check(
                str(screenshot) not in result.provider_request.image_urls,
                "AstrBot created a preview before runner reset",
            )
            saved_message = result.agent_runner.run_context.messages[-1].model_dump()
            saved_screenshot = next(
                part["image_url"]["url"]
                for part in saved_message["content"]
                if part["type"] == "image_url"
            )
            with Image.open(
                BytesIO(b64decode(saved_screenshot.split(",", 1)[1]))
            ) as image:
                check(
                    image.format == "JPEG" and image.size == (1280, 320),
                    "shared history retains AstrBot's preview for other providers",
                )
            async for _ in result.agent_runner._iter_llm_responses():
                pass

        parts = [
            part
            for item in dispatched
            if isinstance(item.get("content"), list)
            for part in item["content"]
            if part["type"] == "input_image"
        ]
        check(parts[0]["detail"] == "original", "original survives typed history")
        with Image.open(
            BytesIO(b64decode(parts[0]["image_url"].split(",", 1)[1]))
        ) as image:
            check(
                image.size == (6000, 1500),
                "typed history uses the 6000 px original limit",
            )
        header, encoded = parts[1]["image_url"].split(",", 1)
        with Image.open(BytesIO(b64decode(encoded))) as image:
            check(
                header == "data:image/png;base64"
                and image.format == "PNG"
                and image.size == (2048, 512),
                "the group screenshot follows Codex sizing and retains PNG",
            )
        check(
            b64decode(parts[2]["image_url"].split(",", 1)[1]) == small_gif.read_bytes(),
            "the group GIF under the limit keeps its original bytes",
        )
        check(
            parts[3]["image_url"].startswith("data:image/jpeg;base64,"),
            "the agent retains the compatible preview for an unsupported bitmap",
        )
        check(
            all(
                "frame montage" not in part.get("text", "")
                for item in dispatched
                if isinstance(item.get("content"), list)
                for part in item["content"]
            ),
            "the request does not describe the original GIF as a preview montage",
        )

    with TemporaryDirectory() as tmpdir:
        screenshot = Path(tmpdir) / "screenshot.png"
        small_gif = Path(tmpdir) / "small.gif"
        bitmap = Path(tmpdir) / "bitmap.bmp"
        with Image.new("RGB", (6400, 1600), "red") as image:
            image.save(screenshot)
        with (
            Image.new("RGB", (64, 32), "blue") as first_frame,
            Image.new("RGB", (64, 32), "green") as second_frame,
        ):
            first_frame.save(
                small_gif, save_all=True, append_images=[second_frame], duration=200
            )
        with Image.new("RGB", (1500, 20), "blue") as image:
            image.save(bitmap)
        asyncio.run(run(screenshot, small_gif, bitmap))


def test_16_bit_png_resize() -> None:
    print("\n=== 16-bit PNG resizing ===")
    for transparency in (None, 1000):
        width = 8192
        row = (1000).to_bytes(2, "little") * (width // 2)
        row += (3000).to_bytes(2, "little") * (width // 2)
        with (
            Image.frombytes("I;16", (width, 64), row * 64) as source,
            BytesIO() as output,
        ):
            source.save(output, "PNG", transparency=transparency)
            encoded = b64encode(output.getvalue()).decode("ascii")
        url = image_input._resize_data_url(f"data:image/png;base64,{encoded}", 2048)
        assert url is not None
        with Image.open(BytesIO(b64decode(url.split(",", 1)[1]))) as image:
            check(
                image.format == "PNG"
                and image.mode == "I;16"
                and image.size == (2048, 16)
                and image.getpixel((10, 4)) == 1000
                and image.getpixel((2038, 4)) == 3000
                and image.info.get("transparency") == transparency,
                f"16-bit PNG preserves sample values and transparency {transparency}",
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

        async def close(self) -> None:
            pass

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
        with mock.patch.object(provider_module, "retry_provider_request", new=retry):
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
        async def close(self) -> None:
            pass

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

        with mock.patch.object(provider_module, "retry_provider_request", new=retry):
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
        default_body.get("reasoning") == {"effort": "high", "summary": "auto"}
        and default_body.get("include") == ["reasoning.encrypted_content"],
        "requests without a session override keep model-level mapping",
    )

    fake_sp = SimpleNamespace(
        get_async=mock.AsyncMock(side_effect=["low", "max", "invalid"])
    )

    async def read_session_overrides() -> tuple[str | None, str | None, str | None]:
        with mock.patch.object(effort, "sp", fake_sp):
            return (
                await effort.get_session_effort("umo-a"),
                await effort.get_session_effort("umo-b"),
                await effort.get_session_effort("umo-c"),
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
        yield provider_module.LLMResponse(
            "assistant",
            result_chain=MessageChain().message("ok"),
        )

    provider._stream_with_current_credentials = stream_with_captured_effort
    request_sp = SimpleNamespace(get_async=mock.AsyncMock(side_effect=["low", "max"]))

    async def run_provider_sessions() -> None:
        with mock.patch.object(effort, "sp", request_sp):
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
    runtime._config_mgr = _FakeConfigManager(conf)
    return ProviderOpenAICodex(make_config(creds), {}), conf


def test_pre_stream_credential_recovery() -> None:
    print("\n=== Pre-stream credential recovery ===")
    provider, conf = _provider_with_source(credentials())
    calls = 0

    class _UnauthorizedError(RuntimeError):
        status_code = 401

    async def query(
        _client,
        _payloads,
        _tools,
        *,
        request_max_retries,
        session_effort=None,
        before_attempt=None,
        on_stream_open=None,
    ):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _UnauthorizedError()
        yield provider_module.LLMResponse(
            "assistant", result_chain=MessageChain().message("ok")
        )

    async def refresh(creds: dict, proxy: str | None) -> dict:
        return {
            **creds,
            "access_token": "test-jwt-refreshed.refreshed.refreshed",
            "refresh_token": "rt-refreshed",
            "expires": 9999999999,
        }

    provider._query_stream = query

    async def run():
        with mock.patch.object(oauth, "refresh_access_token", new=refresh):
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
        stored["access_token"] == "test-jwt-refreshed.refreshed.refreshed",
        "forced refresh persists the recovered token",
    )


def test_stream_is_not_replayed_after_output() -> None:
    print("\n=== Stream output is never replayed ===")
    provider, _ = _provider_with_source(credentials())
    calls = 0

    class _UnauthorizedError(RuntimeError):
        status_code = 401

    async def query(
        _client,
        _payloads,
        _tools,
        *,
        request_max_retries,
        session_effort=None,
        before_attempt=None,
        on_stream_open=None,
    ):
        nonlocal calls
        calls += 1
        yield provider_module.LLMResponse(
            "assistant",
            result_chain=MessageChain().message("partial"),
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
        _client,
        _payloads,
        _tools,
        *,
        request_max_retries,
        session_effort=None,
        before_attempt=None,
        on_stream_open=None,
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
        with mock.patch.object(oauth, "fetch_rate_limits", new=usage):
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
    old_manager = runtime._config_mgr
    try:
        test_provider_initialization_and_request_client()
        test_hot_reload_and_offline_models()
        test_source_model_listing_preserves_credentials()
        test_input_image_resize()
        test_group_chat_image_resize()
        test_16_bit_png_resize()
        test_payload_conversion_and_stream_usage()
        test_session_effort_request_override()
        test_pre_stream_credential_recovery()
        test_stream_is_not_replayed_after_output()
        test_usage_limit_enters_cooldown()
    finally:
        runtime._config_mgr = old_manager
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
