"""Exercise stream retries through the real SDK SSE parser without network access."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ASTRBOT_ROOT = Path(os.environ.get("ASTRBOT_ROOT") or PLUGIN_ROOT.parent / "AstrBot")
sys.path[:0] = [str(ASTRBOT_ROOT), str(PLUGIN_ROOT.parent)]
os.chdir(ASTRBOT_ROOT)

import httpx
from openai import APIError, AsyncOpenAI

module = importlib.import_module(f"{PLUGIN_ROOT.name}.main")
credential_store = importlib.import_module(f"{module.__package__}.src.credential_store")
oauth = importlib.import_module(f"{module.__package__}.src.oauth")
provider_module = importlib.import_module(f"{module.__package__}.src.provider")

OVERLOAD = {
    "error": {
        "message": "Our servers are currently overloaded. Please try again later."
    }
}
SUCCESS = [
    {"type": "response.output_text.delta", "delta": "ok"},
    {
        "type": "response.completed",
        "response": {"id": "success", "status": "completed", "output": []},
    },
]


class StreamRetryTests(unittest.IsolatedAsyncioTestCase):
    async def run_stream(
        self, attempts, *, limit=None, before_attempt=None, payload=None
    ):
        requests = []
        self.headers = []
        responses = []
        output = []

        class EventBody(httpx.AsyncByteStream):
            def __init__(self, events):
                self.events = events

            async def __aiter__(self):
                for event in self.events:
                    if isinstance(event, BaseException):
                        raise event
                    yield f"data: {json.dumps(event)}\n\n".encode()

        def handle(request):
            self.assertTrue(all(response.is_closed for response in responses))
            requests.append(json.loads(request.content))
            self.headers.append(request.headers)
            attempt = attempts[min(len(requests) - 1, len(attempts) - 1)]
            if isinstance(attempt, int):
                response = httpx.Response(
                    attempt, json={"error": {"message": "Service unavailable"}}
                )
            else:
                response = httpx.Response(
                    200,
                    stream=EventBody(attempt),
                    headers={"content-type": "text/event-stream"},
                )
            responses.append(response)
            return response

        provider = object.__new__(module.ProviderOpenAICodex)
        provider.provider_config = {"custom_extra_body": {"reasoning_effort": "low"}}
        provider.default_params = ["model", "input", "store"]
        error = None
        async with AsyncOpenAI(
            api_key="test",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as client:
            with mock.patch.object(
                asyncio, "sleep", new_callable=mock.AsyncMock
            ) as sleep:
                try:
                    async for item in provider._query_stream(
                        client,
                        payload or {"model": "test", "input": [], "store": True},
                        None,
                        request_max_retries=limit,
                        session_effort="high",
                        before_attempt=before_attempt,
                    ):
                        output.append(item)
                except (
                    APIError,
                    asyncio.CancelledError,
                    credential_store.CredentialError,
                ) as exc:
                    error = exc
        self.assertTrue(all(response.is_closed for response in responses))
        return requests, output, error, [call.args[0] for call in sleep.await_args_list]

    async def test_overload_then_success(self):
        requests, output, error, delays = await self.run_stream([[OVERLOAD], SUCCESS])
        self.assertIsNone(error)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(requests[1]["reasoning"]["effort"], "high")
        self.assertFalse(requests[1]["store"])
        self.assertEqual(output[-1].completion_text, "ok")
        self.assertEqual(delays, [1])

    async def test_prompt_cache_key_names_the_codex_session(self):
        requests, _, error, _ = await self.run_stream(
            [SUCCESS],
            payload={"model": "test", "input": [], "prompt_cache_key": "conv-1"},
        )
        self.assertIsNone(error)
        self.assertEqual(requests[0]["prompt_cache_key"], "conv-1")
        self.assertEqual(self.headers[0]["session-id"], "conv-1")
        self.assertEqual(self.headers[0]["thread-id"], "conv-1")

        requests, _, _, _ = await self.run_stream([SUCCESS])
        self.assertNotIn("prompt_cache_key", requests[0])
        self.assertNotIn("session-id", self.headers[0])

    async def test_unsupported_parameters_are_not_sent(self):
        requests, _, error, _ = await self.run_stream(
            [SUCCESS],
            payload={
                "model": "test",
                "input": [],
                "temperature": 0.2,
                "top_p": 0.9,
                "max_output_tokens": 100,
                "max_tokens": 100,
                "service_tier": "flex",
            },
        )
        self.assertIsNone(error)
        for key in ("temperature", "top_p", "max_output_tokens", "max_tokens"):
            self.assertNotIn(key, requests[0])
        self.assertNotIn("service_tier", requests[0])

        requests, _, _, _ = await self.run_stream(
            [SUCCESS],
            payload={"model": "test", "input": [], "service_tier": "priority"},
        )
        self.assertEqual(requests[0]["service_tier"], "priority")

    def test_prompt_cache_key_is_stable_per_conversation(self):
        key = module.ProviderOpenAICodex._prompt_cache_key
        payload = {"model": "m", "input": [{"role": "user", "content": "hi"}]}
        self.assertEqual(key("umo:1", payload), key("umo:1", {"model": "m"}))
        self.assertNotEqual(key("umo:1", payload), key("umo:2", payload))
        self.assertNotIn("umo", key("umo:1", payload))
        start = [
            {"role": "developer", "content": "rules"},
            {"role": "user", "content": "first"},
        ]
        later = {"model": "m", "input": [*start, {"role": "user", "content": "x"}]}
        self.assertEqual(key(None, {"model": "m", "input": start}), key(None, later))
        self.assertIsNone(key(None, {"model": "m", "input": start[:1]}))
        self.assertRegex(
            key(None, later), r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
        )

    async def test_disabled_before_retry_prevents_another_http_request(self):
        count = 0

        def guard():
            nonlocal count
            count += 1
            if count > 1:
                raise credential_store.CredentialSourceError("Provider disabled")

        requests, output, error, _ = await self.run_stream(
            [[OVERLOAD], SUCCESS], before_attempt=guard
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(output, [])
        self.assertIsInstance(error, credential_store.CredentialSourceError)

    async def test_exhaustion_preserves_api_error(self):
        requests, output, error, delays = await self.run_stream([[OVERLOAD]], limit=3)
        self.assertEqual(len(requests), 3)
        self.assertEqual(output, [])
        self.assertIsInstance(error, APIError)
        self.assertEqual(error.body, OVERLOAD["error"])
        self.assertEqual(delays, [1, 2])

    async def test_one_attempt_disables_replay(self):
        requests, _, error, delays = await self.run_stream([[OVERLOAD]], limit=1)
        self.assertEqual(len(requests), 1)
        self.assertIsInstance(error, APIError)
        self.assertEqual(delays, [])

    async def test_default_attempt_limit(self):
        requests, _, error, delays = await self.run_stream([[OVERLOAD]])
        self.assertEqual(len(requests), provider_module.REQUEST_RETRY_ATTEMPTS)
        self.assertIsInstance(error, APIError)
        self.assertEqual(delays, [1, 2, 4, 8])

    async def test_cancellation_does_not_retry(self):
        requests, _, error, delays = await self.run_stream([[asyncio.CancelledError()]])
        self.assertEqual(len(requests), 1)
        self.assertIsInstance(error, asyncio.CancelledError)
        self.assertEqual(delays, [])

    async def test_no_replay_after_text_or_reasoning(self):
        for event_type in (
            "response.output_text.delta",
            "response.reasoning_summary_text.delta",
        ):
            with self.subTest(event_type=event_type):
                requests, output, error, delays = await self.run_stream(
                    [[{"type": event_type, "delta": "partial"}, OVERLOAD]]
                )
                self.assertEqual(len(requests), 1)
                self.assertEqual(len(output), 1)
                self.assertIsInstance(error, APIError)
                self.assertEqual(delays, [])

    async def test_reasoning_deltas_are_joined_without_separators(self):
        events = [
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "summary_index": 0,
                "delta": delta,
            }
            for delta in ("Think", "ing ", "fast")
        ]
        events.append(
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "summary_index": 1,
                "delta": "Then answer",
            }
        )
        requests, output, error, _ = await self.run_stream([[*events, *SUCCESS]])
        self.assertIsNone(error)
        self.assertEqual(len(requests), 1)
        self.assertEqual(output[-1].reasoning_content, "Thinking fast\nThen answer")
        self.assertEqual(output[-1].completion_text, "ok")

    async def test_specific_error_codes(self):
        for code, retryable in (
            ("server_error", True),
            ("service_unavailable", True),
            ("invalid_token", False),
            ("usage_limit_reached", False),
            ("rate_limit_exceeded", False),
            ("invalid_request_error", False),
        ):
            with self.subTest(code=code):
                requests, _, error, delays = await self.run_stream(
                    [[{"error": {"code": code, "message": "Failure"}}], SUCCESS]
                )
                self.assertEqual(len(requests), 2 if retryable else 1)
                self.assertEqual(error is None, retryable)
                self.assertEqual(bool(delays), retryable)
                if code == "invalid_token":
                    self.assertEqual(oauth.classify_codex_error(error), "credential")
                elif code == "usage_limit_reached":
                    self.assertEqual(oauth.classify_codex_error(error), "usage_limit")

    async def test_unknown_error_does_not_retry(self):
        requests, _, error, delays = await self.run_stream(
            [[{"error": {"message": "Please try again later."}}]]
        )
        self.assertEqual(len(requests), 1)
        self.assertIsInstance(error, APIError)
        self.assertEqual(delays, [])

    async def test_creation_and_iteration_share_attempt_budget(self):
        requests, _, error, delays = await self.run_stream([503, [OVERLOAD]], limit=3)
        self.assertEqual(len(requests), 3)
        self.assertIsInstance(error, APIError)
        self.assertEqual(len(delays), 2)

    async def test_partial_tool_state_is_discarded_on_retry(self):
        partial = {
            "type": "response.output_item.added",
            "item": {
                "type": "function_call",
                "call_id": "old",
                "name": "unused",
                "arguments": "{}",
            },
        }
        requests, output, error, _ = await self.run_stream(
            [[partial, OVERLOAD], SUCCESS]
        )
        self.assertIsNone(error)
        self.assertEqual(len(requests), 2)
        self.assertEqual(output[-1].tools_call_ids, [])


if __name__ == "__main__":
    unittest.main()
