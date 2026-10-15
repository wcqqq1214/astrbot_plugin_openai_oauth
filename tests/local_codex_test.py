"""No-network tests for following local Codex accounts and shared token rotation."""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ASTRBOT_ROOT = Path(__file__).resolve().parents[2] / "AstrBot"
sys.path.insert(0, str(ASTRBOT_ROOT))
os.chdir(ASTRBOT_ROOT)
local = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.local_codex")
store = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.credential_store"
)
plugin = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")


def jwt(account="one", expires=9999999999, generation=0):
    claims = {
        "exp": expires,
        "generation": generation,
        "https://api.openai.com/auth": {"chatgpt_account_id": account},
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def auth(account="one", expires=9999999999, generation=0):
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": jwt(account, expires, generation),
            "refresh_token": f"refresh-{account}-{generation}",
            "id_token": "original-id-token",
            "account_id": account,
        },
        "last_refresh": "2026-01-01T00:00:00Z",
        "future_field": {"preserve": True},
    }


class Config(dict):
    async def save_config_async(self):
        self.saved = getattr(self, "saved", 0) + 1
        return True


class LocalCodexTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "auth.json"
        self.local = local.LocalCodexStore(str(self.path))
        self.backup = {
            "access_token": jwt("backup"),
            "refresh_token": "backup-refresh",
            "account_id": "backup",
            "expires": 9999999999,
        }
        self.source = {
            "id": "OpenAI Subscribe",
            "type": "OpenAI Subscribe",
            "key": "",
            "credential_mode": "local_codex",
            "proxy": "",
        }
        self.device = {
            **self.source,
            "id": "device",
            "credential_mode": "device_oauth",
            "key": json.dumps(self.backup),
        }
        self.conf = Config(provider_sources=[self.source, self.device])
        requested = patch.object(
            plugin,
            "_requested_source_id",
            new=AsyncMock(return_value="OpenAI Subscribe"),
        )
        requested.start()
        self.addCleanup(requested.stop)
        self.refresh = AsyncMock()
        self.coordinator = local.LocalCredentialCoordinator(
            SimpleNamespace(default_conf=self.conf),
            provider_type="OpenAI Subscribe",
            default_source_id="OpenAI Subscribe",
            default_source_factory=lambda: {**self.source, "key": ""},
            refresh_credentials=self.refresh,
            local_store=self.local,
        )

    def write(self, document):
        self.path.write_text(json.dumps(document))

    async def test_switch_logout_and_independent_login(self):
        self.write(auth())
        first = await self.coordinator.get_snapshot()
        self.assertEqual(first.account_id, "one")
        self.assertEqual(first.credential_origin, "local_codex")
        self.write(auth("two"))
        self.assertEqual((await self.coordinator.get_snapshot()).account_id, "two")
        await self.coordinator.providers.save_login(
            "device",
            "ChatGPT",
            {**self.backup, "account_id": "new-device"},
            creating=False,
        )
        self.assertEqual((await self.coordinator.get_snapshot()).account_id, "two")
        self.path.unlink()
        with self.assertRaises(store.ReauthenticationRequiredError):
            await self.coordinator.get_snapshot()
        self.assertEqual(
            (await self.coordinator.get_snapshot("device")).account_id, "new-device"
        )
        self.assertEqual(self.coordinator.credential_origin(), "local_codex")
        self.refresh.assert_not_awaited()

    async def test_missing_invalid_api_key_and_keyring_never_switch_provider(self):
        for document in (
            {},
            [],
            {"auth_mode": "apikey", "OPENAI_API_KEY": "fake"},
            {**auth(), "auth_mode": "chatgptAuthTokens"},
            {**auth(), "tokens": {"access_token": "invalid"}},
        ):
            self.write(document)
            with self.assertRaises(store.ReauthenticationRequiredError):
                await self.coordinator.get_snapshot()
            self.assertEqual(
                (await self.coordinator.get_snapshot("device")).account_id, "backup"
            )
        self.path.write_text('{"tokens":')
        with self.assertRaises(store.ReauthenticationRequiredError):
            await self.coordinator.get_snapshot()
        self.refresh.assert_not_awaited()

    async def test_explicit_modes_and_other_sources(self):
        self.write(auth())
        self.coordinator.local_store = None
        with self.assertRaises(store.ReauthenticationRequiredError):
            await self.coordinator.get_snapshot()
        self.coordinator.local_store = self.local
        self.conf["provider_sources"].append({**self.device, "id": "other"})
        self.assertEqual(
            (await self.coordinator.get_snapshot("other")).account_id, "backup"
        )

    async def test_single_flight_rotation_preserves_file_and_backup(self):
        original = auth(expires=1)
        self.write(original)

        async def refresh(creds, proxy):
            await asyncio.sleep(0)
            return {
                **creds,
                "access_token": jwt(generation=1),
                "refresh_token": "rotated",
                "id_token": "rotated-id",
            }

        self.refresh.side_effect = refresh
        results = await asyncio.gather(
            *(self.coordinator.get_snapshot() for _ in range(8))
        )
        self.assertEqual(self.refresh.await_count, 1)
        self.assertTrue(all(x.access_token == jwt(generation=1) for x in results))
        written = json.loads(self.path.read_text())
        self.assertEqual(written["future_field"], original["future_field"])
        self.assertEqual(written["tokens"]["refresh_token"], "rotated")
        self.assertEqual(written["tokens"]["id_token"], "rotated-id")
        self.assertEqual(json.loads(self.device["key"]), self.backup)
        self.assertEqual(list(self.path.parent.glob(".astrbot-auth-*")), [])
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    async def test_switch_during_refresh_wins(self):
        self.write(auth(expires=1))

        async def refresh(creds, proxy):
            self.write(auth("two"))
            return {
                **creds,
                "access_token": jwt(generation=1),
                "refresh_token": "rotated",
            }

        self.refresh.side_effect = refresh
        self.assertEqual((await self.coordinator.get_snapshot()).account_id, "two")
        self.assertEqual(
            json.loads(self.path.read_text())["tokens"]["account_id"], "two"
        )

    async def test_logout_during_refresh_does_not_recreate_file(self):
        self.write(auth(expires=1))

        async def refresh(creds, proxy):
            self.path.unlink()
            return {**creds, "access_token": jwt(generation=1)}

        self.refresh.side_effect = refresh
        # A removed file is a changed login, not a failed persistence attempt.
        with self.assertRaises(store.ReauthenticationRequiredError):
            await self.coordinator.get_snapshot()
        self.assertFalse(self.path.exists())

    async def test_logout_while_waiting_for_refresh_lock_never_returns_empty_token(
        self,
    ):
        self.write(auth())
        lock = self.coordinator._source_lock("OpenAI Subscribe")
        await lock.acquire()
        waiting = asyncio.create_task(self.coordinator.get_snapshot())
        await asyncio.sleep(0)
        self.path.unlink()
        lock.release()
        with self.assertRaises(store.ReauthenticationRequiredError):
            await waiting

    async def test_refresh_failure_observes_new_login(self):
        self.write(auth(expires=1))

        async def refresh(creds, proxy):
            self.write(auth("two"))
            raise RuntimeError("secret token endpoint details")

        self.refresh.side_effect = refresh
        self.assertEqual((await self.coordinator.get_snapshot()).account_id, "two")

    async def test_expired_token_does_not_silently_use_another_account(self):
        self.write(auth(expires=1))
        self.refresh.side_effect = RuntimeError("secret token endpoint details")
        with self.assertRaises(store.ReauthenticationRequiredError) as caught:
            await self.coordinator.get_snapshot()
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(self.coordinator.status().state, "reauth_required")
        self.write(auth("two"))
        self.assertEqual(self.coordinator.status().state, "ready")
        no_refresh = auth(expires=1)
        no_refresh["tokens"].pop("refresh_token")
        self.write(no_refresh)
        with self.assertRaises(store.ReauthenticationRequiredError):
            await self.coordinator.get_snapshot()

    async def test_cooldown_and_quota_follow_account(self):
        self.write(auth())
        fetch = AsyncMock(side_effect=lambda snapshot: {"account": snapshot.account_id})
        self.assertEqual(
            (await self.coordinator.get_usage(None, fetch))["account"], "one"
        )
        await self.coordinator.mark_cooling(None, 9999999999)
        with self.assertRaises(store.CredentialCooldownError):
            await self.coordinator.get_snapshot()
        self.write(auth("two"))
        self.assertEqual((await self.coordinator.get_snapshot()).account_id, "two")
        self.assertEqual(
            (await self.coordinator.get_usage(None, fetch))["account"], "two"
        )
        await self.coordinator.mark_cooling(
            None, 9999999999, expected_access_token=jwt()
        )
        self.assertFalse((await self.coordinator.get_snapshot()).is_cooling_down())
        self.assertEqual(json.loads(self.device["key"]), self.backup)
        self.write(auth())
        self.assertEqual(self.coordinator.status().state, "cooling")

    async def test_quota_cooldown_uses_only_exhausted_windows(self):
        self.write(auth())
        now = 2000000000
        short_reset, weekly_reset = now + 3600, now + 604800
        for short_used, weekly_used, expected in (
            (100, 40, short_reset),
            (100, 100, weekly_reset),
            (40, 100, weekly_reset),
        ):
            with self.subTest(short_used=short_used, weekly_used=weekly_used):
                # A fresh lookup also corrects a previously excessive cooldown.
                await self.coordinator.mark_cooling(None, weekly_reset)
                usage = {
                    "allowed": False,
                    "limit_reached": True,
                    "windows": [
                        {"used_percent": short_used, "reset_at": short_reset},
                        {"used_percent": weekly_used, "reset_at": weekly_reset},
                    ],
                }
                with (
                    patch.object(plugin.time, "time", return_value=now),
                    patch.object(plugin, "_login_request_error", return_value=None),
                    patch.object(
                        plugin,
                        "_get_credential_coordinator",
                        return_value=self.coordinator,
                    ),
                    patch.object(
                        plugin, "fetch_rate_limits", new=AsyncMock(return_value=usage)
                    ),
                ):
                    data = json.loads((await plugin._handle_account_usage()).body)
                    self.assertEqual(data["account"]["cooldown_until"], expected)
                    with self.assertRaises(store.CredentialCooldownError):
                        await self.coordinator.get_snapshot()
                with patch.object(plugin.time, "time", return_value=expected + 1):
                    self.assertFalse(
                        (await self.coordinator.get_snapshot()).is_cooling_down()
                    )

    def test_cooldown_without_exhausted_window_has_no_invented_reset(self):
        for used in (40, None, True, float("nan")):
            self.assertIsNone(
                plugin._cooldown_until_from_usage(
                    {"windows": [{"used_percent": used, "reset_at": 9999999999}]}
                )
            )
        with patch.object(plugin.time, "time", return_value=2000000000):
            self.assertEqual(
                plugin._cooldown_until_from_usage(
                    {"windows": [{"used_percent": 100, "reset_after_seconds": 60}]}
                ),
                2000000060,
            )

    async def test_in_flight_quota_is_not_cached_for_new_account(self):
        self.write(auth())

        async def fetch(snapshot):
            self.write(auth("two"))
            return {"account": snapshot.account_id}

        with self.assertRaises(store.ReauthenticationRequiredError):
            await self.coordinator.get_usage(None, fetch)
        fetch_new = AsyncMock(return_value={"account": "two"})
        self.assertEqual(
            (await self.coordinator.get_usage(None, fetch_new))["account"], "two"
        )

    async def test_refresh_write_failure_keeps_original(self):
        self.write(auth(expires=1))
        original = self.path.read_bytes()
        self.refresh.return_value = {
            "access_token": jwt(generation=1),
            "refresh_token": "rotated",
        }
        with (
            patch.object(local.os, "replace", side_effect=PermissionError),
            self.assertRaises(store.CredentialPersistenceError),
        ):
            await self.coordinator.get_snapshot()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob(".astrbot-auth-*")), [])

    async def test_startup_source_and_default_path(self):
        self.conf["provider_sources"] = []
        await self.coordinator.ensure_default_source()
        await self.coordinator.ensure_default_source()
        self.assertEqual(self.conf.saved, 1)
        self.assertEqual(self.conf["provider_sources"][0]["key"], "")
        with patch.dict(os.environ, {"CODEX_HOME": self.tmp.name}):
            self.assertEqual(local.LocalCodexStore().path, self.path.resolve())

    async def test_invalid_refresh_does_not_damage_codex_login(self):
        self.write(auth(expires=1))
        original = self.path.read_bytes()
        self.refresh.return_value = {
            "access_token": "invalid",
            "refresh_token": "rotated",
        }
        with self.assertRaises(store.ReauthenticationRequiredError):
            await self.coordinator.get_snapshot()
        self.assertEqual(self.path.read_bytes(), original)

    async def test_forced_refresh_is_shared_by_concurrent_requests(self):
        self.write(auth())

        async def refresh(creds, proxy):
            await asyncio.sleep(0)
            return {
                **creds,
                "access_token": jwt(generation=1),
                "refresh_token": "rotated",
            }

        self.refresh.side_effect = refresh
        results = await asyncio.gather(
            *(self.coordinator.get_snapshot(force_refresh=True) for _ in range(4))
        )
        self.assertEqual(self.refresh.await_count, 1)
        self.assertTrue(all(x.access_token == jwt(generation=1) for x in results))

    async def test_plugin_defaults_and_status_disclose_only_origin(self):
        self.write(auth())
        with (
            patch.dict(os.environ, {"CODEX_HOME": self.tmp.name}),
            patch.object(plugin, "_config_mgr", None),
            patch.object(plugin, "_local_codex_store", None),
            patch.object(plugin, "_credential_coordinator", None),
        ):
            context = SimpleNamespace(
                astrbot_config_mgr=SimpleNamespace(default_conf=self.conf),
                register_web_api=lambda *args: None,
            )
            instance = plugin.OpenAI_OAuth_Plugin(context, config={})
            await instance.initialize()
            coordinator = plugin._get_credential_coordinator()
            self.assertEqual((await coordinator.get_snapshot()).account_id, "one")
            provider = plugin.ProviderOpenAICodex(dict(self.source), {})
            try:
                with patch.object(
                    plugin, "fetch_models", new=AsyncMock(return_value=["test-model"])
                ) as fetch:
                    self.assertEqual(await provider.get_models(), ["test-model"])
                    self.assertEqual(fetch.call_args.args[:2], (jwt(), "one"))
                    self.write(auth("two"))
                    self.assertEqual(await provider.get_models(), ["test-model"])
                    self.assertEqual(fetch.call_args.args[:2], (jwt("two"), "two"))
            finally:
                await provider.client.close()
            with patch.object(plugin, "_login_request_error", return_value=None):
                response = await plugin._handle_account_status()
            data = json.loads(response.body)
            self.assertEqual(data["status"], "ready")
            self.assertEqual(data["credential_source"], "local_codex")
            self.assertEqual(data["credential_mode"], "local_codex")
            self.assertNotIn("backup_status", data)
            self.assertEqual(len(data["account_revision"]), 64)

    async def test_view_identity_tracks_account_not_token_rotation(self):
        self.write(auth())
        first = self.coordinator.account_view()
        self.write(auth(generation=1))
        self.assertEqual(first, self.coordinator.account_view())
        self.write(auth("second-account"))
        second = self.coordinator.account_view()
        self.assertNotEqual(first["account_revision"], second["account_revision"])
        serialized = json.dumps(second)
        for secret in ("second-account", jwt("second-account"), "backup-refresh"):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("backup_status", second)
        self.assertEqual(second["credential_mode"], "local_codex")

    async def test_usage_api_reports_switch_during_network_fetch(self):
        self.write(auth())

        async def switched_usage(*args):
            self.write(auth("second-account"))
            return {"allowed": True, "windows": [{"used_percent": 99}]}

        with (
            patch.object(plugin, "_login_request_error", return_value=None),
            patch.object(
                plugin, "_get_credential_coordinator", return_value=self.coordinator
            ),
            patch.object(plugin, "fetch_rate_limits", new=switched_usage),
        ):
            response = await plugin._handle_account_usage()
        data = json.loads(response.body)
        self.assertEqual(data["status"], "account_changed")
        self.assertNotIn("usage", data)
        self.assertEqual(data["account"]["status"], "ready")

    async def test_usage_api_rejects_previous_account_result(self):
        self.write(auth())

        async def switched_usage(source_id):
            self.write(auth("second-account"))
            return {"windows": [{"used_percent": 99}]}

        with (
            patch.object(plugin, "_login_request_error", return_value=None),
            patch.object(
                plugin, "_get_credential_coordinator", return_value=self.coordinator
            ),
            patch.object(plugin, "_fetch_source_usage", new=switched_usage),
        ):
            response = await plugin._handle_account_usage()
        data = json.loads(response.body)
        self.assertEqual(data["status"], "account_changed")
        self.assertNotIn("usage", data)
        self.assertEqual(
            data["account"]["account_revision"],
            self.coordinator.account_view()["account_revision"],
        )


if __name__ == "__main__":
    unittest.main()
