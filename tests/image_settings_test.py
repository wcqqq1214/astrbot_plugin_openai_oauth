"""Exercise both dashboard settings entry points against a disk-backed plugin config."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
from astrbot.api import AstrBotConfig
from astrbot.core.agent.tool import ToolSet
from astrbot.core.provider.register import llm_tools
from astrbot.dashboard.services import config_service
from local_codex_test import Config
from login_test import payload, plugin, request_context

NAME = "astrbot_plugin_openai_oauth"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text()
)


class ImageSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory, f"{NAME}_config.json")
        self.metadata = SimpleNamespace(name=NAME, i18n={})
        self.enterContext(
            patch.object(config_service, "star_registry", [self.metadata])
        )
        core = SimpleNamespace(
            astrbot_config=Config(provider_sources=[], provider=[]),
            plugin_manager=SimpleNamespace(reload=self.reload),
        )
        self.standard = config_service.ConfigFileService(core)
        self.display = config_service.ConfigDisplayService(core)
        self.routes = {}
        self.context = SimpleNamespace(
            astrbot_config_mgr=SimpleNamespace(default_conf=core.astrbot_config),
            get_registered_star=self.standard.get_plugin_metadata_by_name,
            register_web_api=lambda path, handler, *_: self.routes.update(
                {path: handler}
            ),
            conversation_manager=SimpleNamespace(
                get_curr_conversation_id=AsyncMock(return_value="chat")
            ),
            get_provider_by_id=Mock(
                spec=plugin.Context.get_provider_by_id,
                return_value=Mock(spec=plugin.ProviderOpenAICodex),
            ),
            get_config=lambda **_: {},
        )
        self.enterContext(
            patch.object(
                plugin.OpenAI_OAuth_Plugin,
                "_refresh_codex_version",
                new_callable=AsyncMock,
            )
        )
        self.star = None
        await self.reload(NAME)
        self.addAsyncCleanup(self.terminate)

    async def terminate(self):
        if self.star:
            await self.star.terminate()

    async def reload(self, name):
        self.assertEqual(name, NAME)
        await self.terminate()
        config = AstrBotConfig(config_path=str(self.path), schema=SCHEMA)
        self.metadata.config = config
        self.star = plugin.OpenAI_OAuth_Plugin(self.context, config)
        await self.star.initialize()
        return True, None

    async def post(self, route, body=None):
        with request_context(body):
            response = await self.routes[f"/{NAME}/{route}"]()
        return payload(response)

    async def assert_entries(self, enabled):
        self.assertEqual(
            self.display.get_plugin_config(NAME)["config"]["image_enabled"], enabled
        )
        self.assertEqual(
            (await self.post("providers/list"))["settings"]["image_enabled"], enabled
        )
        event = SimpleNamespace(
            unified_msg_origin="session",
            get_messages=Mock(return_value=[]),
            set_extra=Mock(),
            should_call_llm=Mock(),
            send=AsyncMock(),
        )
        tool_name = plugin.image_generation.TOOL_NAME
        edit_name = plugin.image_generation.EDIT_TOOL_NAME
        tools = ToolSet(
            tools=[llm_tools.get_func(name) for name in (tool_name, edit_name)]
        )
        for parts, expected in (
            ([], tool_name),
            ([plugin.Image(file="missing.png")], edit_name),
        ):
            event.get_messages.return_value = parts
            request = SimpleNamespace(conversation=None, func_tool=tools)
            await self.star.prepare_image_tool(event, request)
            self.assertEqual(
                [t.name for t in request.func_tool.tools], [expected] if enabled else []
            )
        self.assertEqual(len(tools.tools), 2)
        account = plugin.image_generation.ChatAccount("model", "selected", "id")
        self.star._image_accounts[("session", "chat")] = account
        invocation = plugin.image_generation.ToolInvocation(account, 120)
        token = plugin.image_generation.tool_invocation.set(invocation)
        try:
            with patch.object(
                plugin.image_generation,
                "generate",
                new=AsyncMock(return_value=b"image"),
            ) as generate:
                result = await self.star.codex_generate_image(event, "A cat")
                self.assertEqual(
                    result,
                    plugin.messages.text("image.sent" if enabled else "image.disabled"),
                )
                await self.star.draw(event, "A cat")
                self.assertEqual(generate.await_count, 2 if enabled else 0)
                if not enabled:
                    self.assertEqual(
                        event.send.await_args.args[0].chain[0].text,
                        plugin.messages.text("image.disabled"),
                    )
        finally:
            plugin.image_generation.tool_invocation.reset(token)

    async def test_shared_setting_survives_reload_and_controls_both_image_entries(self):
        await self.assert_entries(False)
        form = dict(self.display.get_plugin_config(NAME)["config"])
        form.update(image_enabled=True, image_account="selected")
        await self.standard.save_plugin_configs(form, NAME)
        await self.assert_entries(True)
        for enabled in (False, True):
            response = await self.post("settings/update", {"image_enabled": enabled})
            self.assertEqual(response["settings"], {"image_enabled": enabled})
            await self.assert_entries(enabled)
            await self.reload(NAME)
            await self.assert_entries(enabled)
            self.assertEqual(self.metadata.config["image_account"], "selected")

    async def test_invalid_or_failed_save_preserves_image_setting(self):
        for value in (1, "false", None):
            result = await self.post("settings/update", {"image_enabled": value})
            self.assertEqual(result["message"], "invalid_request")
        result = await self.post(
            "settings/update", {"image_enabled": True, "native_web_search": True}
        )
        self.assertEqual(result["message"], "invalid_request")
        with patch.object(AstrBotConfig, "_write_config_snapshot", side_effect=OSError):
            result = await self.post("settings/update", {"image_enabled": True})
        self.assertEqual(result["message"], "save_failed")
        await self.assert_entries(False)
        await self.reload(NAME)
        await self.assert_entries(False)


if __name__ == "__main__":
    unittest.main()
