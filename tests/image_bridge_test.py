"""Exercise real AstrBot fallback and reload boundaries with local images."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import unittest
from base64 import b64decode
from copy import deepcopy
from functools import wraps
from importlib.util import find_spec
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(
    os.environ.get("ASTRBOT_ROOT")
    or os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from astrbot.core.agent.message import Message
from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
from astrbot.core.provider.entities import LLMResponse, ProviderRequest
from PIL import Image

legacy_module = "astrbot.core.astr_main_agent"
astr_main_agent = (
    importlib.import_module(legacy_module) if find_spec(legacy_module) else None
)
bridge = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.src.astrbot_image_bridge"
)
generation = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.src.image_generation"
)
CODEX = "OpenAI Subscribe"


def image_parts(messages):
    return [
        part["image_url"]
        for message in messages
        for part in message.get("content", [])
        if isinstance(part, dict) and part.get("type") == "image_url"
    ]


def dimensions(image):
    url = image["url"]
    source = (
        BytesIO(b64decode(url.split(",", 1)[1])) if url.startswith("data:") else url
    )
    with Image.open(source) as opened:
        return opened.format, opened.size


class ImageBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.path = self.directory / "screenshot.png"
        with Image.new("RGB", (4096, 1024), "blue") as image:
            image.save(self.path)
        self.remove = bridge.install(CODEX)
        self.addCleanup(lambda: self.remove())
        self.event = SimpleNamespace(track_temporary_local_file=lambda _: None)

    async def prepare(self, request=None, cache=None):
        request = request or ProviderRequest(
            prompt="Read the screenshot.", image_urls=[str(self.path)]
        )
        if hasattr(astr_main_agent, "_compress_image_for_provider"):
            request.image_urls = [
                await astr_main_agent._compress_image_for_provider(
                    ref, {"image_compress_options": {"max_size": 1280}}
                )
                for ref in request.image_urls
            ]
        else:
            from astrbot.core.utils.image_input import prepare_request_images

            await prepare_request_images(
                request,
                self.event,
                max_size=1280,
                output_dir=self.directory,
                prepared=cache if cache is not None else {},
            )
        return request

    async def test_tool_scope_tracks_its_own_response_in_concurrent_runs(self):
        state = getattr(ToolLoopAgentRunner, bridge._STATE_ATTR)

        async def run_tool(runner, request, response):
            yield await asyncio.create_task(read_binding())
            yield await asyncio.create_task(read_binding())

        async def read_binding():
            await asyncio.sleep(0)
            return generation.tool_invocation.get()

        async def consume(invocation):
            response = LLMResponse(role="assistant")
            runner = None
            if invocation is not None:
                response._codex_image_account = invocation.account
                runner = SimpleNamespace(
                    run_context=SimpleNamespace(
                        tool_call_timeout=invocation.runner_timeout
                    )
                )
            stream = state["tool_scope"](run_tool, runner, None, response)
            output = [value async for value in stream]
            self.assertIsNone(generation.tool_invocation.get())
            return output

        first = generation.ToolInvocation(
            generation.ChatAccount("model", "first", "first-account"), 120
        )
        second = generation.ToolInvocation(
            generation.ChatAccount("model", "second", "second-account"), 60
        )
        self.assertEqual(
            await asyncio.gather(consume(first), consume(second), consume(None)),
            [[first, first], [second, second], [None, None]],
        )

    def provider(self, name, captured, *, fail=False):
        async def chat(**payload):
            captured.append((name, deepcopy(payload["contexts"])))
            return LLMResponse(
                role="err" if fail else "assistant", completion_text="Fixture response"
            )

        async def stream(**payload):
            yield await chat(**payload)

        return SimpleNamespace(
            provider_config={"id": name, "type": name, "modalities": ["image"]},
            text_chat=chat,
            text_chat_stream=stream,
        )

    async def runner(self, request, provider, fallbacks=(), *, streaming=False):
        runner = ToolLoopAgentRunner()
        await runner.reset(
            provider=provider,
            request=request,
            run_context=SimpleNamespace(),
            tool_executor=None,
            agent_hooks=None,
            fallback_providers=list(fallbacks),
            streaming=streaming,
        )
        return runner

    async def test_fallback_selects_each_providers_images(self):
        for first, second in ((CODEX, "other"), ("other", CODEX)):
            for streaming in (False, True):
                with self.subTest(first=first, streaming=streaming):
                    request = await self.prepare()
                    captured = []
                    runner = await self.runner(
                        request,
                        self.provider(first, captured, fail=True),
                        [self.provider(second, captured)],
                        streaming=streaming,
                    )
                    before = deepcopy(
                        [
                            message.model_dump()
                            for message in runner.run_context.messages
                        ]
                    )
                    async for _ in runner._iter_llm_responses_with_fallback():
                        pass
                    self.assertEqual([name for name, _ in captured], [first, second])
                    for name, messages in captured:
                        image = image_parts(messages)[0]
                        self.assertEqual(
                            dimensions(image),
                            ("PNG", (2048, 512))
                            if name == CODEX
                            else ("JPEG", (1280, 320)),
                        )
                        self.assertNotIn("astrbot-openai-oauth:", str(image.get("id")))
                    self.assertEqual(
                        before,
                        [
                            message.model_dump()
                            for message in runner.run_context.messages
                        ],
                    )

    async def test_pending_previews_survive_module_reload(self):
        cache = {}
        request = await self.prepare(cache=cache)
        old_remove = self.remove
        self.remove()
        importlib.reload(bridge)
        self.remove = bridge.install(CODEX)
        old_remove()
        if not hasattr(astr_main_agent, "_compress_image_for_provider"):
            await self.prepare(request, cache)
        captured = []
        runner = await self.runner(request, self.provider(CODEX, captured))
        async for _ in runner._iter_llm_responses():
            pass
        self.assertEqual(
            dimensions(image_parts(captured[0][1])[0]), ("PNG", (2048, 512))
        )

    async def test_third_party_wrappers_survive_disable_and_reload(self):
        stable_reset = ToolLoopAgentRunner.reset
        calls = []

        @wraps(stable_reset)
        async def third_party(*args, **kwargs):
            calls.append(True)
            return await stable_reset(*args, **kwargs)

        ToolLoopAgentRunner.reset = third_party
        self.addCleanup(setattr, ToolLoopAgentRunner, "reset", stable_reset)
        request = await self.prepare()
        self.remove()
        captured = []
        runner = await self.runner(request, self.provider(CODEX, captured))
        async for _ in runner._iter_llm_responses():
            pass
        self.assertEqual(
            dimensions(image_parts(captured[0][1])[0]), ("JPEG", (1280, 320))
        )
        importlib.reload(bridge)
        self.remove = bridge.install(CODEX)
        self.assertIs(ToolLoopAgentRunner.reset, third_party)
        request = await self.prepare()
        runner = await self.runner(request, self.provider(CODEX, captured))
        async for _ in runner._iter_llm_responses():
            pass
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            dimensions(image_parts(captured[-1][1])[0]), ("PNG", (2048, 512))
        )
        self.remove()
        self.assertIs(ToolLoopAgentRunner.reset, third_party)

    async def test_saved_history_keeps_both_variants_after_source_cleanup(self):
        runner = await self.runner(await self.prepare(), self.provider(CODEX, []))
        saved = json.loads(
            json.dumps([m.model_dump() for m in runner.run_context.messages])
        )
        self.path.unlink()
        importlib.reload(bridge)
        self.remove = bridge.install(CODEX)
        messages = [Message.model_validate(message) for message in saved]
        runner.provider = self.provider("other", [])
        self.assertEqual(
            dimensions(
                image_parts(runner._sanitize_contexts_for_provider(messages))[0]
            ),
            ("JPEG", (1280, 320)),
        )
        runner.provider = self.provider(CODEX, [])
        self.assertEqual(
            dimensions(
                image_parts(runner._sanitize_contexts_for_provider(messages))[0]
            ),
            ("PNG", (2048, 512)),
        )
        self.remove()
        self.assertNotIn(
            "astrbot-openai-oauth:",
            str(
                image_parts(runner._sanitize_contexts_for_provider(messages))[0].get(
                    "id"
                )
            ),
        )

    async def test_original_detail_and_existing_image_id_survive_history(self):
        request = await self.prepare()
        request.extra_user_content_parts = [
            {
                "type": "image_url",
                "image_url": {
                    "url": request.image_urls[0],
                    "detail": "original",
                    "id": "user-image-id",
                },
            }
        ]
        captured = []
        runner = await self.runner(request, self.provider(CODEX, captured))
        async for _ in runner._iter_llm_responses():
            pass
        image = image_parts(captured[0][1])[0]
        self.assertEqual(image["id"], "user-image-id")
        self.assertEqual(image["detail"], "original")
        self.assertEqual(dimensions(image), ("PNG", (4096, 1024)))
        runner.provider = self.provider("other", captured)
        image = image_parts(
            runner._sanitize_contexts_for_provider(runner.run_context.messages)
        )[0]
        self.assertEqual(image["id"], "user-image-id")
        self.assertEqual(dimensions(image), ("JPEG", (1280, 320)))

    @unittest.skipIf(
        hasattr(astr_main_agent, "_compress_image_for_provider"),
        "Legacy AstrBot does not skip missing extra image references during assembly.",
    )
    async def test_identical_previews_keep_each_surviving_origin(self):
        from astrbot.core.utils.image_input import prepare_request_images
        from astrbot.core.utils.media_utils import prepare_model_image

        for untouched_first in (False, True):
            with self.subTest(untouched_first=untouched_first):
                directory = self.directory / str(untouched_first)
                directory.mkdir()
                refs = []
                for name, size, color in [
                    ("first", (4096, 1024), "blue"),
                    ("second", (8192, 2048), "blue"),
                    ("missing", (4096, 1024), "red"),
                ]:
                    path = directory / f"{name}.png"
                    with Image.new("RGB", size, color) as image:
                        image.save(path)
                    refs.append(str(path))
                if untouched_first:
                    generated = await prepare_model_image(
                        refs[1], max_size=1280, output_dir=directory
                    )
                    assert generated is not None
                    compliant = directory / "compliant.jpg"
                    compliant.write_bytes(Path(generated[0]).read_bytes())
                    refs[0] = str(compliant)
                request = ProviderRequest(
                    prompt="Read the images.",
                    extra_user_content_parts=[
                        {
                            "type": "image_url",
                            "image_url": {"url": ref, "detail": "original"},
                        }
                        for ref in refs
                    ],
                )
                await prepare_request_images(
                    request,
                    self.event,
                    max_size=1280,
                    output_dir=directory,
                    prepared={},
                )
                previews = [
                    Path(part["image_url"]["url"])
                    for part in request.extra_user_content_parts
                    if isinstance(part, dict) and part.get("type") == "image_url"
                ]
                self.assertEqual(previews[0].read_bytes(), previews[1].read_bytes())
                previews[2].unlink()
                runner = await self.runner(request, self.provider(CODEX, []))
                images = image_parts(
                    runner._sanitize_contexts_for_provider(runner.run_context.messages)
                )
                first_expected = (
                    ("JPEG", (1280, 320)) if untouched_first else ("PNG", (4096, 1024))
                )
                self.assertEqual(
                    [dimensions(image) for image in images],
                    [first_expected, ("PNG", (6000, 1500))],
                )
                if untouched_first:
                    self.assertEqual(previews[0], compliant)
                    self.assertEqual(
                        b64decode(images[0]["url"].split(",", 1)[1]),
                        compliant.read_bytes(),
                    )


if __name__ == "__main__":
    unittest.main()
