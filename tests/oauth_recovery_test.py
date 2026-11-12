"""Refresh recovery, bounded device polling and safe diagnostics regressions."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import httpx
from local_codex_test import Config, auth, jwt, local, oauth, store, usage_service


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_credential_modes_recover_without_usage(self):
        import tempfile

        for mode in ("device_oauth", "local_codex"):
            for forced in (False, True):
                for failure in ("network", 429, 502, 400):
                    with (
                        self.subTest(mode=mode, forced=forced, failure=failure),
                        tempfile.TemporaryDirectory() as tmp,
                    ):
                        path = Path(tmp) / "auth.json"
                        path.write_text(
                            json.dumps(auth(expires=9999999999 if forced else 1))
                        )
                        credentials = {
                            "access_token": jwt(),
                            "refresh_token": "refresh-secret",
                            "expires": 9999999999 if forced else 1,
                            "account_id": "one",
                        }
                        source = {
                            "id": "test",
                            "type": "test",
                            "credential_mode": mode,
                            "key": json.dumps(credentials),
                        }
                        coordinator = local.LocalCredentialCoordinator(
                            SimpleNamespace(
                                default_conf=Config(provider_sources=[source])
                            ),
                            provider_type="test",
                            default_source_id="test",
                            default_source_factory=dict,
                            refresh_credentials=oauth.refresh_access_token,
                            local_store=local.LocalCodexStore(str(path)),
                        )
                        request = httpx.Request("POST", oauth.CODEX_OAUTH_TOKEN_URL)
                        bad = (
                            httpx.ConnectError("secret connection details")
                            if failure == "network"
                            else httpx.Response(
                                failure,
                                json={"error": "secret-unknown"},
                                request=request,
                            )
                        )
                        good = httpx.Response(
                            200,
                            json={
                                "access_token": jwt(generation=1),
                                "refresh_token": "rotated",
                                "expires_in": 3600,
                            },
                            request=request,
                        )
                        client = SimpleNamespace(
                            post=AsyncMock(side_effect=[bad, good]), aclose=AsyncMock()
                        )
                        with patch.object(
                            oauth, "create_proxy_client", return_value=client
                        ):
                            with self.assertRaises(
                                store.CredentialRefreshError
                            ) as caught:
                                await coordinator.get_snapshot(force_refresh=forced)
                            self.assertNotIn("secret", str(caught.exception))
                            self.assertIsNone(
                                usage_service.failure_state(caught.exception)
                            )
                            self.assertEqual(coordinator.status().state, "degraded")
                            coordinator.ensure_inference_available("test")
                            current = await coordinator.get_snapshot(
                                force_refresh=forced
                            )
                            coordinator.ensure_inference_available("test")
                        self.assertEqual(current.access_token, jwt(generation=1))
                        self.assertEqual(current.refresh_token, "rotated")
                        self.assertEqual(coordinator.status().state, "ready")
                        self.assertEqual(client.post.await_count, 2)
                        self.assertEqual(client.aclose.await_count, 2)

    async def test_refresh_boundary_classifies_auth_and_sanitizes_logs(self):
        for status, body, expected in (
            (400, {"error": "invalid_grant"}, store.ReauthenticationRequiredError),
            (401, {"error": "secret-token"}, store.ReauthenticationRequiredError),
            (
                403,
                {"error": {"code": "invalid_token"}},
                store.ReauthenticationRequiredError,
            ),
            (
                502,
                {
                    "error": {
                        "code": "secret-token\nforged-log",
                        "message": "secret-token",
                    }
                },
                store.CredentialRefreshError,
            ),
        ):
            response = httpx.Response(
                status,
                json=body,
                request=httpx.Request("POST", oauth.CODEX_OAUTH_TOKEN_URL),
            )
            client = SimpleNamespace(
                post=AsyncMock(return_value=response), aclose=AsyncMock()
            )
            with (
                self.subTest(status=status),
                patch.object(oauth, "create_proxy_client", return_value=client),
                patch.object(oauth.logger, "error") as log,
            ):
                with self.assertRaises(expected) as caught:
                    await oauth.refresh_access_token({"refresh_token": "secret-token"})
                self.assertNotIn("secret-token", str(caught.exception))
                self.assertNotIn("secret-token", str(log.call_args))
                self.assertIn(f"status={status}", str(log.call_args))
                self.assertIn(
                    "code=invalid_grant"
                    if status == 400
                    else "code=invalid_token"
                    if status == 403
                    else "code=unknown",
                    str(log.call_args),
                )
                client.aclose.assert_awaited_once()

    async def test_expired_credentials_only_lock_on_explicit_rejection(self):
        for error in (
            store.ReauthenticationRequiredError("rejected"),
            RuntimeError("secret"),
        ):
            credentials = {"access_token": jwt(), "refresh_token": "rt", "expires": 1}
            source = {"id": "test", "type": "test", "key": json.dumps(credentials)}
            coordinator = local.LocalCredentialCoordinator(
                SimpleNamespace(default_conf=Config(provider_sources=[source])),
                provider_type="test",
                default_source_id="test",
                default_source_factory=dict,
                refresh_credentials=AsyncMock(side_effect=error),
            )
            with self.assertRaises(store.CredentialError):
                await coordinator.get_snapshot()
            if isinstance(error, store.ReauthenticationRequiredError):
                with self.assertRaises(store.ReauthenticationRequiredError):
                    coordinator.ensure_inference_available("test")
            else:
                coordinator.ensure_inference_available("test")

    async def test_proactive_refresh_keeps_valid_token(self):
        credentials = {
            "access_token": jwt(),
            "refresh_token": "rt",
            "expires": int(time.time()) + 60,
        }
        coordinator = store.CredentialCoordinator(
            SimpleNamespace(
                default_conf=Config(
                    provider_sources=[
                        {"id": "test", "type": "test", "key": json.dumps(credentials)}
                    ]
                )
            ),
            provider_type="test",
            default_source_id="test",
            default_source_factory=dict,
            refresh_credentials=AsyncMock(
                side_effect=store.CredentialRefreshError("retry")
            ),
        )
        self.assertEqual(
            (await coordinator.get_snapshot()).access_token, credentials["access_token"]
        )
        self.assertEqual(coordinator.status().state, "degraded")


class PollTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 0.0
        self.delays = []
        self.client = SimpleNamespace(post=AsyncMock(), aclose=AsyncMock())
        self.patchers = [
            patch.object(oauth, "create_proxy_client", return_value=self.client),
            patch.object(oauth, "time", SimpleNamespace(monotonic=lambda: self.now)),
            patch.object(oauth.asyncio, "sleep", side_effect=self.sleep),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay

    async def test_transient_errors_then_authorization(self):
        self.client.post.side_effect = [
            httpx.ConnectError("secret"),
            httpx.Response(502),
            httpx.Response(429, headers={"Retry-After": "12"}),
            httpx.Response(403),
            httpx.Response(404),
            httpx.Response(
                200, json={"authorization_code": "ac", "code_verifier": "cv"}
            ),
        ]
        self.assertEqual(
            await oauth.poll_device_authorization("secret", "secret", 1), ("ac", "cv")
        )
        self.assertEqual(self.delays, [1, 2, 4, 12, 1, 1])
        self.client.aclose.assert_awaited_once()

    async def test_retry_after_cannot_extend_deadline(self):
        self.client.post.return_value = httpx.Response(
            429, headers={"Retry-After": "1000"}
        )
        with self.assertRaises(oauth.DeviceAuthTimeout):
            await oauth.poll_device_authorization("d", "u", 1, timeout_seconds=10)
        self.assertEqual(self.now, 10)
        self.client.post.assert_awaited_once()
        self.client.aclose.assert_awaited_once()

    async def test_permanent_errors_stop_and_cancel_propagates(self):
        for outcome, expected in (
            (httpx.Response(400), oauth.DeviceAuthError),
            (asyncio.CancelledError(), asyncio.CancelledError),
            (ValueError("secret"), oauth.DeviceAuthError),
        ):
            self.client.post.reset_mock(side_effect=True)
            self.client.aclose.reset_mock()
            self.client.post.side_effect = [outcome]
            with self.assertRaises(expected):
                await oauth.poll_device_authorization("d", "u", 1)
            self.client.post.assert_awaited_once()
            self.client.aclose.assert_awaited_once()

    def test_retry_after_dates_and_malformed_values(self):
        for value in ("garbage", "nan", "inf", "-1", "0"):
            self.assertEqual(
                oauth._poll_retry_delay(
                    httpx.Response(429, headers={"Retry-After": value}), 4
                ),
                4,
            )
        date = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
        delay = oauth._poll_retry_delay(
            httpx.Response(429, headers={"Retry-After": date}), 4
        )
        self.assertGreater(delay, 28)
        self.assertLessEqual(delay, 30)


if __name__ == "__main__":
    unittest.main()
