"""Framework-free account, routing, local file and transport regressions."""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import credential_store as store
from src import local_codex as local
from src.provider_routing import RequestBudget, RoutingBudgetError
from src.transport_pool import TransportPool


class Config(dict):
    fail = False

    async def save_config_async(self):
        if self.fail:
            raise OSError("Cannot save config")
        return True


def credentials(generation=0):
    claims = {
        "exp": 9999999999,
        store.AUTH_CLAIM: {"chatgpt_account_id": "account"},
        "generation": generation,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return {
        "access_token": f"header.{encoded}.signature",
        "refresh_token": f"refresh-{generation}",
        "account_id": "account",
        "expires": 9999999999,
    }


def coordinator(config, refresh=None, local_store=None):
    return local.LocalCredentialCoordinator(
        SimpleNamespace(default_conf=config),
        provider_type="test",
        default_source_id="test",
        default_source_factory=lambda: {"id": "test", "type": "test", "key": ""},
        refresh_credentials=refresh or AsyncMock(),
        local_store=local_store,
    )


class AccountTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_refresh_can_recover_without_usage(self):
        old = {**credentials(), "expires": 1}
        source = {"id": "test", "type": "test", "key": json.dumps(old)}
        refresh = AsyncMock(
            side_effect=[store.CredentialRefreshError("retry"), credentials(1)]
        )
        account = coordinator(Config(provider_sources=[source]), refresh)
        with self.assertRaises(store.CredentialRefreshError):
            await account.get_snapshot()
        account.ensure_inference_available("test")
        self.assertEqual((await account.get_snapshot()).refresh_token, "refresh-1")
        self.assertEqual(account.status().state, "ready")

    async def test_rejected_refresh_blocks_inference(self):
        old = {**credentials(), "expires": 1}
        account = coordinator(
            Config(
                provider_sources=[
                    {"id": "test", "type": "test", "key": json.dumps(old)}
                ]
            ),
            AsyncMock(side_effect=store.ReauthenticationRequiredError("rejected")),
        )
        with self.assertRaises(store.ReauthenticationRequiredError):
            await account.get_snapshot()
        with self.assertRaises(store.ReauthenticationRequiredError):
            account.ensure_inference_available("test")

    async def test_registry_failed_save_restores_enabled_account(self):
        source = {
            "id": "test",
            "type": "test",
            "key": json.dumps(credentials()),
            "credential_mode": "device_oauth",
            "enable": True,
        }
        config = Config(provider_sources=[source])
        account = coordinator(config)
        config.fail = True
        with self.assertRaises(store.CredentialPersistenceError):
            await account.providers.edit("test", enabled=False)
        self.assertTrue(account.providers.enabled("test"))
        config.fail = False
        await account.providers.edit("test", enabled=False)
        with self.assertRaises(store.ProviderDisabledError):
            account.ensure_inference_available("test")

    async def test_registry_migration_preserves_device_login(self):
        config = Config(
            provider_sources=[
                {"id": "test", "type": "test", "key": json.dumps(credentials())}
            ]
        )
        account = coordinator(config)
        await account.ensure_default_source()
        first = json.dumps(config, sort_keys=True)
        await account.ensure_default_source()
        self.assertEqual(json.dumps(config, sort_keys=True), first)
        self.assertEqual(
            (await account.get_snapshot()).access_token, credentials()["access_token"]
        )

    async def test_passive_usage_merges_windows_isolates_accounts_and_skips_cooling(
        self,
    ):
        claims = {
            "exp": 9999999999,
            store.AUTH_CLAIM: {
                "chatgpt_account_id": "account",
                "chatgpt_plan_type": "plus",
            },
        }
        encoded = (
            base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        )
        creds = {
            **credentials(),
            "access_token": f"header.{encoded}.signature",
        }
        source = {"id": "test", "type": "test", "key": json.dumps(creds)}
        account = coordinator(Config(provider_sources=[source]))
        fetcher = AsyncMock(
            return_value={
                "allowed": True,
                "limit_reached": False,
                "plan_type": "pro",
                "windows": [{"label_seconds": 604800, "used_percent": 10.0}],
            }
        )

        # Cold start passive reading populates display cache with plan_type from JWT.
        recorded = account.record_passive_usage(
            "test",
            [
                {
                    "label_seconds": 18000,
                    "used_percent": 25.0,
                    "reset_at": 1900000100,
                    "reset_after_seconds": 300,
                },
                {
                    "label_seconds": 604800,
                    "used_percent": 12.0,
                    "reset_at": 1900500000,
                    "reset_after_seconds": 90000,
                },
            ],
            expected_account_id="account",
            expected_origin="plugin",
        )
        self.assertTrue(recorded)
        cached = await account.get_usage("test", fetcher)
        fetcher.assert_not_awaited()
        self.assertEqual(cached["plan_type"], "plus")
        self.assertEqual([w["used_percent"] for w in cached["windows"]], [25.0, 12.0])

        # Partial update preserves secondary window and omitted reset fields,
        # and a 100% passive window never sets limit_reached or cooling state.
        self.assertTrue(
            account.record_passive_usage(
                "test",
                [
                    {
                        "label_seconds": 18000,
                        "used_percent": 100.0,
                        "reset_at": None,
                        "reset_after_seconds": None,
                    }
                ],
                expected_account_id="account",
                expected_origin="plugin",
            )
        )
        updated = await account.get_usage("test", fetcher)
        fetcher.assert_not_awaited()
        self.assertTrue(updated["allowed"])
        self.assertFalse(updated["limit_reached"])
        self.assertEqual(account.status("test").state, "ready")
        self.assertEqual(updated["windows"][0]["used_percent"], 100.0)
        self.assertEqual(updated["windows"][0]["reset_at"], 1900000100)
        self.assertEqual(updated["windows"][1]["label_seconds"], 604800)

        # Stale readings from another account/origin are discarded.
        self.assertFalse(
            account.record_passive_usage(
                "test",
                [{"label_seconds": 18000, "used_percent": 1.0}],
                expected_account_id="other-account",
                expected_origin="plugin",
            )
        )
        self.assertFalse(
            account.record_passive_usage(
                "test",
                [{"label_seconds": 18000, "used_percent": 1.0}],
                expected_account_id="account",
                expected_origin="local_codex",
            )
        )

        # force_refresh=True bypasses the passive cache.
        fresh = await account.get_usage("test", fetcher, force_refresh=True)
        fetcher.assert_awaited_once()
        self.assertEqual(fresh["plan_type"], "pro")

    async def test_partial_updates_expire_each_window_independently(self):
        source = {"id": "test", "type": "test", "key": json.dumps(credentials())}
        account = coordinator(Config(provider_sources=[source]))
        fetch = AsyncMock(return_value={"windows": []})
        short = {"label_seconds": 18000, "used_percent": 20}
        week = {"label_seconds": 604800, "used_percent": 50}
        with patch.object(store, "time", wraps=store.time) as clock:
            clock.monotonic.return_value = 100
            account.record_passive_usage("test", [short, week])
            clock.monotonic.return_value = 120
            account.record_passive_usage("test", [short])
            clock.monotonic.return_value = 131
            cached = await account.get_usage("test", fetch)
            self.assertEqual([w["label_seconds"] for w in cached["windows"]], [18000])
            account.record_passive_usage("test", [short])
            self.assertEqual(
                len((await account.get_usage("test", fetch))["windows"]), 1
            )
            fetch.assert_not_awaited()
            clock.monotonic.return_value = 162
            await account.get_usage("test", fetch)
            fetch.assert_awaited_once()

    async def test_passive_readings_preserve_authoritative_denial_until_expiry(self):
        source = {"id": "test", "type": "test", "key": json.dumps(credentials())}
        account = coordinator(Config(provider_sources=[source]))
        week = {"label_seconds": 604800, "used_percent": 100, "reset_at": 9999999999}
        denied = {"allowed": False, "limit_reached": True, "windows": [week]}
        fetch = AsyncMock(return_value=denied)
        with patch.object(store, "time", wraps=store.time) as clock:
            clock.monotonic.return_value = 100
            await account.get_usage("test", fetch)
            clock.monotonic.return_value = 120
            account.record_passive_usage(
                "test", [{"label_seconds": 18000, "used_percent": 100}]
            )
            self.assertEqual(await account.get_usage("test", fetch), denied)
            clock.monotonic.return_value = 131
            passive = await account.get_usage("test", fetch)
            self.assertTrue(passive["allowed"])
            self.assertFalse(passive["limit_reached"])
            self.assertEqual([w["label_seconds"] for w in passive["windows"]], [18000])
            fetch.assert_awaited_once()

    async def test_concurrent_forced_usage_shares_only_the_inflight_lookup(self):
        source = {"id": "test", "type": "test", "key": json.dumps(credentials())}
        account = coordinator(Config(provider_sources=[source]))
        entered, release = asyncio.Event(), asyncio.Event()

        async def lookup(snapshot):
            entered.set()
            await release.wait()
            return {"windows": [{"used_percent": 10}]}

        fetch = AsyncMock(side_effect=lookup)

        async def forced():
            return await account.get_usage("test", fetch, force_refresh=True)

        first = asyncio.create_task(forced())
        await entered.wait()
        others = [asyncio.create_task(forced()) for _ in range(4)]
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(first, *others)
        fetch.assert_awaited_once()
        results[0]["windows"].clear()
        self.assertEqual(results[1]["windows"], [{"used_percent": 10}])
        await forced()
        self.assertEqual(fetch.await_count, 2)


class LocalFileTests(unittest.TestCase):
    def test_rotation_preserves_unknown_fields_and_rejects_stale_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            path.write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": credentials(),
                        "future": {"keep": True},
                    }
                )
            )
            source = local.LocalCodexStore(str(path))
            login = source.read(fresh=True)
            self.assertIsNotNone(login)
            self.assertTrue(source.write_refresh(login, credentials(1)))
            self.assertFalse(source.write_refresh(login, credentials(2)))
            self.assertEqual(
                source.read(fresh=True).credentials["refresh_token"], "refresh-1"
            )
            self.assertEqual(json.loads(path.read_text())["future"], {"keep": True})
            self.assertEqual(list(path.parent.glob(".astrbot-auth-*")), [])

    def test_logout_does_not_recreate_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            path.write_text(json.dumps({"tokens": credentials()}))
            source = local.LocalCodexStore(str(path))
            login = source.read(fresh=True)
            path.unlink()
            self.assertFalse(source.write_refresh(login, credentials(1)))
            self.assertFalse(path.exists())


