"""No-network regressions for Codex OAuth native web search and citations."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ASTRBOT_ROOT = Path(os.environ.get("ASTRBOT_ROOT") or PLUGIN_ROOT.parent / "AstrBot")
sys.path[:0] = [str(ASTRBOT_ROOT), str(PLUGIN_ROOT.parent), str(Path(__file__).parent)]
os.chdir(ASTRBOT_ROOT)

import httpx
import source_lifecycle_test as lifecycle_fixtures
from astrbot.core.agent.tool import FunctionTool, ToolSet
from openai import AsyncOpenAI

package = lifecycle_fixtures.runtime.__package__.rsplit(".", 1)[0]
provider_module = lifecycle_fixtures.provider_module
runtime = lifecycle_fixtures.runtime
web_api = lifecycle_fixtures.fixtures.web_api
request_context = lifecycle_fixtures.fixtures.request_context
api_payload = lifecycle_fixtures.fixtures.payload

WEB_SEARCH_TOOL = {"type": "web_search", "external_web_access": True}
DEFAULT_SUCCESS = [
    {"type": "response.output_text.delta", "delta": "ok"},
    {
        "type": "response.completed",
        "response": {"id": "resp-ok", "status": "completed", "output": []},
    },
]


def _make_tool_set(*names: str) -> ToolSet:
    tools = ToolSet()
    for name in names:
        tools.add_tool(
            FunctionTool(
                name=name,
                description=f"Test tool {name}",
                parameters={"type": "object", "properties": {}},
                handler=mock.AsyncMock(return_value="ok"),
            )
        )
    return tools


def _new_provider(
    *,
    native_web_search: bool | None = None,
    custom_extra_body: dict | None = None,
    default_params: tuple[str, ...] = (
        "model",
        "input",
        "store",
        "tools",
        "tool_choice",
    ),
) -> provider_module.ProviderOpenAICodex:
    provider = object.__new__(provider_module.ProviderOpenAICodex)
    config: dict = {}
    if custom_extra_body is not None:
        config["custom_extra_body"] = custom_extra_body
    provider.provider_config = config
    provider.default_params = default_params
    provider._test_native_web_search = native_web_search  # type: ignore[attr-defined]
    return provider


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def _run_query(
        self,
        provider: provider_module.ProviderOpenAICodex,
        events: list[dict],
        *,
        tools: ToolSet | None = None,
        payload: dict | None = None,
    ):
        final_bodies: list[dict] = []

        class EventBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n".encode()

        def handle(request: httpx.Request) -> httpx.Response:
            final_bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                stream=EventBody(),
                headers={"content-type": "text/event-stream"},
            )

        output = []
        async with AsyncOpenAI(
            api_key="test",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as client:
            native_search = bool(getattr(provider, "_test_native_web_search", False))
            with mock.patch.object(
                runtime, "native_web_search_enabled", return_value=native_search
            ):
                async for item in provider._query_stream(
                    client,
                    payload
                    if payload is not None
                    else {"model": "gpt-5.4-mini", "input": []},
                    tools,
                    request_max_retries=1,
                ):
                    output.append(item)
        return final_bodies[0], output

    async def test_request_tools_and_tool_choice_merging(self):
        fn_tools = _make_tool_set("weather", "clock")
        expected_fn_tools = [
            {"type": "function", **item["function"], "strict": False}
            for item in fn_tools.openai_schema()
        ]

        # Default off: no tools or tool_choice added.
        body, _ = await self._run_query(_new_provider(), DEFAULT_SUCCESS)
        self.assertNotIn("tools", body)
        self.assertNotIn("tool_choice", body)

        # Enabled without function tools: injects web_search and auto tool_choice.
        body, _ = await self._run_query(
            _new_provider(native_web_search=True), DEFAULT_SUCCESS
        )
        self.assertEqual(body["tools"], [WEB_SEARCH_TOOL])
        self.assertEqual(body["tool_choice"], "auto")

        # Enabled with multiple function tools: keeps all function tools + web_search.
        body, _ = await self._run_query(
            _new_provider(native_web_search=True), DEFAULT_SUCCESS, tools=fn_tools
        )
        self.assertEqual(body["tools"], [*expected_fn_tools, WEB_SEARCH_TOOL])
        self.assertEqual(body["tool_choice"], "auto")

        # Configured tools override AstrBot functions, including when search is off.
        custom_body = {"tools": expected_fn_tools[:1], "tool_choice": "required"}
        for enabled in (False, True):
            body, _ = await self._run_query(
                _new_provider(native_web_search=enabled, custom_extra_body=custom_body),
                DEFAULT_SUCCESS,
                tools=fn_tools,
            )
            expected = [expected_fn_tools[0]]
            if enabled:
                expected.append(WEB_SEARCH_TOOL)
            self.assertEqual(body["tools"], expected)
            self.assertEqual(body["tool_choice"], "required")

        body, _ = await self._run_query(
            _new_provider(
                native_web_search=True, custom_extra_body={"tools": [WEB_SEARCH_TOOL]}
            ),
            DEFAULT_SUCCESS,
        )
        self.assertEqual(body["tools"], [WEB_SEARCH_TOOL])

        # Custom function tools default to strict=False unless explicitly set.
        strict_custom = {
            "tools": [
                {
                    "type": "function",
                    "name": "loose_fn",
                    "parameters": {"type": "object", "properties": {}},
                },
                {
                    "type": "function",
                    "name": "strict_fn",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": True,
                },
            ]
        }
        body, _ = await self._run_query(
            _new_provider(native_web_search=True, custom_extra_body=strict_custom),
            DEFAULT_SUCCESS,
        )
        self.assertEqual(
            body["tools"],
            [
                {**strict_custom["tools"][0], "strict": False},
                strict_custom["tools"][1],
                WEB_SEARCH_TOOL,
            ],
        )
        self.assertNotIn("strict", strict_custom["tools"][0])

        # Explicit tool_choice via text_chat_stream overrides default auto without breaking default-off.
        captured: list[tuple[dict, object]] = []

        async def capture_stream(payloads, tools, **_kwargs):
            captured.append((payloads, tools))
            yield provider_module.LLMResponse("assistant")

        for enabled, choice, expected_in_payload in (
            (False, "auto", False),
            (True, "auto", False),
            (True, "required", True),
            (True, "none", True),
        ):
            captured.clear()
            p = _new_provider(native_web_search=enabled)
            p._prepare_chat_payload = mock.AsyncMock(
                return_value=({"model": "gpt-5.4-mini", "input": []}, [])
            )
            p._stream_with_current_credentials = capture_stream
            with (
                mock.patch.object(
                    runtime, "native_web_search_enabled", return_value=enabled
                ),
                mock.patch.object(
                    provider_module.effort,
                    "get_session_effort",
                    new=mock.AsyncMock(return_value=None),
                ),
            ):
                _ = [
                    item
                    async for item in p.text_chat_stream(
                        prompt="hi", tool_choice=choice
                    )
                ]
            sent_payload, _ = captured[0]
            if expected_in_payload:
                self.assertEqual(sent_payload.get("tool_choice"), choice)
            else:
                self.assertNotIn("tool_choice", sent_payload)

    async def test_citations_from_output_item_done_sdk_and_dict(self):
        sdk_events = [
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": "ws_1",
                    "type": "web_search_call",
                    "status": "in_progress",
                },
            },
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": "ws_1",
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {"type": "search", "query": "python 3.12"},
                },
            },
            {"type": "response.output_text.delta", "delta": "Answer."},
            {
                "type": "response.output_item.done",
                "output_index": 1,
                "item": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Answer.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "First Title",
                                    "url": "https://example.com/1",
                                    "start_index": 0,
                                    "end_index": 7,
                                },
                                {
                                    "type": "url_citation",
                                    "title": "Duplicate Title",
                                    "url": "https://example.com/1",
                                    "start_index": 0,
                                    "end_index": 7,
                                },
                                {
                                    "type": "url_citation",
                                    "title": "",
                                    "url": "https://example.org/2",
                                    "start_index": 0,
                                    "end_index": 7,
                                },
                            ],
                        }
                    ],
                },
            },
            {
                "type": "response.completed",
                "response": {"id": "resp-done", "status": "completed", "output": []},
            },
        ]

        # Real SDK SSE stream parsing path
        _, sdk_output = await self._run_query(
            _new_provider(native_web_search=True), sdk_events
        )
        self.assertEqual(len(sdk_output), 3)
        self.assertTrue(sdk_output[0].is_chunk)
        self.assertEqual(sdk_output[0].completion_text, "Answer.")
        self.assertTrue(sdk_output[1].is_chunk)
        expected_sources = (
            "来源：\n"
            "1. [First Title](https://example.com/1)\n"
            "2. [https://example.org/2](https://example.org/2)"
        )
        self.assertEqual(sdk_output[1].completion_text, f"\n\n{expected_sources}")
        final = sdk_output[2]
        self.assertFalse(final.is_chunk)
        self.assertEqual(final.tools_call_name, [])
        self.assertEqual(final.tools_call_args, [])
        self.assertEqual(final.tools_call_ids, [])
        self.assertEqual(final.completion_text, f"Answer.\n\n{expected_sources}")

        # Plain dict stream path
        class DictStream:
            async def close(self):
                pass

            def __aiter__(self):
                async def iterate():
                    for event in sdk_events:
                        yield event

                return iterate()

        provider = _new_provider(native_web_search=True)
        dict_output = [
            item async for item in provider._consume_stream(DictStream(), None)
        ]
        self.assertEqual(
            [item.completion_text for item in dict_output],
            [item.completion_text for item in sdk_output],
        )

    async def test_citations_from_completed_output_and_edge_cases(self):
        # Completed response.output directly carries web_search_call, message, and edge annotations
        events = [
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-full",
                    "status": "completed",
                    "output": [
                        {
                            "id": "ws_1",
                            "type": "web_search_call",
                            "status": "completed",
                            "action": {"type": "search", "query": "q"},
                        },
                        {
                            "id": "msg_1",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Summary.",
                                    "annotations": [
                                        {
                                            "type": "url_citation",
                                            "title": "Valid",
                                            "url": "https://a.example/path",
                                            "start_index": 0,
                                            "end_index": 8,
                                        },
                                        {
                                            "type": "url_citation",
                                            "title": "Invalid host",
                                            "url": "https://[invalid",
                                            "start_index": 0,
                                            "end_index": 8,
                                        },
                                        {
                                            "type": "url_citation",
                                            "title": "Missing URL",
                                            "url": "",
                                            "start_index": 0,
                                            "end_index": 8,
                                        },
                                        {
                                            "type": "url_citation",
                                            "title": "Invalid Scheme",
                                            "url": "javascript:alert(1)",
                                            "start_index": 0,
                                            "end_index": 8,
                                        },
                                        {
                                            "type": "file_citation",
                                            "file_id": "file_1",
                                        },
                                    ],
                                }
                            ],
                        },
                    ],
                },
            }
        ]
        _, output = await self._run_query(_new_provider(native_web_search=True), events)
        self.assertEqual(len(output), 1)
        self.assertEqual(
            output[0].completion_text,
            "Summary.\n\n来源：\n1. [Valid](https://a.example/path)",
        )
        self.assertEqual(output[0].tools_call_name, [])

        # No annotations / no valid citations -> no sources block
        no_cite_events = [
            {"type": "response.output_text.delta", "delta": "Plain."},
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Plain."}],
                },
            },
            {
                "type": "response.completed",
                "response": {"id": "resp-plain", "status": "completed", "output": []},
            },
        ]
        _, plain_output = await self._run_query(
            _new_provider(native_web_search=True), no_cite_events
        )
        self.assertEqual(plain_output[-1].completion_text, "Plain.")
        self.assertNotIn("来源：", plain_output[-1].completion_text)

    async def test_web_search_call_with_function_call(self):
        fn_tools = _make_tool_set("lookup")
        events = [
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": "ws_1",
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {"type": "search", "query": "topic"},
                },
            },
            {
                "type": "response.output_item.done",
                "output_index": 1,
                "item": {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"key": "val"}',
                    "status": "completed",
                },
            },
            {
                "type": "response.completed",
                "response": {"id": "resp-tool", "status": "completed", "output": []},
            },
        ]
        _, output = await self._run_query(
            _new_provider(native_web_search=True), events, tools=fn_tools
        )
        final = output[-1]
        self.assertEqual(final.role, "tool")
        self.assertEqual(final.tools_call_name, ["lookup"])
        self.assertEqual(final.tools_call_args, [{"key": "val"}])
        self.assertEqual(final.tools_call_ids, ["call_1"])


class WebSearchConfigIntegrationTests(unittest.IsolatedAsyncioTestCase):
    setUp = lifecycle_fixtures.SourceLifecycleTests.setUp
    asyncTearDown = lifecycle_fixtures.SourceLifecycleTests.asyncTearDown
    sync = lifecycle_fixtures.SourceLifecycleTests.sync

    async def test_plugin_view_toggle_persists_and_controls_requests(self):
        schema_data = json.loads((PLUGIN_ROOT / "_conf_schema.json").read_text("utf-8"))
        self.assertNotIn("native_web_search", schema_data)

        await self.registry.migrate()
        provider_schema = self.service.get_provider_schema()
        self.assertNotIn(
            "native_web_search", provider_schema["config_schema"]["provider"]["items"]
        )
        self.assertNotIn("native_web_search", provider_schema["providers"][0])

        saved_model = self.conf["provider"][0]
        await self.manager.reload(saved_model)
        loaded = self.manager.inst_map[saved_model["id"]]
        self.assertIsInstance(loaded, provider_module.ProviderOpenAICodex)

        with (
            mock.patch.object(runtime, "_config_mgr", self.coordinator.config_manager),
            mock.patch.object(runtime, "_credential_coordinator", self.coordinator),
            mock.patch.object(runtime, "_startup_error", None),
        ):
            with request_context():
                listed = api_payload(await web_api._handle_providers_list())
            self.assertEqual(listed["settings"], {"native_web_search": False})
            self.assertFalse(runtime.native_web_search_enabled())

            for bad_body in ({}, {"native_web_search": "yes"}, {"other": True}):
                with request_context(bad_body):
                    bad = await web_api._handle_settings_update()
                self.assertEqual(bad.status_code, 400)

            seen_bodies: list[dict] = []

            async def respond(request: httpx.Request) -> httpx.Response:
                seen_bodies.append(json.loads(request.content))
                events = [
                    {
                        "type": "response.output_item.done",
                        "output_index": 0,
                        "item": {
                            "id": "ws_1",
                            "type": "web_search_call",
                            "status": "completed",
                            "action": {"type": "search", "query": "latest"},
                        },
                    },
                    {"type": "response.output_text.delta", "delta": "Latest result."},
                    {
                        "type": "response.output_item.done",
                        "output_index": 1,
                        "item": {
                            "id": "msg_1",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Latest result.",
                                    "annotations": [
                                        {
                                            "type": "url_citation",
                                            "title": "Official",
                                            "url": "https://official.example",
                                            "start_index": 0,
                                            "end_index": 14,
                                        }
                                    ],
                                }
                            ],
                        },
                    },
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp-e2e",
                            "status": "completed",
                            "output": [],
                        },
                    },
                ]
                return httpx.Response(
                    200,
                    text="".join(f"data: {json.dumps(e)}\n\n" for e in events),
                    headers={"content-type": "text/event-stream"},
                )

            loaded._create_http_client = lambda _cfg: httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            )
            await loaded.text_chat(prompt="Disabled check")
            self.assertNotIn("tools", seen_bodies[0])

            with request_context({"native_web_search": True}):
                updated = api_payload(await web_api._handle_settings_update())
            self.assertEqual(updated["settings"], {"native_web_search": True})
            self.assertTrue(runtime.native_web_search_enabled())

            # Survives a stale source snapshot save in AstrBot's provider source editor.
            stale = dict(self.registry.gateway())
            stale.pop("oauth_routing", None)
            await self.service.upsert_provider_source("OpenAI Subscribe", stale)
            self.assertTrue(runtime.native_web_search_enabled())

            reply = await loaded.text_chat(prompt="What is latest?")
            self.assertEqual(seen_bodies[1]["tools"], [WEB_SEARCH_TOOL])
            self.assertEqual(seen_bodies[1]["tool_choice"], "auto")
            self.assertEqual(
                reply.completion_text,
                "Latest result.\n\n来源：\n1. [Official](https://official.example)",
            )

    async def test_auto_language_follows_context_get_locale_for_citations_and_interrupted_stream(
        self,
    ):
        await self.registry.migrate()
        saved_model = self.conf["provider"][0]
        await self.manager.reload(saved_model)
        loaded = self.manager.inst_map[saved_model["id"]]
        self.assertIsInstance(loaded, provider_module.ProviderOpenAICodex)

        events = [
            {
                "type": "response.output_text.delta",
                "delta": "Latest result.",
            },
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Latest result.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "Official",
                                    "url": "https://official.example",
                                    "start_index": 0,
                                    "end_index": 14,
                                }
                            ],
                        }
                    ],
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-en",
                    "status": "completed",
                    "output": [],
                },
            },
        ]

        class _LocaleContext:
            async def get_locale(self, umo: str | None = None) -> str:
                return "en-US" if umo == "webchat:en" else "zh-CN"

        def ok_transport(_cfg):
            return httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _req: httpx.Response(
                        200,
                        text="".join(f"data: {json.dumps(e)}\n\n" for e in events),
                        headers={"content-type": "text/event-stream"},
                    )
                )
            )

        loaded._create_http_client = ok_transport
        try:
            provider_module.messages.set_language(
                provider_module.messages.AUTO_LANGUAGE
            )
            with (
                mock.patch.object(
                    runtime, "_config_mgr", self.coordinator.config_manager
                ),
                mock.patch.object(runtime, "_credential_coordinator", self.coordinator),
                mock.patch.object(runtime, "_startup_error", None),
                mock.patch.object(runtime, "_context", _LocaleContext()),
            ):
                en_reply = await loaded.text_chat(prompt="Hi", session_id="webchat:en")
                self.assertEqual(
                    en_reply.completion_text,
                    "Latest result.\n\nSources:\n1. [Official](https://official.example)",
                )
                self.assertEqual(provider_module.messages.language(), "zh-CN")

                zh_chunks = [
                    chunk.completion_text
                    async for chunk in loaded.text_chat_stream(
                        prompt="Hi", session_id="webchat:zh"
                    )
                    if chunk.is_chunk
                ]
                self.assertEqual(
                    "".join(zh_chunks),
                    "Latest result.\n\n来源：\n1. [Official](https://official.example)",
                )

                class _BrokenStreamBody(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        yield (
                            f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': 'Partial'})}\n\n"
                        ).encode()
                        raise httpx.ReadError("connection dropped")

                await loaded._transport_pool.close()
                loaded._create_http_client = lambda _cfg: httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda _req: httpx.Response(
                            200,
                            stream=_BrokenStreamBody(),
                            headers={"content-type": "text/event-stream"},
                        )
                    )
                )
                chunks = [
                    chunk
                    async for chunk in loaded.text_chat_stream(
                        prompt="Hi", session_id="webchat:en"
                    )
                ]
                self.assertEqual(chunks[-1].role, "err")
                self.assertEqual(
                    chunks[-1].completion_text,
                    provider_module.messages.text("stream.interrupted", lang="en-US"),
                )
                self.assertEqual(provider_module.messages.language(), "zh-CN")
        finally:
            provider_module.messages.set_language("zh-CN")

    async def test_pre_stream_credential_errors_are_localized_with_metadata_intact(
        self,
    ):
        await self.registry.migrate()
        saved_model = self.conf["provider"][0]
        await self.manager.reload(saved_model)
        loaded = self.manager.inst_map[saved_model["id"]]
        self.assertIsInstance(loaded, provider_module.ProviderOpenAICodex)

        class _LocaleContext:
            async def get_locale(self, umo: str | None = None) -> str:
                return "en-US" if umo == "webchat:en" else "zh-CN"

        store = lifecycle_fixtures.fixtures.store
        routing = provider_module.RoutingExhaustedError
        cases = [
            (
                store.ProviderDisabledError("disabled"),
                store.ProviderDisabledError,
                "disabled",
                "已停用",
            ),
            (
                store.ReauthenticationRequiredError("Sign in to this Provider again."),
                store.ReauthenticationRequiredError,
                "sign in again",
                "重新登录",
            ),
            (
                store.CredentialCooldownError(1_900_000_000, "usage_limit_reached"),
                store.CredentialCooldownError,
                "cooling down",
                "冷却中",
            ),
            (
                routing([("local", "cooling")], "startup_timeout"),
                routing,
                "timed out",
                "自动回退超时",
            ),
        ]

        try:
            provider_module.messages.set_language(
                provider_module.messages.AUTO_LANGUAGE
            )
            with (
                mock.patch.object(
                    runtime, "_config_mgr", self.coordinator.config_manager
                ),
                mock.patch.object(runtime, "_credential_coordinator", self.coordinator),
                mock.patch.object(runtime, "_startup_error", None),
                mock.patch.object(runtime, "_context", _LocaleContext()),
            ):
                for err, expected_cls, en_fragment, zh_fragment in cases:
                    with mock.patch.object(
                        loaded, "_stream_with_current_credentials", side_effect=err
                    ):
                        with self.assertRaises(expected_cls) as en_caught:
                            async for _ in loaded.text_chat_stream(
                                prompt="Hi", session_id="webchat:en"
                            ):
                                pass
                        self.assertIn(en_fragment, str(en_caught.exception).lower())
                        self.assertEqual(en_caught.exception.code, err.code)

                    with mock.patch.object(
                        loaded, "_stream_with_current_credentials", side_effect=err
                    ):
                        with self.assertRaises(expected_cls) as zh_caught:
                            async for _ in loaded.text_chat_stream(
                                prompt="Hi", session_id="webchat:zh"
                            ):
                                pass
                        self.assertIn(zh_fragment, str(zh_caught.exception))

                # Non-credential errors keep their original message unchanged.
                with mock.patch.object(
                    loaded,
                    "_stream_with_current_credentials",
                    side_effect=RuntimeError("raw upstream error"),
                ):
                    with self.assertRaises(RuntimeError) as raw_caught:
                        async for _ in loaded.text_chat_stream(
                            prompt="Hi", session_id="webchat:en"
                        ):
                            pass
                    self.assertEqual(str(raw_caught.exception), "raw upstream error")
        finally:
            provider_module.messages.set_language("zh-CN")


if __name__ == "__main__":
    unittest.main()
