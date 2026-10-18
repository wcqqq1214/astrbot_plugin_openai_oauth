"""Single-source migration, live model selection and durable account storage."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import provider_registry_test as fixtures
from astrbot.api import AstrBotConfig
from login_test import payload, request_context

provider_module = importlib.import_module(f"{fixtures.plugin.__package__}.src.provider")


class SingleSourceTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.RegistryTests.setUp

    async def test_migration_keeps_models_credentials_and_other_sources(self):
        self.conf["provider_sources"].extend(
            [
                {"id": "deepseek", "type": "deepseek", "key": "other-secret"},
                {
                    **self.original,
                    "id": "work",
                    "name": "Work",
                    "credential_mode": "device_oauth",
                    "enable": False,
                    "oauth_routing_mode": "auto",
                },
            ]
        )
        self.conf["provider"].extend(
            [
                {
                    "id": "work-model",
                    "provider_source_id": "work",
                    "model": "gpt-example",
                    "enable": False,
                },
                {"id": "other-model", "provider_source_id": "deepseek"},
            ]
        )
        await self.registry.migrate()
        self.assertEqual(
            [s["id"] for s in self.conf["provider_sources"]],
            ["OpenAI Subscribe", "deepseek"],
        )
        self.assertEqual(self.conf["provider_sources"][1]["key"], "other-secret")
        self.assertEqual(
            self.conf["provider"][1],
            {
                "id": "work-model",
                "provider_source_id": "OpenAI Subscribe",
                "model": "gpt-example",
                "enable": False,
            },
        )
        work = self.coordinator._source("work")
        self.assertEqual(work["key"], self.original["key"])
        self.assertFalse(work["enable"])
        self.assertEqual(work["oauth_routing_mode"], "auto")
        self.assertEqual(
            self.registry.resolve_model("work-model", "OpenAI Subscribe"), "work"
        )
        self.assertEqual(
            [m["id"] for m in self.registry.routing_view()["models"]],
            ["existing-model", "work-model"],
        )
        before = deepcopy(self.conf)
        saves = self.conf.saved
        await self.registry.migrate()
        self.assertEqual(self.conf, before)
        self.assertEqual(self.conf.saved, saves)

    async def test_internal_account_fields_are_hidden_from_source_editor(self):
        fields = fixtures.runtime.CONFIG_METADATA_2["provider_group"]["metadata"][
            "provider"
        ]["items"]
        with patch.dict(fields):
            fixtures.runtime.configure(
                SimpleNamespace(astrbot_config_mgr=self.coordinator.config_manager), {}
            )
            for key in ("oauth_gateway", "oauth_accounts", "oauth_routing"):
                self.assertTrue(fields[key]["invisible"])
        await self.registry.migrate()
        self.assertNotIn("name", self.registry.gateway())
        self.assertTrue(all(s.get("name") for s in self.registry.owned()))

    async def test_accounts_survive_real_astrbot_config_reload(self):
        await self.registry.migrate()
        device = self.registry.owned()[1]
        await self.registry.update_routing(device["id"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cmd_config.json"
            path.write_text(json.dumps(self.conf))
            defaults = {"provider_sources": [], "provider": []}
            reloaded = AstrBotConfig(config_path=str(path), default_config=defaults)
            self.assertEqual(reloaded, self.conf)
            self.assertEqual(
                fixtures.store.find_source(reloaded, device["id"], "OpenAI Subscribe")[
                    "key"
                ],
                device["key"],
            )

    async def test_loaded_models_follow_default_and_keep_explicit_preferences(self):
        await self.registry.migrate()
        device = self.registry.owned()[1]["id"]
        loaded = object.__new__(provider_module.ProviderOpenAICodex)
        loaded.provider_config = {"id": "new-model"}
        loaded._source_id = "OpenAI Subscribe"
        pinned = object.__new__(provider_module.ProviderOpenAICodex)
        pinned.provider_config = {"id": "existing-model"}
        pinned._source_id = "OpenAI Subscribe"
        self.conf["provider"].append(
            {"id": "new-model", "provider_source_id": "OpenAI Subscribe"}
        )
        await self.registry.update_routing(device)
        self.assertEqual(loaded._source_id, device)
        self.assertEqual(pinned._source_id, "OpenAI Subscribe")
        await self.registry.update_routing(None, model_id="existing-model")
        self.assertEqual(pinned._source_id, device)
        await self.registry.edit(device, routing_mode="auto")
        self.assertEqual(
            self.registry.candidates(loaded._source_id), [device, "OpenAI Subscribe"]
        )
        with self.assertRaises(fixtures.store.CredentialSourceError):
            await self.registry.edit(device, delete=True)
        await self.registry.update_routing("OpenAI Subscribe")
        await self.registry.edit(device, delete=True)
        self.assertEqual(loaded._source_id, "OpenAI Subscribe")

    async def test_failed_routing_save_keeps_committed_policy(self):
        await self.registry.migrate()
        device = self.registry.owned()[1]["id"]
        before = deepcopy(self.conf)

        async def fail():
            self.assertEqual(
                self.registry.resolve_model("new", "OpenAI Subscribe"),
                "OpenAI Subscribe",
            )
            raise OSError("disk unavailable")

        with (
            patch.object(self.conf, "save_config_async", new=fail),
            self.assertRaises(fixtures.store.CredentialPersistenceError),
        ):
            await self.registry.update_routing(device)
        self.assertEqual(self.conf, before)
        with (
            patch.object(
                self.conf,
                "save_config_async",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await self.registry.update_routing(device)
        self.assertEqual(self.conf, before)
        with (
            patch.object(
                self.conf, "save_config_async", new=AsyncMock(return_value=False)
            ),
            self.assertRaises(fixtures.store.CredentialPersistenceError),
        ):
            await self.registry.update_routing(device)
        self.assertEqual(self.conf, before)

    async def test_routing_api_validates_and_never_returns_credentials(self):
        await self.registry.migrate()
        before = deepcopy(self.conf)
        for body in (
            {},
            [],
            {"account_id": False},
            {"account_id": "unknown"},
            {"account_id": None},
            {"account_id": "OpenAI Subscribe", "model_id": None},
            {"account_id": None, "model_id": "unknown"},
            {"account_id": "OpenAI Subscribe", "extra": 1},
        ):
            with request_context(body):
                response = await fixtures.web_api._handle_routing_update()
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.conf, before)
        device = self.registry.owned()[1]["id"]
        with request_context({"account_id": device}):
            result = payload(await fixtures.web_api._handle_routing_update())
        self.assertEqual(result["routing"]["default_account_id"], device)
        self.assertNotIn(self.creds["access_token"], json.dumps(result))
        with request_context():
            self.assertEqual(await fixtures.web_api._requested_source_id(), device)

    async def test_removal_clears_deleted_model_preferences_and_rolls_back(self):
        await self.registry.migrate()
        device = self.registry.owned()[1]["id"]
        await self.registry.update_routing(device, model_id="existing-model")
        self.conf["provider"] = []
        before = deepcopy(self.conf)
        with (
            patch.object(
                self.conf, "save_config_async", new=AsyncMock(side_effect=OSError)
            ),
            self.assertRaises(fixtures.store.CredentialPersistenceError),
        ):
            await self.registry.edit(device, delete=True)
        self.assertEqual(self.conf, before)
        await self.registry.edit(device, delete=True)
        self.assertNotIn("existing-model", self.registry.routing()["models"])
        self.assertEqual(
            self.registry.resolve_model("existing-model", "OpenAI Subscribe"),
            "OpenAI Subscribe",
        )

    async def test_refresh_updates_nested_account_without_adding_source(self):
        await self.registry.migrate()
        device = self.registry.owned()[1]["id"]
        refreshed = {**self.creds, "access_token": fixtures.jwt("refreshed")}
        self.coordinator.update_refresh_credentials(AsyncMock(return_value=refreshed))
        snapshot = await self.coordinator.get_snapshot(device, force_refresh=True)
        self.assertEqual(snapshot.access_token, refreshed["access_token"])
        self.assertEqual(
            json.loads(self.registry.owned()[1]["key"])["access_token"],
            refreshed["access_token"],
        )
        self.assertEqual(len(self.conf["provider_sources"]), 1)


if __name__ == "__main__":
    unittest.main()
