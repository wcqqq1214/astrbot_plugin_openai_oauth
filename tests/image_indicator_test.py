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
from astrbot.core import db_helper
from astrbot.core.platform.sources.webchat import webchat_event
from astrbot.core.platform.sources.webchat.webchat_event import WebChatMessageEvent
from astrbot.core.star.star import star_map
from astrbot.dashboard.services.chat_service import ChatRunState, ChatService
from login_test import plugin
from PIL import Image

bridge = plugin.chatui_citations


@unittest.skipUnless(
    hasattr(ChatService, "get_chat_view"), "Host lacks chat-message views"
)
class ImageIndicatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from astrbot.core.message.interactive_ui import ViewSpec

        await db_helper.initialize()
        meta = star_map[plugin.__name__]
        self.enterContext(
            patch.multiple(
                meta,
                activated=True,
                star_cls=object(),
                module=plugin,
                views=[ViewSpec(name="image_progress", target="chat_message")],
            )
        )
        self.addCleanup(bridge.install())
        queue = webchat_event.webchat_queue_mgr.get_or_create_back_queue("run")
        self.run = ChatRunState("run", "user", "session", "turn", "webchat", queue)
        self.frames = asyncio.Queue()
        self.run.subscribers.add(self.frames)
        self.service = object.__new__(ChatService)
        self.service.chat_runs = {"run": self.run}
        self.service.chat_runs_by_session = {"session": {"run"}}
        self.service.running_convs = {}
        self.service.attachments_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.service.create_attachment_from_file = AsyncMock(
            return_value={"attachment_id": "result"}
        )
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
                            self.assertEqual(
                                (parts[-1]["type"], parts[-1]["text"]), ("view", "0%")
                            )
                            self.assertEqual(parts[0]["text"], "Ready")
                            if outcome == "success":
                                generation.set_result(b"image")
                                await task
                                self.service.create_attachment_from_file.assert_awaited()
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
                    final = hidden["data"]["content"]["message"]
                    self.assertFalse(
                        any(
                            p.get("text") == "0%" and p["type"] == "view" for p in final
                        )
                    )
                    self.assertEqual(final[0]["text"], "Ready")

    async def test_reconnect_concurrent_images_and_history(self):
        async with bridge.image_generation_indicator(self.event):
            await self.next_frame("run_snapshot")
            async with bridge.image_generation_indicator(self.event):
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
                        frame["data"]["content"]["message"][-1]["text"], "0%"
                    )
                finally:
                    await resumed.aclose()
            self.assertEqual(self.run.message_parts[-1]["text"], "0%")
            self.assertNotIn(
                "image_progress", str(self.service.save_bot_message.await_args_list)
            )
            self.service.save_bot_message.assert_awaited()
        self.assertNotIn("image_progress", str(self.run.message_parts))
        async with bridge.image_generation_indicator(
            Mock(message_obj=self.event.message_obj)
        ):
            self.assertNotIn("image_progress", str(self.run.message_parts))

    async def test_draw_delivers_only_the_finished_png(self):
        directory = self.service.attachments_dir
        png = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(png, format="PNG")
        data = png.getvalue()
        from astrbot.core.platform_message_history_mgr import (
            PlatformMessageHistoryManager,
        )
        from astrbot.dashboard.services.plugin_page_service import (
            PluginPageService,
            PluginPageServiceError,
        )

        await db_helper.create_platform_session("user", session_id="session")
        self.service.db = db_helper
        self.service.platform_history_mgr = PlatformMessageHistoryManager(db_helper)
        self.service.webchat_img_dir = directory
        del self.service.save_bot_message, self.service.create_attachment_from_file
        self.service.core_lifecycle = SimpleNamespace(
            plugin_manager=SimpleNamespace(context=self.star.context)
        )
        generation = asyncio.get_running_loop().create_future()
        with patch.object(
            plugin.image_generation, "generate", Mock(return_value=generation)
        ):
            drawing = asyncio.create_task(self.star.draw(self.event, "A cat"))
            shown = await self.next_frame("run_snapshot")
            view_id = shown["data"]["content"]["message"][-1]["id"]
            _, _, spec, entry = await self.service.get_chat_view("user", view_id)
            self.assertTrue(entry.is_file())
            pages = object.__new__(PluginPageService)
            args = {
                "plugin_name": "astrbot_plugin_openai_oauth",
                "view_name": spec.name,
                "asset_path": view_id + ".png",
            }
            with self.assertRaises(PluginPageServiceError):
                await pages.serve_page_content(username="other", **args)
            download = asyncio.create_task(
                pages.serve_page_content(username="user", **args)
            )
            generation.set_result(data)
            await drawing
            self.assertEqual((await download).content, data)
        await self.next_frame("run_snapshot")
        await self.next_frame("message_saved")
        self.service.chat_runs.pop("run")
        record, _, _, _ = await self.service.get_chat_view("user", view_id)
        saved = await db_helper.get_platform_message_history_by_id(
            int(record["message_id"])
        )
        result = saved.content["message"][-1]
        self.assertEqual(result["id"], view_id)
        self.assertTrue(await db_helper.get_attachment_by_id(result["attachment_id"]))
        self.assertEqual(
            (await pages.serve_page_content(username="user", **args)).content, data
        )
        self.assertEqual([p.read_bytes() for p in Path(directory).iterdir()], [data])


if __name__ == "__main__":
    unittest.main()
