"""Framework-free account, routing, local file and transport regressions."""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
