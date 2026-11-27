"""No-network regressions for Codex OAuth native web search and citations."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from collections.abc import AsyncIterable
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ASTRBOT_ROOT = Path(os.environ.get("ASTRBOT_ROOT") or PLUGIN_ROOT.parent / "AstrBot")
sys.path[:0] = [str(ASTRBOT_ROOT), str(PLUGIN_ROOT.parent), str(Path(__file__).parent)]
os.chdir(ASTRBOT_ROOT)

import httpx
import source_lifecycle_test as lifecycle_fixtures
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.platform.sources.webchat.webchat_queue_mgr import webchat_queue_mgr
from astrbot.dashboard.services import chat_service
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
        events: list[dict] | AsyncIterable[dict],
        *,
        tools: ToolSet | None = None,
        payload: dict | None = None,
        reply_language: str | None = None,
    ):
        final_bodies: list[dict] = []

        async def event_stream():
            if isinstance(events, list):
                for event in events:
                    yield event
            else:
                async for event in events:
                    yield event

        class EventBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                async for event in event_stream():
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
                    reply_language=reply_language,
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

    async def test_bot_citations_follow_part_offsets_and_reuse_source_numbers(self):
        bridge = provider_module.bot_citations
        url = "https://example.org/article"
        other = "https://example.org/data"
        ordinary = f"🔎[全文]({url})。"
        first = ordinary + "发布。"
        second = "发布。更多。"

        def part(text, refs):
            return {
                "type": "output_text",
                "text": text,
                "annotations": [
                    {
                        "type": "url_citation",
                        "url": target,
                        "title": title,
                        "start_index": 0,
                        "end_index": end,
                    }
                    for end, target, title in refs
                ],
            }

        events = [
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "delta": first,
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                part(
                                    first,
                                    [
                                        (ordinary.index("]"), url, "Article"),
                                        (len(first), url, "Article"),
                                    ],
                                ),
                                part(
                                    second,
                                    [(3, url, "Article"), (len(second), other, "Data")],
                                ),
                            ],
                        }
                    ],
                },
            },
        ]
        for platform in ("telegram", "slack", "aiocqhttp", "line"):
            with self.subTest(platform=platform):
                extras = {}
                event = mock.Mock()
                event.get_platform_name.return_value = platform
                event.get_extra.side_effect = extras.get
                event.set_extra.side_effect = extras.__setitem__
                event.send = mock.AsyncMock()
                token = bridge.event_context.set(event)
                try:
                    _, output = await self._run_query(
                        _new_provider(native_web_search=True),
                        events,
                        reply_language="en",
                    )
                finally:
                    bridge.event_context.reset(token)
                if platform == "telegram":
                    one, two = f"[〔1〕]({url})", f"[〔2〕]({other})"
                elif platform == "slack":
                    one, two = f"<{url}|〔1〕>", f"<{other}|〔2〕>"
                else:
                    one, two = "〔1〕", "〔2〕"
                expected = f"{ordinary[:-1]}{one}。发布。{one}发布。{one}更多。{two}"
                card = platform == "line" and hasattr(bridge.Comp, "ActionRow")
                if platform in {"line", "aiocqhttp"} and not card:
                    expected += f"\n\nSources:\n〔1〕 Article {url}\n〔2〕 Data {other}"
                self.assertEqual(output[-1].completion_text, expected)
                self.assertEqual(
                    [item.completion_text for item in output if item.is_chunk],
                    [expected],
                )
                if card:
                    event.send.side_effect = [RuntimeError("card rejected"), None]
                    result = bridge.MessageEventResult().message(expected)
                    result.result_content_type = bridge.ResultContentType.LLM_RESULT
                    event.get_result.return_value = result
                    await bridge.deliver_card(event, after_send=False)
                    event.send.assert_not_awaited()
                    await bridge.deliver_card(event, after_send=True)
                    await bridge.deliver_card(event, after_send=True)
                    native, fallback = [
                        call.args[0] for call in event.send.await_args_list
                    ]
                    self.assertEqual(
                        [(b.label, b.action.url) for b in native.chain[0].buttons],
                        [("〔1〕 Article", url), ("〔2〕 Data", other)],
                    )
                    self.assertEqual(
                        fallback.get_plain_text(),
                        f"Sources:\n〔1〕 Article {url}\n〔2〕 Data {other}",
                    )

    async def test_inline_citations_in_live_and_saved_chat(self):
        from astrbot.core.db.po import PlatformMessageHistory

        url = "https://www.example.com/article_(2026)?utm_source=openai"
        ordinary = f"查看[原文]({url})，也可浏览 [example.com]({url})。"
        visible = ordinary + "🔎第一条。"
        sentence = visible + f"([example.com]({url}))"
        second = sentence + "更多。"
        annotation = {
            "type": "url_citation",
            "url": url,
            "title": "Article",
            "start_index": 0,
            "end_index": len(sentence) - 1,
        }
        run = chat_service.ChatRunState(
            "run", "user", "session", "turn", "webchat", asyncio.Queue()
        )
        work = {"type": "think", "think": "Checking the source."}
        prelude = [{"type": "plain", "text": sentence}, work]
        run.message_parts = prelude
        service = object.__new__(chat_service.ChatService)
        service.chat_runs = {run.run_id: run}
        subscriber = asyncio.Queue()
        run.subscribers.add(subscriber)
        bridge = runtime.chatui_citations
        state = bridge._CitationRun(service, run)
        tag = "<ref>codex-1</ref>"

        async def events():
            yield {
                "type": "response.output_text.delta",
                "delta": sentence[:-1],
                "output_index": 1,
                "content_index": 0,
            }
            event = {
                "type": "response.output_text.annotation.added",
                "annotation": annotation,
                "output_index": 1,
                "content_index": 0,
            }
            yield event
            yield event
            # Annotation arrived before WebChat consumed the text frame.
            _, snapshot = subscriber.get_nowait()
            self.assertEqual(snapshot["data"]["content"]["message"], prelude)
            self.assertTrue(subscriber.empty())
            run.message_parts = [*prelude, {"type": "plain", "text": sentence[:-1]}]
            state._publish_chat_run(run, {"type": "plain", "data": sentence[:-1]})
            self.assertEqual(subscriber.get_nowait()[1]["type"], "plain")
            _, snapshot = subscriber.get_nowait()
            self.assertEqual(
                snapshot["data"]["content"]["message"][-1]["text"], visible + "(" + tag
            )
            yield {
                "type": "response.output_text.delta",
                "delta": ")",
                "output_index": 1,
                "content_index": 0,
            }
            run.message_parts = [*prelude, {"type": "plain", "text": sentence}]
            state._publish_chat_run(run, {"type": "plain", "data": ")"})
            self.assertEqual(subscriber.get_nowait()[1]["type"], "plain")
            _, snapshot = subscriber.get_nowait()
            self.assertEqual(
                snapshot["data"]["content"]["message"][-1]["text"], visible + tag
            )

            yield {
                "type": "response.output_text.delta",
                "delta": second,
                "output_index": 1,
                "content_index": 1,
            }
            item = {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": text, "annotations": [annotation]}
                    for text in (sentence, second)
                ],
            }
            yield {"type": "response.output_item.done", "item": item, "output_index": 1}
            yield DEFAULT_SUCCESS[-1]

        token = bridge._producer.set(state)
        try:
            _, output = await self._run_query(
                _new_provider(native_web_search=True), events()
            )
        finally:
            bridge._producer.reset(token)

        body = sentence + second
        raw = [*prelude, {"type": "plain", "text": body}]
        run.message_parts = raw
        state._publish_chat_run(run, {"type": "plain", "data": second})
        expected = [
            *prelude,
            {"type": "plain", "text": visible + tag + visible + tag + "更多。"},
        ]
        snapshot = service.get_active_chat_runs("user", "session")[0]["content"]
        self.assertEqual(snapshot["message"], expected)
        self.assertEqual(
            snapshot["refs"]["used"],
            [{"index": "codex-1", "title": "Article", "url": annotation["url"]}],
        )
        service.save_bot_message = mock.AsyncMock()
        await state.save_bot_message("session", raw, {}, {})
        saved = service.save_bot_message.await_args.args
        record = PlatformMessageHistory(
            platform_id="webchat",
            user_id="session",
            content={"type": "bot", "message": saved[1], "refs": saved[3]},
        )
        self.assertIn(
            f"([example.com]({url}){tag})", record.content["message"][-1]["text"]
        )
        uninstall = bridge.install()
        try:
            reopened = chat_service.serialize_history_entry(record)["content"]
        finally:
            uninstall()
        self.assertEqual(
            (reopened["message"], reopened["refs"]), (expected, snapshot["refs"])
        )
        self.assertEqual(
            "".join(item.completion_text for item in output if item.is_chunk), body
        )
        self.assertEqual(output[-1].completion_text, body)

    def test_only_adjacent_links_to_the_cited_url_are_collapsed(self):
        bridge = runtime.chatui_citations
        url = "https://example.com/news?q=1#today"
        refs = [{"index": "codex-1", "url": url}]
        tag = "<ref>codex-1</ref>"
        for fragment, expected in (
            (f"（[{url}]({url}){tag}）", tag),
            (f"(<{url}>){tag}", tag),
            (f"{tag} ({url})", tag),
            (f"[原文]({url}){tag}", f"[原文]({url}){tag}"),
            (f"[example.com]({url}2){tag}", f"[example.com]({url}2){tag}"),
        ):
            with self.subTest(fragment=fragment):
                shown = bridge._display_parts(
                    [{"type": "plain", "text": fragment}], refs
                )
                self.assertEqual(shown[0]["text"], expected)

    async def test_reload_during_active_chat_restores_hooks(self):
        from astrbot.core.agent.runners.tool_loop_agent_runner import (
            ToolLoopAgentRunner,
        )

        started, finish = asyncio.Event(), asyncio.Event()

        async def consume(service, run):
            started.set()
            await finish.wait()

        stream_name = (
            "_recorded_responses"
            if hasattr(ToolLoopAgentRunner, "_recorded_responses")
            else "_iter_llm_responses"
        )
        original_stream = getattr(ToolLoopAgentRunner, stream_name)
        original_extract = chat_service.extract_web_search_refs
        with mock.patch.object(chat_service.ChatService, "_consume_chat_run", consume):
            uninstall = runtime.chatui_citations.install()
            task = asyncio.create_task(
                chat_service.ChatService._consume_chat_run(
                    None, mock.Mock(run_id="run")
                )
            )
            await started.wait()
            uninstall()
            uninstall = runtime.chatui_citations.install()
            try:
                finish.set()
                await task
            finally:
                uninstall()
            self.assertIs(chat_service.ChatService._consume_chat_run, consume)
            self.assertIs(getattr(ToolLoopAgentRunner, stream_name), original_stream)
            self.assertIs(chat_service.extract_web_search_refs, original_extract)

    async def test_native_search_cards_stream_and_persist_in_chatui(self):
        run_id = "native-search-test"
        queue = webchat_queue_mgr.get_or_create_back_queue(run_id)
        run = chat_service.ChatRunState(
            run_id, "user", "session", "turn", "webchat", queue
        )
        service = object.__new__(chat_service.ChatService)
        service.chat_runs = {run_id: run}
        service.chat_runs_by_session = {run.session_id: {run_id}}
        service.running_convs = {}
        service.save_bot_message = mock.AsyncMock(return_value=None)
        subscriber = asyncio.Queue()
        run.subscribers.add(subscriber)
        bridge = runtime.chatui_citations
        state = bridge._CitationRun(service, run)
        continue_answer = asyncio.Event()
        search_item = {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {"type": "search", "queries": ["OpenAI news", "官方公告"]},
        }
        find_item = {
            "type": "web_search_call",
            "id": "ws_2",
            "status": "completed",
            "action": {
                "type": "find_in_page",
                "url": "https://example.org",
                "pattern": "Responses API",
            },
        }

        async def events():
            yield {"type": "response.web_search_call.searching", "item_id": "ws_1"}
            yield {"type": "response.web_search_call.completed", "item_id": "ws_1"}
            yield {
                "type": "response.output_item.done",
                "item": search_item,
                "output_index": 0,
            }
            await continue_answer.wait()
            yield {"type": "response.web_search_call.searching", "item_id": "ws_3"}
            yield {
                "type": "response.completed",
                "response": {
                    "id": "resp-search",
                    "status": "completed",
                    "output": [
                        search_item,
                        find_item,
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "ok"}],
                        },
                    ],
                },
            }

        consumer = asyncio.create_task(
            chat_service.ChatService._consume_chat_run(state, run)
        )
        token = bridge._producer.set(state)
        try:
            producer = asyncio.create_task(
                self._run_query(
                    _new_provider(native_web_search=True),
                    events(),
                    reply_language="zh-CN",
                )
            )
        finally:
            bridge._producer.reset(token)

        async def next_card():
            _, frame = await asyncio.wait_for(subscriber.get(), 5)
            self.assertEqual(frame["chain_type"], "tool_call")
            return json.loads(frame["data"])

        try:
            running = await next_card()
            self.assertEqual(running["name"], "OpenAI web_search · 搜索中")
            completed = await next_card()
            self.assertEqual(completed["name"], "OpenAI web_search · 搜索完成")
            self.assertGreaterEqual(completed["finished_ts"], running["ts"])
            details = await next_card()
            self.assertEqual(details["id"], running["id"])
            self.assertEqual(
                details["args"]["queries"], search_item["action"]["queries"]
            )
            self.assertEqual(details["finished_ts"], completed["finished_ts"])
            snapshot = service.get_active_chat_runs(run.username, run.session_id)[0]
            self.assertEqual(snapshot["content"]["message"][0]["tool_calls"], [details])
            continue_answer.set()
            _, output = await asyncio.wait_for(producer, 5)
            self.assertEqual(output[-1].tools_call_name, [])
            await queue.put({"type": "end", "message_id": run_id})
            await asyncio.wait_for(consumer, 5)
        finally:
            for task in (producer, consumer):
                task.cancel()
            await asyncio.gather(producer, consumer, return_exceptions=True)
            webchat_queue_mgr.remove_back_queue(run_id)

        parts = service.save_bot_message.await_args.args[1]
        cards = {call["id"]: call for part in parts for call in part["tool_calls"]}
        self.assertEqual(len(parts), 3)
        self.assertEqual(cards[details["id"]]["args"], details["args"])
        fallback = cards["codex-web-search:ws_2"]
        self.assertEqual(
            fallback["args"],
            {
                "action": "find_in_page",
                "url": "https://example.org",
                "pattern": "Responses API",
            },
        )
        self.assertEqual(fallback["name"], "OpenAI web_search · 搜索完成")
        interrupted = cards["codex-web-search:ws_3"]
        self.assertEqual(interrupted["name"], "OpenAI web_search · 搜索中断")
        self.assertEqual(interrupted["args"], {})

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

    async def test_passive_rate_limits_update_display_cache_and_filter_non_codex(self):
        await self.registry.migrate()
        saved_model = self.conf["provider"][0]
        await self.manager.reload(saved_model)
        loaded = self.manager.inst_map[saved_model["id"]]
        self.assertIsInstance(loaded, provider_module.ProviderOpenAICodex)

        usage_service = provider_module.usage_service
        oauth_mod = provider_module.oauth

        stream_events = [
            {
                "type": "codex.rate_limits",
                "metered_limit_name": "codex",
                "rate_limits": {
                    "primary": {
                        "used_percent": 42,
                        "window_minutes": 300,
                        "reset_at": 1_900_000_500,
                    },
                    "secondary": {
                        "used_percent": 15,
                        "window_minutes": 10080,
                        "reset_at": 1_900_500_000,
                    },
                },
            },
            {"type": "response.output_text.delta", "delta": "ok"},
            {
                "type": "response.completed",
                "response": {"id": "resp-limits", "status": "completed", "output": []},
            },
        ]
        response_headers = {
            "content-type": "text/event-stream",
            "x-codex-primary-used-percent": "38",
            "x-codex-primary-window-minutes": "300",
            "x-codex-primary-reset-at": "1900000400",
        }
        other_events = [
            {
                "type": "codex.rate_limits",
                "metered_limit_name": "imagegen_premium",
                "rate_limits": {
                    "primary": {
                        "used_percent": 100,
                        "window_minutes": 1440,
                        "reset_at": 1_900_086_400,
                    }
                },
            },
            {"type": "response.output_text.delta", "delta": "ok"},
            {
                "type": "response.completed",
                "response": {"id": "resp-img", "status": "completed", "output": []},
            },
        ]
        other_headers = {
            "content-type": "text/event-stream",
            "x-codex-active-limit": "imagegen_premium",
            "x-codex-primary-used-percent": "100",
            "x-codex-primary-window-minutes": "1440",
            "x-codex-primary-reset-at": "1900086400",
        }

        current_reply = [stream_events, response_headers]

        def respond(_request: httpx.Request) -> httpx.Response:
            events, headers = current_reply
            return httpx.Response(
                200,
                text="".join(f"data: {json.dumps(e)}\n\n" for e in events),
                headers=headers,
            )

        loaded._create_http_client = lambda _cfg: httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        )

        with (
            mock.patch.object(runtime, "_config_mgr", self.coordinator.config_manager),
            mock.patch.object(runtime, "_credential_coordinator", self.coordinator),
            mock.patch.object(runtime, "_startup_error", None),
        ):
            reply = await loaded.text_chat(prompt="Hello")
            self.assertEqual(reply.completion_text, "ok")

            with mock.patch.object(
                oauth_mod, "fetch_rate_limits", new=mock.AsyncMock()
            ) as active_fetch:
                cached = await usage_service.fetch_source_usage(loaded._source_id)
            active_fetch.assert_not_awaited()
            self.assertEqual(
                [w["used_percent"] for w in cached["windows"]],
                [42.0, 15.0],
            )
            self.assertEqual(
                [w["label_seconds"] for w in cached["windows"]],
                [18000, 604800],
            )

            # Image or specialized metered limits never overwrite account windows or cool the account.
            current_reply[:] = [other_events, other_headers]
            await loaded.text_chat(prompt="Hello again")
            self.assertNotEqual(
                self.coordinator.status(loaded._source_id).state, "cooling"
            )
            with mock.patch.object(
                oauth_mod, "fetch_rate_limits", new=mock.AsyncMock()
            ) as active_fetch:
                still_cached = await usage_service.fetch_source_usage(loaded._source_id)
            active_fetch.assert_not_awaited()
            self.assertEqual(
                [w["used_percent"] for w in still_cached["windows"]],
                [42.0, 15.0],
            )


if __name__ == "__main__":
    unittest.main()
