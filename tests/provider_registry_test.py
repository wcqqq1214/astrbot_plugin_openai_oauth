"""Migration, provider lifecycle and device-session isolation regressions."""

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
from local_codex_test import Config, jwt, local, store
from login_test import payload, plugin, request_context

login = importlib.import_module(f"{plugin.__package__}.src.login")
oauth = importlib.import_module(f"{plugin.__package__}.src.oauth")
runtime = importlib.import_module(f"{plugin.__package__}.src.runtime")
usage_service = importlib.import_module(f"{plugin.__package__}.src.usage")
web_api = importlib.import_module(f"{plugin.__package__}.src.web_api")
credential_seal = importlib.import_module(f"{plugin.__package__}.src.credential_seal")


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.creds = {
            "access_token": jwt("device"),
            "refresh_token": "secret-refresh",
            "account_id": "device",
            "expires": 9999999999,
        }
        self.original = {
            "id": "OpenAI Subscribe",
            "type": "OpenAI Subscribe",
            "key": json.dumps(self.creds),
            "proxy": "http://old-proxy:8080",
            "enable": True,
        }
        self.conf = Config(
            provider_sources=[deepcopy(self.original)],
            provider=[
                {"id": "existing-model", "provider_source_id": "OpenAI Subscribe"}
            ],
        )
        self.local = SimpleNamespace(
            read=lambda: SimpleNamespace(
                credentials={
                    **self.creds,
                    "account_id": "local",
                    "access_token": jwt("local"),
                }
            )
        )
        self.coordinator = local.LocalCredentialCoordinator(
            SimpleNamespace(default_conf=self.conf),
            provider_type="OpenAI Subscribe",
            default_source_id="OpenAI Subscribe",
            default_source_factory=lambda: {**self.original, "key": ""},
            refresh_credentials=AsyncMock(),
            local_store=self.local,
        )
        self.registry = self.coordinator.providers
        patcher = patch.object(
            runtime, "get_coordinator", return_value=self.coordinator
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(login.discard_all_sessions)

    async def test_plaintext_credentials_are_sealed_once(self):
        await self.registry.migrate()
        key_dir = self.enterContext(tempfile.TemporaryDirectory())
        sealer = credential_seal.FernetCredentialSealer(Path(key_dir, "k"))
        self.coordinator.sealer = sealer
        local_source, device = self.registry.owned()
        before = self.coordinator.account_view(device["id"])
        saves = self.conf.saved
        self.assertEqual(await self.registry.seal_stored_credentials(), 1)
        self.assertEqual(self.conf.saved, saves + 1)
        device = self.registry.owned()[1]
        self.assertTrue(store.is_sealed(device["key"]))
        self.assertNotIn("secret-refresh", json.dumps(self.conf))
        self.assertEqual(local_source["key"], "")
        self.assertEqual(self.coordinator.account_view(device["id"]), before)
        snapshot = await self.coordinator.get_snapshot(device["id"])
        self.assertEqual(snapshot.refresh_token, "secret-refresh")
        self.assertEqual(await self.registry.seal_stored_credentials(), 0)
        self.assertEqual(self.conf.saved, saves + 1)

        # Cooldowns and refreshes keep the record sealed.
        await self.coordinator.mark_cooling(device["id"], 9999999999)
        self.assertTrue(store.is_sealed(self.registry.owned()[1]["key"]))

        # Without the key the account is shown as invalid, never as logged in.
        self.coordinator.sealer = credential_seal.FernetCredentialSealer(
            Path(key_dir, "other")
        )
        self.assertEqual(
            self.coordinator.account_view(device["id"])["status"], "invalid"
        )
        self.assertFalse(Path(key_dir, "other").exists())

    async def test_local_active_migration_preserves_model_and_saved_login(self):
        model = deepcopy(self.conf["provider"])
        await self.registry.migrate()
        local_source, device = self.registry.owned()
        self.assertEqual(local_source["id"], "OpenAI Subscribe")
        self.assertEqual(local_source["key"], "")
        self.assertEqual(json.loads(device["key"]), self.creds)
        self.assertEqual(device["proxy"], self.original["proxy"])
        self.assertNotEqual(device["id"], local_source["id"])
        self.assertEqual(self.conf["provider"], model)
        snapshot = deepcopy(self.conf)
        await self.registry.migrate()
        self.assertEqual(self.conf, snapshot)
        self.assertEqual(self.conf.saved, 1)
        self.assertTrue(
            all(
                self.registry.routing_mode(s["id"]) == "fixed"
                for s in self.registry.owned()
            )
        )
        self.assertEqual((await self.coordinator.get_snapshot()).account_id, "local")
        self.assertEqual(
            (await self.coordinator.get_snapshot(device["id"])).account_id, "device"
        )

    async def test_enabled_patch_preserves_credentials_health_and_binding(self):
        await self.registry.migrate()
        device = self.registry.owned()[1]
        sid = device["id"]
        await self.coordinator.mark_cooling(sid, 9999999999)
        before = deepcopy(device)
        models = deepcopy(self.conf["provider"])
        for enabled in (False, False, True):
            with request_context({"source_id": sid, "enabled": enabled}):
                result = payload(await web_api._handle_provider_update())
            self.assertEqual(result["provider"]["enabled"], enabled)
            self.assertEqual(result["provider"]["status"], "cooling")
            self.assertEqual(device, {**before, "enable": enabled})
            self.assertEqual(self.conf["provider"], models)
        await self.registry.edit("OpenAI Subscribe", enabled=False)
        self.assertFalse(self.coordinator.account_view()["enabled"])
        self.assertEqual((await self.coordinator.get_snapshot()).account_id, "local")
        with self.assertRaises(store.ProviderDisabledError):
            self.registry.ensure_enabled("OpenAI Subscribe")

    async def test_enabled_migration_and_strict_validation(self):
        self.conf["provider_sources"][0]["enable"] = False
        await self.registry.migrate()
        self.assertTrue(all(not s["enable"] for s in self.registry.owned()))
        del self.registry.owned()[1]["enable"]
        await self.registry.migrate()
        self.assertTrue(self.registry.owned()[1]["enable"])
        self.assertFalse(self.registry.owned()[0]["enable"])
        before = deepcopy(self.conf)
        for values in (
            {"enabled": None},
            {"enabled": 1},
            {"enabled": "false"},
            {"name": None},
            {},
            {"enable": False},
        ):
            with request_context({"source_id": "OpenAI Subscribe", **values}):
                response = await web_api._handle_provider_update()
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.conf, before)

    async def test_failed_enable_save_keeps_committed_dispatch_policy(self):
        await self.registry.migrate()
        sid = "OpenAI Subscribe"
        await self.registry.edit(sid, enabled=False)

        async def fail_save():
            self.assertFalse(self.registry.enabled(sid))
            raise OSError("save failed")

        with (
            patch.object(self.conf, "save_config_async", new=fail_save),
            self.assertRaises(store.CredentialPersistenceError),
        ):
            await self.registry.edit(sid, enabled=True)
        self.assertFalse(self.registry.enabled(sid))

    async def test_disabled_source_blocks_loaded_adapter_before_inference(self):
        await self.registry.migrate()
        provider = object.__new__(plugin.ProviderOpenAICodex)
        provider._source_id = "OpenAI Subscribe"
        provider._request_client = AsyncMock()
        await self.registry.edit(provider._source_id, enabled=False)
        with self.assertRaises(store.ProviderDisabledError):
            _ = [
                item
                async for item in provider._stream_with_current_credentials(
                    {}, None, request_max_retries=1
                )
            ]
        provider._request_client.assert_not_called()

    async def test_disabling_during_refresh_blocks_dispatch(self):
        await self.registry.migrate()
        sid = "OpenAI Subscribe"
        original = self.coordinator.get_snapshot

        async def get_snapshot(*args, **kwargs):
            snapshot = await original(*args, **kwargs)
            await self.registry.edit(sid, enabled=False)
            return snapshot

        provider = object.__new__(plugin.ProviderOpenAICodex)
        provider._source_id = sid
        provider._request_client = AsyncMock()
        with (
            patch.object(self.coordinator, "get_snapshot", new=get_snapshot),
            self.assertRaises(store.ProviderDisabledError),
        ):
            _ = [
                item
                async for item in provider._stream_with_current_credentials(
                    {}, None, request_max_retries=1
                )
            ]
        provider._request_client.assert_not_called()

    async def test_saved_login_keeps_id_when_following_off_or_local_missing(self):
        for follow in (True, False):
            for present in (True, False):
                if follow and present:
                    continue
                self.conf["provider_sources"][:] = [deepcopy(self.original)]
                self.coordinator.legacy_follow_local = follow
                self.coordinator.local_store = self.local if present else None
                await self.registry.migrate()
                local_source, device = self.registry.owned()
                self.assertEqual(device["id"], "OpenAI Subscribe")
                self.assertEqual(local_source["credential_mode"], "local_codex")
                self.assertEqual(
                    (await self.coordinator.get_snapshot()).account_id, "device"
                )
                self.assertEqual(
                    self.conf["provider"][0]["provider_source_id"], device["id"]
                )
                self.coordinator.local_store = self.local
                await self.registry.migrate()
                self.assertEqual(
                    (await self.coordinator.get_snapshot()).account_id, "device"
                )

    async def test_fresh_install_and_legacy_custom_sources(self):
        self.conf["provider_sources"][:] = []
        self.coordinator.local_store = None
        await self.registry.migrate()
        self.assertEqual(len(self.registry.owned()), 1)
        self.assertEqual(self.registry.owned()[0]["credential_mode"], "local_codex")
        self.conf["provider_sources"].append({**self.original, "id": "custom"})
        self.conf["provider_sources"].append(
            {"id": "unrelated", "type": "other", "key": "untouched"}
        )
        await self.registry.migrate()
        self.assertEqual(
            self.coordinator.source("custom")["credential_mode"], "device_oauth"
        )
        self.assertEqual(self.conf["provider_sources"][-1]["key"], "untouched")

    async def test_migration_preserves_invalid_credentials_for_reauthorization(self):
        self.conf["provider_sources"][0]["key"] = "unsupported-old-credential"
        await self.registry.migrate()
        device = self.registry.owned()[1]
        self.assertEqual(device["key"], "unsupported-old-credential")
        self.assertEqual(
            self.coordinator.account_view(device["id"])["status"], "invalid"
        )

    async def test_failed_migration_rolls_back_and_can_retry(self):
        before = deepcopy(self.conf)
        with (
            patch.object(
                self.conf, "save_config_async", new=AsyncMock(side_effect=OSError)
            ),
            self.assertRaises(store.CredentialPersistenceError),
        ):
            await self.registry.migrate()
        self.assertEqual(self.conf, before)
        await self.registry.migrate()
        self.assertEqual(len(self.registry.owned()), 2)

    async def test_rejected_duplicate_ids_leave_configuration_untouched(self):
        self.conf["provider_sources"].append(deepcopy(self.original))
        before = deepcopy(self.conf)
        with self.assertRaises(store.CredentialSourceError):
            await self.registry.migrate()
        self.assertEqual(self.conf, before)

    async def test_independent_creation_rename_delete_and_bound_model_protection(self):
        await self.registry.migrate()
        before = deepcopy(self.conf["provider_sources"])
        await self.registry.save_login("new", "Work", self.creds, creating=True)
        self.assertEqual(len(self.conf["provider_sources"]), 1)
        self.assertEqual(self.registry.sources()[:-1], before[0]["oauth_accounts"])
        await self.registry.edit("new", name="Personal")
        self.assertEqual(self.coordinator.source("new")["name"], "Personal")
        self.conf["provider"].append({"id": "new-model", "provider_source_id": "new"})
        with self.assertRaises(store.CredentialSourceError):
            await self.registry.edit("new", delete=True)
        self.conf["provider"].pop()
        await self.registry.edit("new", delete=True)
        with self.assertRaises(store.CredentialSourceError):
            await self.registry.save_login("new", "Work", self.creds, creating=False)
        with self.assertRaises(store.CredentialSourceError):
            await self.registry.edit("OpenAI Subscribe", delete=True)
        with self.assertRaises(store.CredentialSourceError):
            await self.registry.save_login(
                "OpenAI Subscribe", "Local", self.creds, creating=False
            )

    async def test_save_failure_does_not_report_or_leave_new_provider(self):
        await self.registry.migrate()
        before = deepcopy(self.conf)
        with (
            patch.object(
                self.conf, "save_config_async", new=AsyncMock(return_value=False)
            ),
            self.assertRaises(store.CredentialPersistenceError),
        ):
            await self.registry.save_login("new", "Work", self.creds, creating=True)
        self.assertEqual(self.conf, before)

    async def test_web_login_new_provider_and_reauthorization_are_scoped(self):
        await self.registry.migrate()
        before = deepcopy(self.conf["provider_sources"])

        async def complete(body):
            with request_context(body):
                started = payload(await web_api._handle_device_start())
            session = login._login_sessions[started["session_id"]]
            await session.task
            with request_context({"session_id": started["session_id"]}):
                return payload(await web_api._handle_device_poll())

        with (
            patch.object(
                oauth,
                "request_device_user_code",
                new=AsyncMock(return_value=("d", "code", 1)),
            ),
            patch.object(
                login, "_complete_device_login", new=AsyncMock(return_value=self.creds)
            ),
        ):
            one = await complete({"name": "One"})
            two = await complete({"name": "Two"})
            self.assertNotEqual(one["source_id"], two["source_id"])
            self.assertEqual(len(self.conf["provider_sources"]), 1)
            self.assertEqual(self.registry.sources()[:2], before[0]["oauth_accounts"])
            same = await complete({"source_id": one["source_id"], "name": "ignored"})
            self.assertEqual(same["source_id"], one["source_id"])
            self.assertEqual(self.coordinator.source(one["source_id"])["name"], "One")
            self.assertEqual(len(self.registry.owned()), 4)
            with request_context({"source_id": "OpenAI Subscribe"}):
                self.assertEqual(
                    (await web_api._handle_device_start()).status_code, 400
                )

    async def test_listing_and_usage_are_scoped_and_do_not_expose_tokens(self):
        await self.registry.migrate()
        with request_context():
            listing = payload(await web_api._handle_providers_list())
        self.assertEqual(listing["providers"][0]["credential_mode"], "local_codex")
        for secret in (self.creds["access_token"], self.creds["refresh_token"]):
            self.assertNotIn(secret, json.dumps(listing))
        device_id = listing["providers"][1]["id"]
        with (
            patch.object(
                oauth, "fetch_rate_limits", new=AsyncMock(return_value={"windows": []})
            ) as fetch,
            request_context({"source_id": device_id}),
        ):
            result = payload(await web_api._handle_account_usage())
        self.assertEqual(
            fetch.call_args.args[:2], (self.creds["access_token"], "device")
        )
        self.assertEqual(result["account"]["id"], device_id)
        self.assertNotIn("backup_status", result["account"])

    async def test_usage_cooldown_does_not_follow_a_replaced_login(self):
        await self.registry.migrate()
        sid = self.registry.owned()[1]["id"]
        exhausted = {
            "allowed": False,
            "limit_reached": True,
            "windows": [{"used_percent": 100, "reset_at": 9999999999}],
        }
        replacement = {
            **self.creds,
            "access_token": jwt("replacement"),
            "account_id": "replacement",
        }
        for cached in (False, True):
            with self.subTest(cached=cached):
                await self.registry.save_login(
                    sid, "ChatGPT", self.creds, creating=False
                )
                if cached:
                    await self.coordinator.get_usage(
                        sid, AsyncMock(return_value=exhausted)
                    )
                saving_started, cooling_started = asyncio.Event(), asyncio.Event()
                mark_cooling = self.coordinator.mark_cooling

                async def replace_login(started=saving_started):
                    started.set()
                    await self.registry.save_login(
                        sid, "ChatGPT", replacement, creating=False
                    )

                async def delayed_cooling(
                    *args, started=cooling_started, mark=mark_cooling, **kwargs
                ):
                    started.set()
                    return await mark(*args, **kwargs)

                tasks = []
                try:
                    with (
                        patch.object(
                            oauth,
                            "fetch_rate_limits",
                            new=AsyncMock(return_value=exhausted),
                        ) as fetch,
                        patch.object(
                            self.coordinator,
                            "mark_cooling",
                            side_effect=delayed_cooling,
                        ),
                    ):
                        # Queue the new login before the old usage result writes its cooldown.
                        async with self.coordinator.source_lock(sid):
                            tasks.append(asyncio.create_task(replace_login()))
                            await asyncio.wait_for(saving_started.wait(), 5)
                            tasks.append(
                                asyncio.create_task(
                                    usage_service.fetch_source_usage(sid)
                                )
                            )
                            await asyncio.wait_for(cooling_started.wait(), 5)
                        await asyncio.gather(*tasks)
                        self.assertEqual(fetch.await_count, 0 if cached else 1)
                    snapshot = self.coordinator.read_snapshot(sid)
                    self.assertEqual(snapshot.account_id, "replacement")
                    self.assertFalse(snapshot.is_cooling_down())
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

    async def test_usage_cooldown_uses_refreshed_credentials(self):
        await self.registry.migrate()
        sid = self.registry.owned()[1]["id"]
        expired = {**self.creds, "access_token": jwt("device", expires=1), "expires": 1}
        await self.registry.save_login(sid, "ChatGPT", expired, creating=False)
        refreshed = {**self.creds, "access_token": jwt("device", generation=1)}
        exhausted = {
            "allowed": False,
            "windows": [{"used_percent": 100, "reset_at": 9999999999}],
        }
        with (
            patch.object(
                self.coordinator,
                "_refresh_credentials",
                new=AsyncMock(return_value=refreshed),
            ),
            patch.object(
                oauth, "fetch_rate_limits", new=AsyncMock(return_value=exhausted)
            ) as fetch,
        ):
            await usage_service.fetch_source_usage(sid)
        self.assertEqual(fetch.call_args.args[0], refreshed["access_token"])
        self.assertTrue(self.coordinator.read_snapshot(sid).is_cooling_down())

    async def test_cancellation_cannot_interrupt_a_started_save(self):
        await self.registry.migrate()
        entered, release = asyncio.Event(), asyncio.Event()
        save = self.registry.save_login

        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            await save(*args, **kwargs)

        with (
            patch.object(
                oauth,
                "request_device_user_code",
                new=AsyncMock(return_value=("d", "code", 1)),
            ),
            patch.object(
                login, "_complete_device_login", new=AsyncMock(return_value=self.creds)
            ),
            patch.object(self.registry, "save_login", new=delayed),
        ):
            with request_context({"name": "Saving"}):
                started = payload(await web_api._handle_device_start())
            task = login._login_sessions[started["session_id"]].task
            await entered.wait()
            with request_context({"session_id": started["session_id"]}):
                self.assertEqual(
                    (await web_api._handle_device_cancel()).status_code, 409
                )
            release.set()
            await task
            with request_context({"session_id": started["session_id"]}):
                result = payload(await web_api._handle_device_poll())
            self.assertEqual(result["status"], "success")
            self.assertEqual(
                self.coordinator.source(result["source_id"])["name"], "Saving"
            )

    async def test_usage_command_resolves_current_model_source(self):
        event = SimpleNamespace(
            should_call_llm=lambda value: None,
            get_extra=lambda key: "selected-model",
            unified_msg_origin="test:private:user",
            send=AsyncMock(),
        )
        provider = SimpleNamespace(
            meta=lambda: SimpleNamespace(type=runtime.PROVIDER_TYPE),
            _source_id="selected-source",
        )
        instance = SimpleNamespace(
            context=SimpleNamespace(get_provider_by_id=lambda value: provider)
        )
        with patch.object(
            usage_service, "build_usage_message", new=AsyncMock(return_value="quota")
        ) as usage:
            await plugin.OpenAI_OAuth_Plugin.usage(instance, event)
        usage.assert_awaited_once_with("selected-source")

    async def test_new_session_cancelled_before_authorization_leaves_no_provider(self):
        await self.registry.migrate()
        before = deepcopy(self.conf)
        with (
            patch.object(
                oauth,
                "request_device_user_code",
                new=AsyncMock(return_value=("d", "code", 1)),
            ),
            patch.object(
                login, "_complete_device_login", side_effect=lambda **kwargs: None
            ),
        ):
            # Reserve and cancel before the worker gets its first event-loop turn.
            with request_context({"name": "Cancelled"}):
                started = payload(await web_api._handle_device_start())
            task = login._login_sessions[started["session_id"]].task
            with request_context({"session_id": started["session_id"]}):
                self.assertEqual(
                    payload(await web_api._handle_device_cancel())["status"],
                    "cancelled",
                )
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.conf, before)


if __name__ == "__main__":
    unittest.main()
