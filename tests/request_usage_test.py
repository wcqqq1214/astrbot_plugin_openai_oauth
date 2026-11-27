"""Verify Codex request accounting through the Dashboard service and public chat APIs."""

import json
import sys
import tempfile
import unittest
from contextlib import aclosing
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import httpx
from provider_routing_test import RoutingFixture

HAS_REQUEST_STATS = find_spec("astrbot.core.provider.sources.chat_request") is not None
if HAS_REQUEST_STATS:
    from astrbot.core.db.po import ChatRequestStat
    from astrbot.core.db.sqlite import SQLiteDatabase
    from astrbot.core.provider.sources import chat_request
    from astrbot.dashboard.services.stat_service import StatService
    from sqlmodel import select


USAGE = {
    "input_tokens": 11,
    "input_tokens_details": {"cached_tokens": 3},
    "output_tokens": 7,
}
TEXT_DELTA = {"type": "response.output_text.delta", "delta": "ok"}


def completion(*, usage=USAGE):
    response = {"id": "r", "status": "completed", "output": []}
    if usage is not None:
        response["usage"] = usage
    return event_stream(
        TEXT_DELTA, {"type": "response.completed", "response": response}
    )


def event_stream(*events):
    return httpx.Response(
        200,
        text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        headers={"content-type": "text/event-stream"},
    )


@unittest.skipUnless(HAS_REQUEST_STATS, "Requires per-request statistics")
class RequestUsageTests(RoutingFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db = SQLiteDatabase(str(Path(directory) / "usage.db"))
        self.addAsyncCleanup(self.db.engine.dispose)
        self.addAsyncCleanup(self.db.chat_usage_writer.close)
        await self.db.initialize()
        self.enterContext(patch.object(chat_request, "db_helper", self.db))
        self.service = StatService(self.db, MagicMock(), {})

    async def assert_usage(self, expected, total=18):
        await self.db.chat_usage_writer.flush()
        async with self.db.get_db() as session:
            result = await session.execute(
                select(ChatRequestStat).order_by(ChatRequestStat.id)
            )
            rows = result.scalars().all()
        self.assertEqual(
            [
                (r.status, r.token_input_other, r.token_input_cached, r.token_output)
                for r in rows
            ],
            expected,
        )
        self.assertEqual(len(self.requests), len(rows))
        for row in rows:
            self.assertEqual(row.provider_id, "model")
            self.assertEqual(row.provider_model, "test-model")
            self.assertEqual(row.conversation_id, "conv")
        stats = await self.service.get_provider_token_stats(1)
        self.assertEqual(
            stats["range_by_provider"], [{"provider_id": "model", "tokens": total}]
        )
        self.assertEqual(stats["range_total_tokens"], total)
        self.assertEqual(stats["range_total_calls"], len(expected))
        self.assertEqual(
            stats["range_unknown_usage_calls"], sum(row[1] is None for row in expected)
        )

    async def test_text_chat_counts_one_request(self):
        self.outcomes["local"] = [completion()]
        response = await self.provider.text_chat(prompt="hi", conversation_id="conv")
        self.assertEqual(response.usage.total, 18)
        await self.assert_usage([("completed", 8, 3, 7)])

    async def test_stream_retry_settles_before_consumer_closes_on_final(self):
        self.outcomes["local"] = [503, completion()]
        async with aclosing(
            self.provider.text_chat_stream(
                prompt="hi", conversation_id="conv", request_max_retries=2
            )
        ) as stream:
            async for response in stream:
                if not response.is_chunk:
                    self.assertEqual(response.usage.total, 18)
                    break
            else:
                self.fail("Expected a final response")
        await self.assert_usage([("error", None, None, None), ("completed", 8, 3, 7)])

    async def test_only_reported_zero_counts_as_known_usage(self):
        for usage, expected in (
            (None, None),
            ({}, None),
            ({"input_tokens": 0, "output_tokens": 0}, 0),
        ):
            self.outcomes["local"] = [completion(usage=usage)]
            result = await self.provider.text_chat(prompt="hi", conversation_id="conv")
            self.assertEqual(
                result.usage.total if result.usage is not None else None, expected
            )
        unknown = ("completed", None, None, None)
        await self.assert_usage([unknown, unknown, ("completed", 0, 0, 0)], total=0)

    async def test_failed_terminal_response_retains_reported_usage(self):
        self.outcomes["local"] = [
            event_stream(
                TEXT_DELTA,
                {
                    "type": "response.failed",
                    "response": {"error": {"code": "server_error"}, "usage": USAGE},
                },
            )
        ]
        result = await self.provider.text_chat(prompt="hi", conversation_id="conv")
        self.assertEqual(result.role, "err")
        await self.assert_usage([("error", 8, 3, 7)])

    async def test_last_reported_snapshot_reaches_both_response_and_dashboard(self):
        self.outcomes["local"] = [
            event_stream(
                {
                    "type": "response.in_progress",
                    "response": {"usage": {"input_tokens": 5, "output_tokens": 0}},
                },
                {"type": "response.in_progress", "response": {"usage": USAGE}},
                TEXT_DELTA,
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "ok"}],
                            }
                        ],
                    },
                },
            )
        ]
        result = await self.provider.text_chat(prompt="hi", conversation_id="conv")
        self.assertEqual(result.usage.total, 18)
        await self.assert_usage([("completed", 8, 3, 7)])

    async def test_closing_after_first_delta_records_aborted(self):
        self.outcomes["local"] = [completion()]
        stream = self.provider.text_chat_stream(prompt="hi", conversation_id="conv")
        try:
            self.assertEqual((await anext(stream)).completion_text, "ok")
        finally:
            await stream.aclose()
        await self.assert_usage([("aborted", None, None, None)], total=0)


if __name__ == "__main__":
    unittest.main()
