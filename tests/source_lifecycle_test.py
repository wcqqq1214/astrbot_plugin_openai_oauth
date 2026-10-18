"""Regressions for AstrBot reload and stale dashboard source snapshots."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import httpx
import provider_registry_test as fixtures
from astrbot.core.provider.manager import ProviderManager
from astrbot.dashboard.services.config_service import ProviderConfigService

runtime = fixtures.runtime
provider_module = importlib.import_module(f"{fixtures.plugin.__package__}.src.provider")
source_editor = importlib.import_module(
    f"{fixtures.plugin.__package__}.src.source_editor"
)


class SourceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.RegistryTests.setUp(self)
        self.conf["provider_settings"] = {}
        self.conf["provider"][0].update(enable=True, model="test-model")
        self.original.update(
            provider_type="chat_completion", api_base="https://example.invalid"
        )
        self.coordinator._default_source_factory = lambda: {
            **self.original,
            "key": "",
            "proxy": "",
        }
        manager_config = SimpleNamespace(
            confs={"default": self.conf}, default_conf=self.conf
        )
        self.manager = ProviderManager(
            manager_config, None, SimpleNamespace(default_persona="")
        )
        self.context = SimpleNamespace(provider_manager=self.manager)
        self.service = ProviderConfigService(
            SimpleNamespace(astrbot_config=self.conf, provider_manager=self.manager)
        )
        self.coordinator.providers.on_change = self.sync
        manager_conf = patch("astrbot.core.provider.manager.astrbot_config", self.conf)
        manager_conf.start()
        self.addCleanup(manager_conf.stop)
        save = patch("astrbot.dashboard.services.config_service.save_config")
        save.start()
        self.addCleanup(save.stop)
        self.addCleanup(source_editor.install(self.coordinator))

    def sync(self, sources):
        self.manager.provider_sources_config = sources
        self.manager.providers_config = self.conf["provider"]

    async def asyncTearDown(self):
        for provider_id in list(self.manager.inst_map):
            await self.manager.terminate_provider(provider_id)

    async def test_reload_replaces_retained_instances_and_existing_model_can_infer(
        self,
    ):
        # A retained class represents a provider loaded before plugin modules were purged.
        class RetainedProvider(provider_module.ProviderOpenAICodex):
            async def text_chat(self, **kwargs):
                raise fixtures.store.CredentialsNotConfiguredError("Old source reader")

        old = RetainedProvider({**self.original, **self.conf["provider"][0]}, {})
        self.manager.inst_map["existing-model"] = old
        self.manager.provider_insts.append(old)
        self.manager.curr_provider_inst = old
        with self.assertRaises(fixtures.store.CredentialsNotConfiguredError):
            await old.text_chat(prompt="test")
        await runtime.initialize(self.context)
        current = self.manager.inst_map["existing-model"]
        self.assertIsNot(current, old)
        self.assertIs(type(current), provider_module.ProviderOpenAICodex)
        self.assertIs(self.manager.curr_provider_inst, current)
        self.assertEqual(len(self.manager.provider_insts), 1)
        device = self.registry.owned()[1]["id"]
        await self.registry.update_routing(device, model_id="existing-model")
        seen = []

        async def respond(request):
            seen.append(request.headers["authorization"])
            events = [
                {"type": "response.output_text.delta", "delta": "ok"},
                {
                    "type": "response.completed",
                    "response": {"id": "test", "status": "completed", "output": []},
                },
            ]
            return httpx.Response(
                200,
                text="".join("data: " + json.dumps(e) + "\n\n" for e in events),
                headers={"content-type": "text/event-stream"},
            )

        current._create_http_client = lambda config: httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        )
        result = await current.text_chat(prompt="test")
        self.assertEqual(result.completion_text, "ok")
        self.assertEqual(seen, ["Bearer " + self.creds["access_token"]])

    async def test_startup_does_not_load_models_before_provider_manager(self):
        with patch.object(self.manager, "reload", new=AsyncMock()) as reload:
            await runtime.initialize(self.context)
        reload.assert_not_awaited()

    async def test_migration_preserves_effective_model_timeout_and_request_body(self):
        self.coordinator._default_source_factory = runtime._build_default_source_config
        first = self.conf["provider_sources"][0]
        first.update(
            proxy="",
            timeout=240,
            custom_extra_body={"reasoning": {"effort": "high"}},
        )
        second = {
            **deepcopy(first),
            "id": "work",
            "credential_mode": "device_oauth",
            "timeout": 360,
            "custom_extra_body": {"text": {"verbosity": "low"}},
        }
        self.conf["provider_sources"].append(second)
        self.conf["provider"].extend(
            [
                {
                    "id": "work-model",
                    "provider_source_id": "work",
                    "model": "test-model",
                },
                {
                    "id": "explicit-model",
                    "provider_source_id": "work",
                    "model": "test-model",
                    "timeout": 90,
                    "custom_extra_body": {},
                },
                {"id": "other", "provider_source_id": "unrelated"},
            ]
        )
        before = [
            self.manager.get_merged_provider_config(model)
            for model in self.conf["provider"]
        ]
        await self.registry.migrate()
        for model, original in zip(self.conf["provider"][:-1], before[:-1]):
            merged = self.manager.get_merged_provider_config(model)
            current = provider_module.ProviderOpenAICodex(merged, {})
            seen = []

            async def respond(request, seen=seen):
                seen.append(
                    (json.loads(request.content), request.extensions["timeout"])
                )
                events = [
                    {"type": "response.output_text.delta", "delta": "ok"},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "test",
                            "status": "completed",
                            "output": [],
                        },
                    },
                ]
                return httpx.Response(
                    200,
                    text="".join("data: " + json.dumps(e) + "\n\n" for e in events),
                    headers={"content-type": "text/event-stream"},
                )

            current._create_http_client = lambda config: httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            )
            try:
                self.assertEqual(current.timeout, original["timeout"])
                self.assertEqual(
                    current.provider_config["custom_extra_body"],
                    original["custom_extra_body"],
                )
                result = await current.text_chat(prompt="test")
                self.assertEqual(result.completion_text, "ok")
                self.assertEqual(len(seen), 1)
                body, timeout = seen[0]
                self.assertEqual(timeout["read"], original["timeout"])
                for key in ("reasoning", "text"):
                    self.assertEqual(
                        body.get(key), original["custom_extra_body"].get(key)
                    )
                self.assertNotIn("key", model)
                self.assertNotIn("proxy", model)
            finally:
                await current.terminate()
        self.assertEqual(self.conf["provider"][-1], before[-1])
        # Neither the account copy nor later gateway edits overwrite migrated model values.
        self.registry.gateway()["timeout"] = 180
        self.registry.gateway()["custom_extra_body"] = {"reasoning": {"effort": "low"}}
        snapshot = deepcopy(self.conf)
        await self.registry.migrate()
        self.assertEqual(self.conf, snapshot)
        first["custom_extra_body"]["reasoning"]["effort"] = "low"
        self.assertEqual(
            self.conf["provider"][0]["custom_extra_body"]["reasoning"]["effort"], "high"
        )

    async def test_reload_failure_is_not_reported_as_success(self):
        self.manager.inst_map["existing-model"] = SimpleNamespace(terminate=AsyncMock())
        with (
            patch.object(self.manager, "reload", new=AsyncMock()),
            self.assertRaises(RuntimeError),
        ):
            await runtime.initialize(self.context)

    def pre_repair_gateway(self):
        """Build a legacy gateway with account settings but no origin history."""
        self.coordinator._default_source_factory = runtime._build_default_source_config
        account = {
            **deepcopy(self.original),
            "proxy": "",
            "credential_mode": "device_oauth",
            "timeout": 240,
            "custom_extra_body": {"reasoning": {"effort": "high"}},
        }
        gateway = {
            **runtime._build_default_source_config(),
            "oauth_gateway": True,
            "oauth_accounts": [account],
            "oauth_routing": {
                "default_account_id": account["id"],
                "models": {"existing-model": account["id"]},
            },
        }
        self.conf["provider_sources"] = [gateway]
        self.sync(self.conf["provider_sources"])
        return gateway

    async def test_upgrade_skips_unproven_settings_and_reloads_model(self):
        self.pre_repair_gateway()
        before = deepcopy(self.conf["provider"])
        old = provider_module.ProviderOpenAICodex(
            self.manager.get_merged_provider_config(self.conf["provider"][0]), {}
        )
        self.manager.inst_map["existing-model"] = old
        self.manager.provider_insts.append(old)
        self.assertEqual(old.timeout, 120)
        await runtime.initialize(self.context)
        current = self.manager.inst_map["existing-model"]
        self.assertIsNot(current, old)
        self.assertEqual(current.timeout, 120)
        self.assertNotIn("custom_extra_body", current.provider_config)
        self.assertEqual(self.conf["provider"], before)
        self.assertEqual(len(self.conf["provider_sources"]), 1)

    async def test_upgrade_preserves_explicit_model_and_gateway_settings(self):
        for location in ("model", "gateway"):
            with self.subTest(location=location):
                gateway = self.pre_repair_gateway()
                model = self.conf["provider"][0]
                model.pop("timeout", None)
                model.pop("custom_extra_body", None)
                target = model if location == "model" else gateway
                # Explicit defaults and an empty body are intentional settings too.
                target.update(timeout=120, custom_extra_body={})
                before = deepcopy(model)
                await self.registry.migrate()
                self.assertEqual(self.conf["provider"][0], before)
                merged = self.manager.get_merged_provider_config(
                    self.conf["provider"][0]
                )
                self.assertEqual(merged["timeout"], 120)
                self.assertEqual(merged["custom_extra_body"], {})

    async def test_upgrade_keeps_new_model_settings_when_pinned_to_old_account(self):
        self.pre_repair_gateway()
        with patch.object(self.conf, "save_config", create=True):
            await self.service.create_provider(
                {"id": "new-after-migration", "model": "test-model", "enable": True},
                source_id="OpenAI Subscribe",
            )
        await self.registry.update_routing(
            "OpenAI Subscribe", model_id="new-after-migration"
        )
        before = deepcopy(self.conf["provider"][-1])
        await runtime.initialize(self.context)
        self.assertEqual(self.conf["provider"][-1], before)
        current = self.manager.inst_map["new-after-migration"]
        self.assertEqual(current.timeout, 120)
        self.assertNotIn("custom_extra_body", current.provider_config)

    async def test_upgrade_does_not_restore_from_a_changed_account_binding(self):
        gateway = self.pre_repair_gateway()
        account = deepcopy(gateway["oauth_accounts"][0])
        account.update(
            id="work", timeout=360, custom_extra_body={"reasoning": {"effort": "low"}}
        )
        gateway["oauth_accounts"].append(account)
        await self.registry.update_routing("work", model_id="existing-model")
        before = deepcopy(self.conf["provider"])
        await self.registry.migrate()
        self.assertEqual(self.conf["provider"], before)
        self.assertEqual(self.registry.resolve_model("existing-model", ""), "work")

    async def test_upgrade_preserves_saved_values_and_later_removals(self):
        gateway = self.pre_repair_gateway()
        gateway["timeout"] = 90
        gateway["oauth_routing"]["inference_settings_migrated"] = True
        self.conf["provider"][0]["custom_extra_body"] = {
            "reasoning": {"effort": "high"}
        }
        await self.registry.migrate()
        model = self.conf["provider"][0]
        self.assertNotIn("timeout", model)
        self.assertEqual(model["custom_extra_body"], {"reasoning": {"effort": "high"}})
        # A later source save may come from an editor without the private marker.
        stale = deepcopy(self.registry.gateway())
        stale["oauth_routing"] = {
            "default_account_id": "OpenAI Subscribe",
            "models": {},
        }
        await self.service.upsert_provider_source("OpenAI Subscribe", stale)
        model.pop("custom_extra_body")
        self.registry.gateway().pop("timeout")
        self.conf["provider"].append(
            {"id": "later-model", "provider_source_id": "OpenAI Subscribe"}
        )
        await self.registry.update_routing("OpenAI Subscribe", model_id="later-model")
        snapshot = deepcopy(self.conf)
        await self.registry.migrate()
        self.assertEqual(self.conf, snapshot)

    async def test_upgrade_never_uses_legacy_markers_as_origin_evidence(self):
        gateway = self.pre_repair_gateway()
        account = deepcopy(gateway["oauth_accounts"][0])
        account.update(
            id="work", timeout=360, custom_extra_body={"text": {"verbosity": "low"}}
        )
        gateway["oauth_accounts"].append(account)
        gateway["oauth_routing"]["models"]["work-model"] = "work"
        self.conf["provider"].append(
            {"id": "work-model", "provider_source_id": "OpenAI Subscribe"}
        )
        before = deepcopy(self.conf["provider"])
        for marker in (None, False, True):
            with self.subTest(marker=marker):
                self.registry.gateway()["oauth_routing"][
                    "inference_settings_migrated"
                ] = marker
                await self.registry.migrate()
                self.assertEqual(self.conf["provider"], before)
                self.assertIs(
                    self.registry.routing()["inference_settings_migrated"], marker
                )

    async def test_upgrade_does_not_infer_settings_for_unbound_or_unrelated_models(
        self,
    ):
        gateway = self.pre_repair_gateway()
        gateway["oauth_routing"]["models"] = {
            "missing-account-model": "deleted-account",
            "other": "OpenAI Subscribe",
        }
        self.conf["provider"].extend(
            [
                {"id": "new-model", "provider_source_id": "OpenAI Subscribe"},
                {
                    "id": "missing-account-model",
                    "provider_source_id": "OpenAI Subscribe",
                },
                {"id": "other", "provider_source_id": "deepseek"},
            ]
        )
        before = deepcopy(self.conf["provider"])
        await self.registry.migrate()
        self.assertEqual(self.conf["provider"], before)

    async def test_failed_gateway_upgrade_rolls_back_and_retries(self):
        self.pre_repair_gateway()
        before = deepcopy(self.conf)
        with (
            patch.object(
                self.conf, "save_config_async", new=AsyncMock(side_effect=OSError)
            ),
            self.assertRaises(fixtures.store.CredentialPersistenceError),
        ):
            await self.registry.migrate()
        self.assertEqual(self.conf, before)
        await self.registry.migrate()
        self.assertEqual(self.conf["provider"], before["provider"])
        snapshot = deepcopy(self.conf)
        saves = self.conf.saved
        await self.registry.migrate()
        self.assertEqual(self.conf, snapshot)
        self.assertEqual(self.conf.saved, saves)

    async def test_stale_source_save_preserves_added_account_rotation_and_routing(self):
        await self.registry.migrate()
        stale = deepcopy(self.registry.gateway())
        await self.registry.save_login("new-account", "New", self.creds, creating=True)
        rotated = {**self.creds, "access_token": fixtures.jwt("rotated")}
        await self.registry.save_login("new-account", "New", rotated, creating=False)
        await self.registry.update_routing("new-account")
        await self.registry.update_routing("new-account", model_id="existing-model")
        before = deepcopy(self.registry.gateway())
        stale["proxy"] = "http://updated:8080"
        await self.service.upsert_provider_source("OpenAI Subscribe", stale)
        self.assertEqual(
            self.registry.gateway(), {**before, "proxy": "http://updated:8080"}
        )
        self.assertEqual(len(self.conf["provider_sources"]), 1)
        self.assertEqual(
            self.registry.resolve_model("existing-model", ""), "new-account"
        )

    async def test_stale_source_save_does_not_resurrect_deleted_account(self):
        await self.registry.migrate()
        stale = deepcopy(self.registry.gateway())
        device = self.registry.owned()[1]["id"]
        await self.registry.edit(device, delete=True)
        await self.service.upsert_provider_source("OpenAI Subscribe", stale)
        self.assertNotIn(device, [a["id"] for a in self.registry.sources()])
        for key in ("oauth_gateway", "oauth_accounts", "oauth_routing"):
            stale.pop(key)
        await self.service.upsert_provider_source("OpenAI Subscribe", stale)
        self.assertEqual(len(self.registry.sources()), 1)

    async def test_source_save_waits_for_inflight_token_refresh(self):
        await self.registry.migrate()
        stale = deepcopy(self.registry.gateway())
        device = self.registry.owned()[1]["id"]
        entered, release = asyncio.Event(), asyncio.Event()
        rotated = {**self.creds, "access_token": fixtures.jwt("rotated")}

        async def refresh(*args):
            entered.set()
            await release.wait()
            return rotated

        self.coordinator.update_refresh_credentials(refresh)
        refreshing = asyncio.create_task(
            self.coordinator.get_snapshot(device, force_refresh=True)
        )
        await entered.wait()
        saving = asyncio.create_task(
            self.service.upsert_provider_source("OpenAI Subscribe", stale)
        )
        await asyncio.sleep(0)
        self.assertFalse(saving.done())
        release.set()
        await asyncio.gather(refreshing, saving)
        self.assertEqual(
            (await self.coordinator.get_snapshot(device)).access_token,
            rotated["access_token"],
        )

    async def test_guard_is_scoped_and_does_not_stack_on_reload(self):
        await self.registry.migrate()
        current = ProviderConfigService.upsert_provider_source
        remove = source_editor.install(self.coordinator)
        self.addCleanup(remove)
        self.assertIs(
            getattr(current, source_editor._ORIGINAL),
            getattr(
                ProviderConfigService.upsert_provider_source, source_editor._ORIGINAL
            ),
        )
        other = {"id": "other", "type": "other", "key": "new-key"}
        await self.service.upsert_provider_source("other", other)
        self.assertEqual(self.conf["provider_sources"][-1], other)
        # Internal account IDs do not reserve names for unrelated adapters.
        reused_id = self.registry.owned()[1]["id"]
        unrelated = {**other, "id": reused_id}
        await self.service.upsert_provider_source(reused_id, unrelated)
        self.assertEqual(self.conf["provider_sources"][-1], unrelated)
        remove()
        self.assertIs(
            ProviderConfigService.upsert_provider_source,
            getattr(current, source_editor._ORIGINAL),
        )

    async def test_gateway_id_cannot_be_renamed_or_retyped(self):
        await self.registry.migrate()
        before = deepcopy(self.conf)
        for changes in (
            {"id": "Subscription renamed"},
            {"type": "openai"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                await self.service.upsert_provider_source(
                    "OpenAI Subscribe", {**deepcopy(self.registry.gateway()), **changes}
                )
            self.assertEqual(self.conf, before)
        await self.registry.migrate()
        self.assertEqual(self.conf, before)
        self.assertEqual(
            self.registry.routing_view()["models"][0]["id"], "existing-model"
        )

    async def test_pre_migration_editor_cannot_recreate_account_source(self):
        legacy = {
            **deepcopy(self.original),
            "id": "openai-oauth-old-device",
            "credential_mode": "device_oauth",
        }
        self.conf["provider_sources"].append(deepcopy(legacy))
        await self.registry.migrate()
        before = deepcopy(self.conf)
        for payload in (
            legacy,
            {**legacy, "id": "OpenAI Subscribe"},
            {"id": legacy["id"], "proxy": "http://updated:8080"},
        ):
            with (
                self.subTest(payload_keys=list(payload)),
                self.assertRaises(ValueError),
            ):
                await self.service.upsert_provider_source(legacy["id"], payload)
            self.assertEqual(self.conf, before)
        await self.registry.migrate()
        self.assertEqual(self.conf, before)

    async def test_deleted_account_and_extra_subscription_sources_are_rejected(self):
        await self.registry.migrate()
        device = deepcopy(self.registry.owned()[1])
        await self.registry.edit(device["id"], delete=True)
        before = deepcopy(self.conf)
        for payload in (device, {**device, "id": "OpenAI Subscribe_2"}):
            with self.subTest(source_id=payload["id"]), self.assertRaises(ValueError):
                await self.service.upsert_provider_source(payload["id"], payload)
            self.assertEqual(self.conf, before)

    async def test_pre_migration_canonical_editor_preserves_migrated_accounts(self):
        stale = deepcopy(self.conf["provider_sources"][0])
        await self.registry.migrate()
        before = deepcopy(self.registry.gateway())
        stale["proxy"] = "http://updated:8080"
        await self.service.upsert_provider_source("OpenAI Subscribe", stale)
        after = self.registry.gateway()
        self.assertEqual(after["id"], "OpenAI Subscribe")
        self.assertEqual(after["key"], "")
        self.assertEqual(after["oauth_accounts"], before["oauth_accounts"])
        self.assertEqual(after["oauth_routing"], before["oauth_routing"])
        self.assertEqual(after["proxy"], stale["proxy"])

    async def test_migration_repairs_previously_renamed_gateway_references(self):
        await self.registry.migrate()
        device = self.registry.owned()[1]["id"]
        await self.registry.update_routing(device, model_id="existing-model")
        self.registry.gateway()["id"] = "Subscription renamed"
        self.conf["provider"][0]["provider_source_id"] = "Subscription renamed"
        await self.registry.migrate()
        self.assertEqual(self.registry.gateway()["id"], "OpenAI Subscribe")
        self.assertEqual(
            self.conf["provider"][0]["provider_source_id"], "OpenAI Subscribe"
        )
        self.assertEqual(self.registry.resolve_model("existing-model", ""), device)
        self.assertEqual(
            self.manager.get_merged_provider_config(self.conf["provider"][0])["type"],
            "OpenAI Subscribe",
        )
        before = deepcopy(self.conf)
        await self.registry.migrate()
        self.assertEqual(self.conf, before)


if __name__ == "__main__":
    unittest.main()
