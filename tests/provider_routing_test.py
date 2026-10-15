"""Exercise source routing through the real SDK with isolated, fake transports."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import httpx
from local_codex_test import Config, jwt, local, store
from login_test import payload, plugin, request_context
from openai import BadRequestError


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        def source(sid, account, **extra):
            return {
                "id": sid,
                "type": "OpenAI Subscribe",
                "enable": True,
                "credential_mode": "device_oauth",
                "name": sid,
                "oauth_routing_mode": "fixed",
                "proxy": "http://" + sid + ":8080",
                "originator": sid,
                "user_agent": "agent-" + sid,
                "custom_headers": {"X-Source": sid, "Authorization": "stale"},
                "key": json.dumps(
                    {
                        "access_token": jwt(account),
                        "account_id": account,
                        "refresh_token": "refresh-" + sid,
                        "expires": 9999999999,
                    }
                ),
                **extra,
            }

        self.conf = Config(
            provider_sources=[
                source(
                    "local",
                    "a",
                    credential_mode="local_codex",
                    oauth_routing_mode="auto",
                ),
                source("same", "a"),
                source("other", "b"),
            ],
            provider=[{"id": "model", "provider_source_id": "local", "enable": True}],
        )
        self.login = {
            "access_token": jwt("a"),
            "account_id": "a",
            "refresh_token": "local-refresh",
            "expires": 9999999999,
        }
        self.refresh = AsyncMock(
            side_effect=lambda creds, proxy: {
                **creds,
                "access_token": creds["access_token"] + "-new",
            }
        )
        self.coordinator = local.LocalCredentialCoordinator(
            SimpleNamespace(default_conf=self.conf),
            provider_type="OpenAI Subscribe",
            default_source_id="local",
            default_source_factory=dict,
            refresh_credentials=self.refresh,
            local_store=SimpleNamespace(
                read=lambda: SimpleNamespace(credentials=self.login)
            ),
        )
        self.registry = self.coordinator.providers
        patcher = patch.object(
            plugin, "_get_credential_coordinator", return_value=self.coordinator
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.provider = plugin.ProviderOpenAICodex(
            {
                "id": "model",
                "provider_source_id": "local",
                "model": "test-model",
                "key": "",
                "proxy": "",
                "custom_headers": {"X-Source": "local"},
            },
            {},
        )
        self.addAsyncCleanup(self.provider.terminate)
        # Older AstrBot versions leave the SDK default retries enabled.
        # Routing must own every HTTP attempt regardless of the root client.
        self.provider.client.max_retries = 2
        self.outcomes = {}
        self.requests = []
        self.transports = []
        self.on_request = None
        self.on_sleep = None
        self.output = []

        async def handle(request):
            sid = request.headers["originator"]
            self.requests.append((sid, request))
            if self.on_request:
                await self.on_request(sid)
            queue = self.outcomes.get(sid, [])
            outcome = queue.pop(0) if queue else "ok"
            if outcome == "network":
                raise httpx.ConnectError("connection failed", request=request)
            if outcome == "wait":
                await asyncio.Event().wait()
            if outcome == "cancel":
                raise asyncio.CancelledError()
            if isinstance(outcome, int):
                return httpx.Response(
                    outcome, json={"error": {"message": "test error"}}
                )
            if outcome == "quota":
                return httpx.Response(
                    429,
                    json={"error": {"code": "usage_limit_reached", "message": "quota"}},
                )
            if outcome == "partial":
                events = [
                    {"type": "response.output_text.delta", "delta": "partial"},
                    {"error": {"code": "server_error", "message": "failed"}},
                ]
            else:
                events = [
                    {"type": "response.output_text.delta", "delta": sid},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "success",
                            "status": "completed",
                            "output": [],
                        },
                    },
                ]
            body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
            return httpx.Response(
                200, text=body, headers={"content-type": "text/event-stream"}
            )

        def transport(config):
            client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
            self.transports.append((config["proxy"], client))
            return client

        self.provider._create_http_client = transport

        async def sleep(_):
            if self.on_sleep:
                await self.on_sleep()

        patcher = patch.object(plugin.asyncio, "sleep", new=sleep)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(
            plugin,
            "fetch_rate_limits",
            new=AsyncMock(
                return_value={
                    "windows": [{"used_percent": 100, "reset_at": 9999999999}]
                }
            ),
        )
        self.usage = patcher.start()
        self.addCleanup(patcher.stop)

    async def collect(self, *, limit=5, public=False):
        if public:
            self.provider._prepare_chat_payload = AsyncMock(
                return_value=({"model": "test-model", "input": []}, None)
            )
            stream = self.provider.text_chat_stream(
                prompt="test", request_max_retries=limit
            )
        else:
            stream = self.provider._stream_with_current_credentials(
                {"model": "test-model", "input": []},
                None,
                request_max_retries=limit,
            )
        try:
            async for item in stream:
                self.output.append(item)
        finally:
            await stream.aclose()

    def requested(self):
        return [sid for sid, _ in self.requests]

    async def test_quota_fallback_deduplicates_and_uses_full_source_connection(self):
        self.outcomes["local"] = ["quota"]
        before = deepcopy(self.conf["provider"])
        await self.collect()
        self.assertEqual(self.requested(), ["local", "other"])
        request = self.requests[-1][1]
        self.assertEqual(request.headers["chatgpt-account-id"], "b")
        self.assertEqual(request.headers["authorization"], "Bearer " + jwt("b"))
        self.assertEqual(request.headers["user-agent"], "agent-other")
        self.assertEqual(request.headers["x-source"], "other")
        self.assertEqual(json.loads(request.content)["model"], "test-model")
        self.assertEqual(self.transports[-1][0], "http://other:8080")
        self.assertTrue(all(client.is_closed for _, client in self.transports))
        self.assertEqual(self.conf["provider"], before)
        self.assertEqual(self.provider._source_id, "local")
        self.assertEqual(self.coordinator.account_view("same")["status"], "cooling")
        await self.collect()
        self.assertEqual(self.requested(), ["local", "other", "other"])

    async def test_disabled_preferred_does_not_disable_same_account(self):
        await self.registry.edit("local", enabled=False)
        await self.collect()
        self.assertEqual(self.requested(), ["same"])

    async def test_all_disabled_is_actionable_without_reenabling(self):
        for sid in ("local", "same", "other"):
            await self.registry.edit(sid, enabled=False)
        with self.assertRaises(plugin.RoutingExhaustedError) as ctx:
            await self.collect()
        self.assertEqual(
            [reason for _, reason in ctx.exception.failures], ["disabled"] * 3
        )
        self.assertEqual(self.requests, [])
        self.assertTrue(all(not source["enable"] for source in self.registry.owned()))

    async def test_fixed_mode_never_switches(self):
        await self.registry.edit("local", routing_mode="fixed", enabled=False)
        with self.assertRaises(store.ProviderDisabledError):
            await self.collect()
        self.assertEqual(self.requests, [])

    async def test_unlogged_and_expired_without_refresh_skip_without_http(self):
        await self.registry.edit("local", enabled=False)
        for creds, reason in (
            ({}, "not_logged_in"),
            (
                {"access_token": jwt("a"), "expires": 1, "account_id": "a"},
                "reauth_required",
            ),
        ):
            self.coordinator._source("same")["key"] = json.dumps(creds)
            self.requests.clear()
            await self.collect()
            self.assertEqual(self.requested(), ["other"])
            self.assertEqual(self.coordinator.account_view("same")["status"], reason)

    async def test_preferred_device_precedes_local_and_no_recursive_fallback(self):
        self.provider._source_id = "other"
        await self.registry.edit("other", routing_mode="auto")
        self.outcomes["other"] = ["network", "network"]
        await self.collect()
        self.assertEqual(self.requested(), ["other", "other", "local"])

    async def test_network_retries_share_budget_across_accounts(self):
        self.outcomes = {"local": ["network"] * 4, "other": ["network"] * 4}
        with self.assertRaises(plugin.RoutingExhaustedError):
            await self.collect(limit=3)
        self.assertEqual(self.requested(), ["local", "local", "other"])

    async def test_rate_limit_falls_back_without_subscription_cooldown(self):
        self.outcomes["local"] = [429]
        await self.collect()
        self.assertEqual(self.requested(), ["local", "other"])
        self.assertEqual(self.coordinator.account_view("local")["status"], "ready")
        self.usage.assert_not_awaited()

    async def test_credential_refresh_cannot_reset_the_attempt_budget(self):
        await self.registry.edit("local", enabled=False)
        self.outcomes["same"] = [401]
        with self.assertRaises(plugin.RoutingExhaustedError) as ctx:
            await self.collect(limit=1)
        self.assertEqual(ctx.exception.reason, "attempt_limit")
        self.assertEqual(self.requested(), ["same"])
        self.refresh.assert_not_awaited()

    async def test_quota_lookup_timeout_retains_provisional_cooldown(self):
        self.outcomes["local"] = ["quota"]

        async def wait_for_usage(*args):
            await asyncio.Event().wait()

        self.usage.side_effect = wait_for_usage
        with (
            patch.object(plugin, "ROUTING_TIMEOUT_SECONDS", 0.02),
            self.assertRaises(plugin.RoutingExhaustedError),
        ):
            await self.collect()
        self.assertEqual(self.coordinator.account_view("local")["status"], "cooling")
        self.assertEqual(self.coordinator.account_view("same")["status"], "cooling")

    async def test_bad_request_does_not_rotate(self):
        self.outcomes["local"] = [400]
        with self.assertRaises(BadRequestError):
            await self.collect()
        self.assertEqual(self.requested(), ["local"])

    async def test_output_then_failure_returns_terminal_error_without_replay(self):
        self.outcomes["local"] = ["partial"]
        await self.collect(public=True)
        self.assertEqual(self.requested(), ["local"])
        self.assertTrue(self.output[0].is_chunk)
        self.assertEqual(self.output[-1].role, "err")

    async def test_outer_astrbot_runner_does_not_fallback_after_partial_output(self):
        from astrbot.core.agent.runners.tool_loop_agent_runner import (
            ToolLoopAgentRunner,
        )

        self.outcomes["local"] = ["partial"]
        self.provider._prepare_chat_payload = AsyncMock(
            return_value=({"model": "test-model", "input": []}, None)
        )
        runner = object.__new__(ToolLoopAgentRunner)
        runner.provider = self.provider
        runner.fallback_providers = [
            SimpleNamespace(provider_config={"id": "must-not-run"})
        ]
        runner.run_context = SimpleNamespace(
            messages=[{"role": "user", "content": "test"}]
        )
        runner._is_stop_requested = lambda: False
        runner._sanitize_malformed_tool_calls = lambda response: None

        async def iterate(**kwargs):
            self.assertIs(runner.provider, self.provider)
            async for item in self.provider.text_chat_stream(prompt="test"):
                yield item

        runner._iter_llm_responses = iterate
        output = [item async for item in runner._iter_llm_responses_with_fallback()]
        self.assertEqual(output[-1].role, "err")
        self.assertEqual(self.requested(), ["local"])

    async def test_consumer_close_releases_active_transport_immediately(self):
        self.provider._prepare_chat_payload = AsyncMock(
            return_value=({"model": "test-model", "input": []}, None)
        )
        stream = self.provider.text_chat_stream(prompt="test")
        first = await anext(stream)
        self.assertTrue(first.is_chunk)
        await stream.aclose()
        self.assertTrue(all(client.is_closed for _, client in self.transports))

    async def test_local_account_change_does_not_clear_other_entry_cooldown(self):
        self.outcomes["local"] = ["quota"]
        await self.collect()
        self.login = {**self.login, "account_id": "c", "access_token": jwt("c")}
        self.assertEqual(self.coordinator.account_view("same")["status"], "cooling")
        self.assertEqual(self.coordinator.account_view("local")["status"], "ready")

    async def test_startup_deadline_cannot_cancel_a_consumer_after_first_output(self):
        self.provider._prepare_chat_payload = AsyncMock(
            return_value=({"model": "test-model", "input": []}, None)
        )
        with patch.object(plugin, "ROUTING_TIMEOUT_SECONDS", 0.02):
            stream = self.provider.text_chat_stream(prompt="test")
            await anext(stream)
            done = asyncio.Event()
            asyncio.get_running_loop().call_later(0.04, done.set)
            await done.wait()
            await stream.aclose()
        self.assertEqual(self.requested(), ["local"])

    async def test_disable_during_retry_skips_source_and_keeps_budget(self):
        self.outcomes["local"] = [503]

        async def disable():
            await self.registry.edit("local", enabled=False)

        self.on_sleep = disable
        await self.collect()
        self.assertEqual(self.requested(), ["local", "other"])

    async def test_disable_inflight_does_not_interrupt_response(self):
        async def disable(sid):
            await self.registry.edit(sid, enabled=False)

        self.on_request = disable
        await self.collect()
        self.assertEqual(self.requested(), ["local"])
        self.assertEqual(self.output[-1].completion_text, "local")

    async def test_cancellation_is_not_fallback(self):
        self.outcomes["local"] = ["cancel"]
        with self.assertRaises(asyncio.CancelledError):
            await self.collect()
        self.assertEqual(self.requested(), ["local"])
        self.assertTrue(all(client.is_closed for _, client in self.transports))

    async def test_startup_timeout_is_shared_and_closes_transport(self):
        self.outcomes["local"] = ["wait"]
        with (
            patch.object(plugin, "ROUTING_TIMEOUT_SECONDS", 0.02),
            self.assertRaises(plugin.RoutingExhaustedError) as ctx,
        ):
            await self.collect()
        self.assertEqual(ctx.exception.reason, "startup_timeout")
        self.assertTrue(all(client.is_closed for _, client in self.transports))

    async def test_auth_refresh_once_then_skip_until_reauthorization(self):
        await self.registry.edit("local", enabled=False)
        self.outcomes["same"] = [401, 401]
        await self.collect()
        self.assertEqual(self.requested(), ["same", "same", "other"])
        self.assertEqual(self.refresh.await_count, 1)
        self.assertEqual(
            self.coordinator.account_view("same")["status"], "reauth_required"
        )
        await self.registry.edit("same", enabled=False)
        await self.registry.edit("same", enabled=True)
        self.assertEqual(
            self.coordinator.account_view("same")["status"], "reauth_required"
        )
        await self.collect()
        self.assertEqual(self.requested()[-1], "other")
        self.assertEqual(self.refresh.await_count, 1)

    async def test_failed_forced_refresh_does_not_reuse_rejected_token(self):
        await self.registry.edit("local", enabled=False)
        self.refresh.side_effect = RuntimeError("token rejected")
        self.outcomes["same"] = [401]
        await self.collect()
        self.assertEqual(self.requested(), ["same", "other"])
        self.assertEqual(
            self.coordinator.account_view("same")["status"], "reauth_required"
        )

    async def test_concurrent_requests_keep_clients_and_bindings_isolated(self):
        self.outcomes["local"] = [503, 503]
        await asyncio.gather(self.collect(), self.collect())
        for sid, request in self.requests:
            self.assertEqual(
                request.headers["chatgpt-account-id"], "b" if sid == "other" else "a"
            )
        self.assertEqual(self.provider._source_id, "local")

    async def test_routing_api_validates_and_rolls_back(self):
        with request_context({"source_id": "other", "routing_mode": "auto"}):
            result = payload(await plugin._handle_provider_update())
        self.assertEqual(result["provider"]["routing_mode"], "auto")
        for value in (None, False, 1, [], {}, "random"):
            with request_context({"source_id": "other", "routing_mode": value}):
                self.assertEqual(
                    (await plugin._handle_provider_update()).status_code, 400
                )
        with (
            patch.object(
                self.conf, "save_config_async", new=AsyncMock(side_effect=OSError)
            ),
            self.assertRaises(store.CredentialPersistenceError),
        ):
            await self.registry.edit("other", routing_mode="fixed")
        self.assertEqual(self.registry.routing_mode("other"), "auto")

    async def test_cancelled_policy_save_rolls_back_both_fields(self):
        before = deepcopy(self.conf)
        with (
            patch.object(
                self.conf,
                "save_config_async",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await self.registry.edit("other", enabled=False, routing_mode="auto")
        self.assertEqual(self.conf, before)
        self.assertTrue(self.registry.enabled("other"))
        self.assertEqual(self.registry.routing_mode("other"), "fixed")


if __name__ == "__main__":
    unittest.main()
