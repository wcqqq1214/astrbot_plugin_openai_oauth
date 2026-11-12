"""Critical hook preflight, blocked saves, rollback and recovery regressions."""

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
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import local_codex_test as fixtures
import login_test as web_fixtures
from astrbot.dashboard.services.config_service import ProviderConfigService

Config, plugin, runtime = fixtures.Config, fixtures.plugin, fixtures.runtime

editor = importlib.import_module(f"{plugin.__package__}.src.source_editor")


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name in (
            "_config_mgr",
            "_credential_coordinator",
            "_local_codex_store",
            "_credential_sealer",
            "_remove_source_guard",
            "_remove_image_bridge",
            "_startup_error",
        ):
            self.enterContext(patch.object(runtime, name, None))
        self.metadata = deepcopy(runtime.CONFIG_METADATA_2)
        self.enterContext(patch.object(runtime, "CONFIG_METADATA_2", self.metadata))
        self.gateway = {
            "id": runtime.PROVIDER_TYPE,
            "type": runtime.PROVIDER_TYPE,
            "oauth_gateway": True,
            "oauth_accounts": [
                {
                    "id": "account",
                    "type": runtime.PROVIDER_TYPE,
                    "credential_mode": "device_oauth",
                    "key": "private-account-record",
                }
            ],
            "oauth_routing": {"default_account_id": "account", "models": {}},
            "key": "",
        }
        self.conf = Config(provider_sources=[self.gateway], provider=[])
        self.context = SimpleNamespace(
            astrbot_config_mgr=SimpleNamespace(default_conf=self.conf),
            register_web_api=Mock(),
        )
        self.calls = []

        async def save(service, source_id, config):
            self.calls.append((source_id, deepcopy(config)))

        self.base = save
        self.enterContext(
            patch.object(ProviderConfigService, "upsert_provider_source", save)
        )
        self.service = SimpleNamespace(config=self.conf)

    async def save(self, source_id=None, config=None, service=None):
        return await ProviderConfigService.upsert_provider_source(
            service or self.service,
            source_id or runtime.PROVIDER_TYPE,
            config if config is not None else {"id": runtime.PROVIDER_TYPE},
        )

    def fields(self):
        return self.metadata["provider_group"]["metadata"]["provider"]["items"]

    async def assert_blocked(self):
        before = deepcopy(self.conf)
        with self.assertRaisesRegex(editor.HookCompatibilityError, "blocked"):
            runtime.get_coordinator()
        with self.assertRaises(editor.HookCompatibilityError):
            await runtime.initialize(self.context)
        with self.assertRaises(editor.HookCompatibilityError):
            await self.save()
        self.assertEqual(self.conf, before)
        self.assertEqual(self.calls, [])

    async def test_metadata_failure_blocks_subscription_saves_and_plugin_routes(self):
        self.metadata["provider_group"]["metadata"]["provider"]["items"] = []
        with self.assertRaisesRegex(editor.HookCompatibilityError, "metadata"):
            plugin.OpenAI_OAuth_Plugin(self.context, config={})
        self.context.register_web_api.assert_not_called()
        await self.assert_blocked()
        await self.save("other", {"id": "other", "type": "other"})
        self.assertEqual(self.calls, [("other", {"id": "other", "type": "other"})])
        other_service = SimpleNamespace(config=Config())
        await self.save(service=other_service)
        self.assertEqual(len(self.calls), 2)

    async def test_collects_all_missing_contracts_without_mutating_metadata(self):
        self.metadata.clear()
        delattr(ProviderConfigService, "upsert_provider_source")
        with self.assertRaises(editor.HookCompatibilityError) as caught:
            runtime.configure(self.context, {})
        self.assertIn("CONFIG_METADATA_2", str(caught.exception))
        self.assertIn("upsert_provider_source", str(caught.exception))
        self.assertEqual(self.metadata, {})
        await self.assert_blocked()

    async def test_incompatible_signatures_fail_closed(self):
        async def added_required(service, source_id, config, required):
            self.fail("Incompatible hook must not run")

        async def renamed(service, account_id, payload):
            self.fail("Unknown hook semantics must not run")

        def sync(service, source_id, config):
            self.fail("Synchronous hook must not run")

        for hook in (None, added_required, renamed, sync):
            with self.subTest(hook=hook):
                ProviderConfigService.upsert_provider_source = hook
                before = deepcopy(self.metadata)
                with self.assertRaisesRegex(
                    editor.HookCompatibilityError, "upsert_provider_source"
                ):
                    runtime.configure(self.context, {})
                self.assertEqual(self.metadata, before)
                await self.assert_blocked()
                with self.assertRaises(editor.HookCompatibilityError):
                    await self.save("other", {"id": "other", "type": "other"})

    async def test_guard_install_failure_rolls_back_metadata_and_blocks_writes(self):
        self.fields().pop("oauth_accounts", None)
        self.fields()["oauth_gateway"] = {"type": "bool", "custom": "preserve"}
        before = deepcopy(self.metadata)
        with (
            patch.object(editor, "install", side_effect=RuntimeError("private-secret")),
            patch.object(runtime.logger, "error") as log,
            self.assertRaises(editor.HookCompatibilityError) as caught,
        ):
            runtime.configure(self.context, {})
        self.assertEqual(self.metadata, before)
        self.assertNotIn("private-secret", str(caught.exception))
        self.assertNotIn("private-secret", str(log.call_args_list))
        await self.assert_blocked()

    async def test_success_recovery_preserves_records_and_stale_cleanup_is_safe(self):
        correct_fields = self.fields()
        self.metadata["provider_group"]["metadata"]["provider"]["items"] = None
        with self.assertRaises(editor.HookCompatibilityError):
            runtime.configure(self.context, {})
        stale_remove = runtime._remove_source_guard
        runtime.terminate()
        await self.assert_blocked()
        self.metadata["provider_group"]["metadata"]["provider"]["items"] = (
            correct_fields
        )
        with patch.object(runtime.logger, "info") as log:
            runtime.configure(self.context, {})
        self.assertIn("critical hooks ready", str(log.call_args))
        stale_remove()
        coordinator = runtime.get_coordinator()
        self.assertIs(coordinator.config(), self.conf)
        await self.save(
            config={
                "id": runtime.PROVIDER_TYPE,
                "oauth_accounts": [],
                "oauth_routing": {},
                "key": "stale-key",
            }
        )
        self.assertEqual(
            self.calls[-1][1]["oauth_accounts"], self.gateway["oauth_accounts"]
        )
        self.assertEqual(
            self.calls[-1][1]["oauth_routing"], self.gateway["oauth_routing"]
        )
        self.assertEqual(self.calls[-1][1]["key"], "")
        self.assertTrue(
            all(
                self.fields()[key]["invisible"]
                for key in ("oauth_accounts", "oauth_gateway", "oauth_routing")
            )
        )

    async def test_failed_reload_blocks_existing_coordinator_access(self):
        runtime.configure(self.context, {})
        prior = runtime.get_coordinator()
        self.metadata.clear()
        with self.assertRaises(editor.HookCompatibilityError):
            runtime.configure(self.context, {})
        await self.assert_blocked()
        self.assertEqual(prior.config(), self.conf)

    async def test_waiting_save_rechecks_protection_before_writing(self):
        runtime.configure(self.context, {})
        coordinator = runtime.get_coordinator()
        lock = coordinator.source_lock("account")
        await lock.acquire()
        pending = asyncio.create_task(self.save())
        await asyncio.sleep(0)
        self.metadata.clear()
        try:
            with self.assertRaises(editor.HookCompatibilityError):
                runtime.configure(self.context, {})
        finally:
            lock.release()
        with self.assertRaises(editor.HookCompatibilityError):
            await pending
        self.assertEqual(self.calls, [])

    async def test_retained_registry_cannot_save_after_failed_reload(self):
        runtime.configure(self.context, {})
        registry = runtime.get_coordinator().providers
        before = deepcopy(self.conf)
        await registry.lock.acquire()
        pending = asyncio.create_task(registry.edit("account", enabled=False))
        await asyncio.sleep(0)
        self.metadata.clear()
        try:
            with self.assertRaises(editor.HookCompatibilityError):
                runtime.configure(self.context, {})
        finally:
            registry.lock.release()
        with self.assertRaises(fixtures.store.CredentialError):
            await pending
        self.assertEqual(self.conf, before)

    async def test_retained_registry_cannot_commit_routing_after_failed_reload(self):
        self.gateway["oauth_accounts"].append(
            {
                "id": "second",
                "type": runtime.PROVIDER_TYPE,
                "credential_mode": "device_oauth",
                "key": "another-private-record",
            }
        )
        runtime.configure(self.context, {})
        registry = runtime.get_coordinator().providers
        before = deepcopy(self.conf)
        self.metadata.clear()
        with self.assertRaises(editor.HookCompatibilityError):
            runtime.configure(self.context, {})
        with self.assertRaises(fixtures.store.CredentialError):
            await registry.update_routing("second")
        self.assertEqual(self.conf, before)

    async def test_queued_cooldown_cannot_persist_after_failed_reload(self):
        self.gateway["oauth_accounts"][0]["key"] = json.dumps(
            {
                "access_token": fixtures.jwt(),
                "refresh_token": "test-only",
                "expires": 9999999999,
            }
        )
        runtime.configure(self.context, {})
        coordinator = runtime.get_coordinator()
        before = deepcopy(self.conf)
        lock = coordinator.source_lock("account")
        await lock.acquire()
        pending = asyncio.create_task(coordinator.mark_cooling("account", 9999999999))
        await asyncio.sleep(0)
        self.metadata.clear()
        try:
            with self.assertRaises(editor.HookCompatibilityError):
                runtime.configure(self.context, {})
        finally:
            lock.release()
        with self.assertRaises(editor.HookCompatibilityError):
            await pending
        self.assertEqual(self.conf, before)
        self.assertEqual(getattr(self.conf, "saved", 0), 0)

    async def test_inflight_refresh_cannot_persist_after_failed_reload(self):
        self.gateway["oauth_accounts"][0]["key"] = json.dumps(
            {
                "access_token": fixtures.jwt(),
                "refresh_token": "test-only",
                "expires": 1,
            }
        )
        runtime.configure(self.context, {})
        coordinator = runtime.get_coordinator()
        before = deepcopy(self.conf)

        async def refresh(credentials, proxy):
            self.metadata.clear()
            with self.assertRaises(editor.HookCompatibilityError):
                runtime.configure(self.context, {})
            return {**credentials, "expires": 9999999999, "refresh_token": "rotated"}

        coordinator.update_refresh_credentials(refresh)
        with self.assertRaises(editor.HookCompatibilityError):
            await coordinator.get_snapshot("account")
        self.assertEqual(self.conf, before)
        self.assertEqual(getattr(self.conf, "saved", 0), 0)

    async def test_local_refresh_stops_before_dispatch_and_before_file_write(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(directory) / "auth.json"
        path.write_text(json.dumps(fixtures.auth(expires=1)))
        self.gateway["oauth_accounts"][0].update(credential_mode="local_codex", key="")
        config = {"codex_auth_path": str(path)}
        runtime.configure(self.context, config)
        coordinator = runtime.get_coordinator()
        before = path.read_bytes()

        async def refresh(credentials, proxy):
            self.metadata.clear()
            with self.assertRaises(editor.HookCompatibilityError):
                runtime.configure(self.context, config)
            return {
                **credentials,
                "access_token": fixtures.jwt(generation=1),
                "refresh_token": "rotated",
            }

        coordinator.update_refresh_credentials(refresh)
        with self.assertRaises(editor.HookCompatibilityError):
            await coordinator.get_snapshot("account")
        self.assertEqual(path.read_bytes(), before)
        callback = AsyncMock()
        coordinator.update_refresh_credentials(callback)
        with self.assertRaises(editor.HookCompatibilityError):
            await coordinator.get_snapshot("account")
        callback.assert_not_awaited()
        with self.assertRaises(editor.HookCompatibilityError):
            coordinator.ensure_inference_available("account")

    async def test_existing_web_routes_and_usage_report_compatibility_failure(self):
        self.metadata.clear()
        with self.assertRaises(editor.HookCompatibilityError):
            runtime.configure(self.context, {})
        with web_fixtures.request_context():
            response = await web_fixtures.web_api._handle_providers_list()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            web_fixtures.payload(response)["message"], "incompatible_astrbot"
        )
        self.assertEqual(
            fixtures.usage_service.failure_state(
                editor.HookCompatibilityError("blocked")
            ),
            "incompatible",
        )

    async def test_compatible_extra_optional_parameter_is_accepted(self):
        async def compatible(service, source_id, config, *, validate=True):
            self.calls.append((source_id, {**config, "validate": validate}))

        ProviderConfigService.upsert_provider_source = compatible
        runtime.configure(self.context, {})
        await ProviderConfigService.upsert_provider_source(
            self.service, runtime.PROVIDER_TYPE, {}, validate=False
        )
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.calls[0][1]["validate"])


if __name__ == "__main__":
    unittest.main()