class RoutingTests(unittest.TestCase):
    def test_budget_stops_at_limit(self):
        budget = RequestBudget(2)
        budget.consume()
        budget.consume()
        with self.assertRaises(RoutingBudgetError):
            budget.consume()
        self.assertEqual(budget.remaining, 0)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_rotated_transport_closes_only_after_old_lease_finishes(self):
        pool = TransportPool()
        first = SimpleNamespace(is_closed=False, aclose=AsyncMock())
        second = SimpleNamespace(is_closed=False, aclose=AsyncMock())
        async with pool.lease("one", ("token-1", "proxy"), lambda: first) as old:
            async with pool.lease("one", ("token-1", "proxy"), lambda: None) as same:
                self.assertIs(same, old)
            async with pool.lease("one", ("token-2", "proxy"), lambda: second) as new:
                self.assertIs(new, second)
                first.aclose.assert_not_awaited()
            first.aclose.assert_not_awaited()
        first.aclose.assert_awaited_once()
        await pool.close()
        second.aclose.assert_awaited_once()

    async def test_cancelled_consumer_releases_retired_transport(self):
        pool = TransportPool()
        old = SimpleNamespace(is_closed=False, aclose=AsyncMock())
        new = SimpleNamespace(is_closed=False, aclose=AsyncMock())
        started = asyncio.Event()

        async def consume():
            async with pool.lease("one", ("old", ""), lambda: old):
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(consume())
        await started.wait()
        async with pool.lease("one", ("new", ""), lambda: new):
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            old.aclose.assert_awaited_once()
        await pool.close()
