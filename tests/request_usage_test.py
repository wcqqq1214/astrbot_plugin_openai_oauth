"""Verify Codex request accounting through the Dashboard service and public chat APIs."""

import json
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import httpx
from provider_routing_test import RoutingFixture, provider_module

HAS_REQUEST_STATS = find_spec("astrbot.core.provider.sources.chat_request") is not None
if HAS_REQUEST_STATS:
    from astrbot.core.db.po import ChatRequestStat
    from astrbot.core.db.sqlite import SQLiteDatabase
    from astrbot.core.provider.sources import chat_request
    from astrbot.dashboard.services.stat_service import StatService
    from sqlmodel import select


def completion(*, report_usage=True):
    response = {"id": "r", "status": "completed", "output": []}
    if report_usage:
        response["usage"] = {
            "input_tokens": 11,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens": 7,
        }
    events = [
        {"type": "response.output_text.delta", "delta": "ok"},
        {"type": "response.completed", "response": response},
    ]
    return httpx.Response(
        200,
        text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        headers={"content-type": "text/event-stream"},
    )


class LegacyUsageTests(RoutingFixture):
    async def test_response_retains_usage_for_turn_accounting(self):
        self.outcomes["local"] = [completion()]
        with patch.object(provider_module, "chat_request", None):
            response = await self.provider.text_chat(prompt="hi")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(
            (
                response.usage.input_other,
                response.usage.input_cached,
                response.usage.output,
            ),
            (8, 3, 7),
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

    async def test_stream_records_failed_open_then_success(self):
        self.outcomes["local"] = [503, completion()]
        chunks = [
            chunk
            async for chunk in self.provider.text_chat_stream(
                prompt="hi", conversation_id="conv", request_max_retries=2
            )
        ]
        self.assertEqual(chunks[-1].usage.total, 18)
        await self.assert_usage([("error", None, None, None), ("completed", 8, 3, 7)])

    async def test_missing_usage_stays_unknown(self):
        self.outcomes["local"] = [completion(report_usage=False)]
        await self.provider.text_chat(prompt="hi", conversation_id="conv")
        await self.assert_usage([("completed", None, None, None)], total=0)

    async def test_failure_after_first_delta_records_error_without_replay(self):
        self.outcomes["local"] = ["partial", completion()]
        chunks = [
            chunk
            async for chunk in self.provider.text_chat_stream(
                prompt="hi", conversation_id="conv", request_max_retries=3
            )
        ]
        self.assertEqual(chunks[0].completion_text, "partial")
        self.assertEqual(chunks[-1].role, "err")
        await self.assert_usage([("error", None, None, None)], total=0)

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
