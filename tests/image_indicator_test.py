"""Exercise the ephemeral image indicator against AstrBot's WebChat consumer."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
from astrbot.core.platform.sources.webchat import webchat_event
from astrbot.core.platform.sources.webchat.webchat_event import WebChatMessageEvent
from astrbot.dashboard.services.chat_service import ChatRunState, ChatService
from login_test import plugin
from PIL import Image

bridge = plugin.chatui_citations


class ImageIndicatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.addCleanup(bridge.install())
        queue = webchat_event.webchat_queue_mgr.get_or_create_back_queue("run")
        self.run = ChatRunState("run", "user", "session", "turn", "webchat", queue)
        self.frames = asyncio.Queue()
        self.run.subscribers.add(self.frames)
        self.service = object.__new__(ChatService)
        self.service.chat_runs = {"run": self.run}
        self.service.chat_runs_by_session = {"session": {"run"}}
        self.service.running_convs = {}
        self.service.save_bot_message = AsyncMock(return_value=None)
        self.consumer = asyncio.create_task(self.service._consume_chat_run(self.run))
        await self.run.back_queue.put(
            {"type": "plain", "data": "Ready", "streaming": True}
        )
        await self.next_frame("plain")

        self.event = Mock(spec=WebChatMessageEvent)
        self.event.message_obj = SimpleNamespace(message_id="run")
        self.event.unified_msg_origin = "session"
        self.event.send = AsyncMock()
        self.star = object.__new__(plugin.OpenAI_OAuth_Plugin)
        self.star.config = {"image_enabled": True}
        self.star.context = SimpleNamespace(
            get_config=lambda **_: {},
            get_provider_by_id=lambda _: Mock(spec=plugin.ProviderOpenAICodex),
            conversation_manager=SimpleNamespace(
                get_curr_conversation_id=AsyncMock(return_value="chat")
            ),
        )
        self.account = plugin.image_generation.ChatAccount("model", "account", "id")
        self.star._image_accounts = {("session", "chat"): self.account}

    async def asyncTearDown(self):
        await self.run.back_queue.put({"type": "end", "data": ""})
        await asyncio.wait_for(self.consumer, 5)

    async def next_frame(self, kind):
        async with asyncio.timeout(5):
            while True:
                _, frame = await self.frames.get()
                if frame["type"] == kind:
                    return frame

    async def test_tool_and_draw_on_success_failure_and_cancellation(self):
        invocation = plugin.image_generation.ToolInvocation(self.account, 120)
        token = plugin.image_generation.tool_invocation.set(invocation)
        self.addCleanup(plugin.image_generation.tool_invocation.reset, token)
        for entry in (self.star.draw, self.star.codex_generate_image):
            for outcome in ("success", "failure", "cancel"):
                with self.subTest(entry=entry.__name__, outcome=outcome):
                    generation = asyncio.get_running_loop().create_future()

                    self.event.send.reset_mock()
                    with patch.object(
                        plugin.image_generation,
                        "generate",
                        Mock(return_value=generation),
                    ):
                        task = asyncio.create_task(entry(self.event, "A cat"))
                        try:
                            shown = await self.next_frame("run_snapshot")
                            parts = shown["data"]["content"]["message"]
                            self.assertEqual(parts[-1]["filename"], "生成中")
                            self.assertTrue(
                                parts[-1]["embedded_url"].startswith(
                                    "data:image/svg+xml;base64,"
                                )
                            )
                            self.assertEqual(parts[0]["text"], "Ready")
                            if outcome == "success":
                                generation.set_result(b"image")
                                await task
                                self.event.send.assert_awaited_once()
                            elif outcome == "failure":
                                generation.set_exception(
                                    plugin.image_generation.ImageError("image.failed")
                                )
                                result = await task
                                if entry == self.star.draw:
                                    self.assertEqual(
                                        self.event.send.await_args.args[0]
                                        .chain[0]
                                        .text,
                                        plugin.messages.text("image.failed"),
                                    )
                                else:
                                    self.assertEqual(
                                        result, plugin.messages.text("image.failed")
                                    )
                            else:
                                task.cancel()
                                with self.assertRaises(asyncio.CancelledError):
                                    await task
                        finally:
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                    hidden = await self.next_frame("run_snapshot")
                    self.assertEqual(
                        hidden["data"]["content"]["message"],
                        [{"type": "plain", "text": "Ready"}],
                    )

    async def test_reconnect_concurrent_images_and_history(self):
        with bridge.image_generation_indicator(self.event):
            await self.next_frame("run_snapshot")
            with bridge.image_generation_indicator(self.event):
                await self.run.back_queue.put(
                    {"type": "plain", "data": "Updated", "streaming": False}
                )
                await self.next_frame("plain")
                resumed = self.service._subscribe_chat_run(
                    self.run, include_snapshot=True
                )
                try:
                    frame = json.loads((await anext(resumed)).removeprefix("data: "))
                    self.assertEqual(
                        frame["data"]["content"]["message"][-1]["filename"], "生成中"
                    )
                finally:
                    await resumed.aclose()
            self.assertEqual(self.run.message_parts[-1]["filename"], "生成中")
            self.assertNotIn(
                "data:image/svg", str(self.service.save_bot_message.await_args_list)
            )
            self.service.save_bot_message.assert_awaited()
        self.assertNotIn("embedded_url", str(self.run.message_parts))
        with bridge.image_generation_indicator(
            Mock(message_obj=self.event.message_obj)
        ):
            self.assertNotIn("embedded_url", str(self.run.message_parts))

    async def test_draw_delivers_only_the_finished_png(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(webchat_event, "attachments_dir", directory))
        png = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(png, format="PNG")
        data = png.getvalue()

        async def send(chain):
            await WebChatMessageEvent._send("run", chain, "session")

        self.event.send.side_effect = send
        self.service.create_attachment_from_file = AsyncMock(
            return_value={
                "type": "image",
                "attachment_id": "result",
                "filename": "result.png",
            }
        )
        with patch.object(
            plugin.image_generation, "generate", AsyncMock(return_value=data)
        ):
            await self.star.draw(self.event, "A cat")
        await self.next_frame("image")
        saved = self.service.save_bot_message.await_args.args[1]
        self.assertEqual(
            [part["attachment_id"] for part in saved if part["type"] == "image"],
            ["result"],
        )
        self.assertNotIn("embedded_url", str(saved))
        files = list(Path(directory).iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
