"""Focused regression tests for the plugin Web login security boundary.

Run with the AstrBot checkout interpreter so the real plugin request adapter is
available, as documented in AGENTS.md.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

plugin = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
from astrbot.api.web import PluginRequest, bind_request_context


class _FakeRequest:
    def __init__(
        self,
        body: dict | None = None,
        *,
        scheme: str = "https",
        client_host: str = "198.51.100.8",
        host: str = "astrbot.example",
        method: str = "POST",
    ) -> None:
        self._body = body or {}
        self.method = method
        self.url = SimpleNamespace(path="/extension", scheme=scheme, query="")
        self.headers = {"host": host}
        self.cookies = {}
        self.client = SimpleNamespace(host=client_host)
        self.query_params = SimpleNamespace(multi_items=list)

    async def json(self) -> dict:
        return self._body


def _plugin_request(
    body: dict | None = None,
    *,
    username: str = "astrbot",
    scheme: str = "https",
    client_host: str = "198.51.100.8",
    host: str = "astrbot.example",
    method: str = "POST",
) -> PluginRequest:
    return PluginRequest(
        _FakeRequest(
            body,
            scheme=scheme,
            client_host=client_host,
            host=host,
            method=method,
        ),
        username=username,
    )


def _payload(response) -> dict:
    return json.loads(response.body)


class _FakeConfig(dict):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.saved = 0

    async def save_config_async(self) -> None:
        self.saved += 1


class _FakeConfigManager:
    def __init__(self) -> None:
        self.default_conf = _FakeConfig({"provider_sources": []})


class _FakeContext:
    def __init__(self) -> None:
        self.astrbot_config_mgr = object()
        self.routes = []

    def register_web_api(self, *route) -> None:
        self.routes.append(route)


class LoginBoundaryTests(unittest.TestCase):
    def tearDown(self) -> None:
        discard = getattr(plugin, "_discard_all_login_sessions", None)
        if discard is not None:
            discard()
        else:
            plugin._login_sessions.clear()
        plugin._config_mgr = None

    def test_plain_http_is_rejected_by_default_and_https_is_allowed(self) -> None:
        async def run():
            remote_request = _plugin_request(scheme="http", method="GET")
            remote_request.headers["x-forwarded-proto"] = "https"
            with bind_request_context(remote_request):
                remote = await plugin._handle_login_page()
            with bind_request_context(
                _plugin_request(
                    scheme="http",
                    client_host="127.0.0.1",
                    host="astrbot.example",
                    method="GET",
                )
            ):
                untrusted_proxy = await plugin._handle_login_page()
            with bind_request_context(
                _plugin_request(
                    scheme="http",
                    client_host="127.0.0.1",
                    host="localhost:6185",
                    method="GET",
                )
            ):
                ambiguous_local = await plugin._handle_login_page()
            with bind_request_context(_plugin_request(method="GET")):
                secure = await plugin._handle_login_page()
            return remote, untrusted_proxy, ambiguous_local, secure

        remote, untrusted_proxy, ambiguous_local, secure = asyncio.run(run())
        self.assertEqual(remote.status_code, 403)
        self.assertEqual(untrusted_proxy.status_code, 403)
        self.assertEqual(ambiguous_local.status_code, 403)
        self.assertEqual(secure.status_code, 200)
        self.assertEqual(secure.headers["cache-control"], "no-store")

    def test_insecure_http_opt_in_still_requires_loopback_peer_and_host(self) -> None:
        async def load_page(*, client_host: str, host: str):
            with bind_request_context(
                _plugin_request(
                    scheme="http",
                    client_host=client_host,
                    host=host,
                    method="GET",
                )
            ):
                return await plugin._handle_login_page()

        async def run():
            with mock.patch.object(
                plugin, "_allow_insecure_local_http", True, create=True
            ):
                local = await load_page(client_host="127.0.0.1", host="localhost:6185")
                remote_peer = await load_page(
                    client_host="198.51.100.8", host="localhost:6185"
                )
                external_host = await load_page(
                    client_host="127.0.0.1", host="astrbot.example"
                )
                return local, remote_peer, external_host

        local, remote_peer, external_host = asyncio.run(run())
        self.assertEqual(local.status_code, 200)
        self.assertEqual(remote_peer.status_code, 403)
        self.assertEqual(external_host.status_code, 403)

    def test_api_key_cannot_enter_the_login_boundary(self) -> None:
        async def run():
            with bind_request_context(_plugin_request(username="api_key:key-1")):
                return await plugin._handle_device_start()

        with mock.patch.object(
            plugin,
            "request_device_user_code",
            new=mock.AsyncMock(return_value=("device", "CODE", 5)),
        ) as request_code:
            response = asyncio.run(run())
        self.assertEqual(response.status_code, 403)
        request_code.assert_not_awaited()

    def test_login_sessions_are_bounded_and_bound_to_their_owner(self) -> None:
        async def wait_forever(*_args):
            await asyncio.Event().wait()

        async def run():
            with (
                mock.patch.object(plugin, "_MAX_LOGIN_SESSIONS", 1),
                mock.patch.object(
                    plugin,
                    "request_device_user_code",
                    new=mock.AsyncMock(return_value=("device", "CODE", 5)),
                ),
                mock.patch.object(
                    plugin, "_run_device_login", side_effect=wait_forever
                ),
            ):
                with bind_request_context(_plugin_request(username="owner-a")):
                    first = await plugin._handle_device_start()
                first_data = _payload(first)
                with bind_request_context(_plugin_request(username="owner-b")):
                    second = await plugin._handle_device_start()
                with bind_request_context(
                    _plugin_request(
                        {"session_id": first_data["session_id"]}, username="owner-b"
                    )
                ):
                    stolen_poll = await plugin._handle_device_poll()
                return first, second, stolen_poll

        first, second, stolen_poll = asyncio.run(run())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(stolen_poll.status_code, 404)

    def test_login_sessions_have_a_per_user_limit(self) -> None:
        async def wait_forever(*_args):
            await asyncio.Event().wait()

        async def start(username: str):
            with bind_request_context(_plugin_request(username=username)):
                return await plugin._handle_device_start()

        async def run():
            with (
                mock.patch.object(plugin, "_MAX_LOGIN_SESSIONS", 3),
                mock.patch.object(plugin, "_MAX_LOGIN_SESSIONS_PER_USER", 1),
                mock.patch.object(
                    plugin,
                    "request_device_user_code",
                    new=mock.AsyncMock(return_value=("device", "CODE", 5)),
                ),
                mock.patch.object(
                    plugin, "_run_device_login", side_effect=wait_forever
                ),
            ):
                first = await start("owner-a")
                same_owner = await start("owner-a")
                other_owner = await start("owner-b")
                return first, same_owner, other_owner

        first, same_owner, other_owner = asyncio.run(run())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(same_owner.status_code, 429)
        self.assertEqual(other_owner.status_code, 200)

    def test_expiry_cancels_task_and_removes_session(self) -> None:
        async def run():
            started = asyncio.Event()

            async def pending():
                started.set()
                await asyncio.Event().wait()

            task = asyncio.create_task(pending())
            await started.wait()
            plugin._login_sessions["expiring"] = {
                "owner": "owner-a",
                "status": "pending",
                "task": task,
            }
            plugin._schedule_login_session_expiry("expiring", 0)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return task

        task = asyncio.run(run())
        self.assertNotIn("expiring", plugin._login_sessions)
        self.assertTrue(task.cancelled())

    def test_success_is_server_persisted_without_returning_credentials(self) -> None:
        fake_manager = _FakeConfigManager()
        plugin._config_mgr = fake_manager

        async def run():
            with (
                mock.patch.object(
                    plugin,
                    "request_device_user_code",
                    new=mock.AsyncMock(return_value=("device", "CODE", 1)),
                ),
                mock.patch.object(
                    plugin,
                    "poll_device_authorization",
                    new=mock.AsyncMock(return_value=("auth-code", "verifier")),
                ),
                mock.patch.object(
                    plugin,
                    "exchange_authorization_code",
                    new=mock.AsyncMock(
                        return_value={
                            "access_token": "fake-access",
                            "refresh_token": "fake-refresh",
                            "expires_in": 3600,
                        }
                    ),
                ),
            ):
                with bind_request_context(_plugin_request(username="owner-a")):
                    start = await plugin._handle_device_start()
                session_id = _payload(start)["session_id"]
                for _ in range(20):
                    session = plugin._login_sessions.get(session_id)
                    if session and session.get("status") != "pending":
                        break
                    await asyncio.sleep(0)
                with bind_request_context(
                    _plugin_request({"session_id": session_id}, username="owner-a")
                ):
                    first_poll = await plugin._handle_device_poll()
                with bind_request_context(
                    _plugin_request({"session_id": session_id}, username="owner-a")
                ):
                    replay = await plugin._handle_device_poll()
                return first_poll, replay

        first_poll, replay = asyncio.run(run())
        first_data = _payload(first_poll)
        self.assertEqual(first_data, {"status": "success", "error": None})
        self.assertEqual(first_poll.headers["cache-control"], "no-store")
        self.assertEqual(replay.status_code, 404)
        source = fake_manager.default_conf["provider_sources"][0]
        self.assertEqual(json.loads(source["key"])["access_token"], "fake-access")
        self.assertEqual(fake_manager.default_conf.saved, 1)
        self.assertFalse(hasattr(plugin, "_handle_save_creds"))
        self.assertNotIn("data.creds", plugin._LOGIN_PAGE_HTML)
        self.assertNotIn("<textarea", plugin._LOGIN_PAGE_HTML)


class StaticSecurityTests(unittest.TestCase):
    def test_insecure_http_plugin_setting_defaults_off(self) -> None:
        schema_path = os.path.join(PLUGIN_ROOT, "_conf_schema.json")
        with open(schema_path, encoding="utf-8") as source:
            schema = json.load(source)
        self.assertIs(schema["allow_insecure_local_http"]["default"], False)

        original_manager = plugin._config_mgr
        original_setting = plugin._allow_insecure_local_http
        try:
            plugin.OpenAI_OAuth_Plugin(
                _FakeContext(), config={"allow_insecure_local_http": True}
            )
            self.assertIs(plugin._allow_insecure_local_http, True)
            plugin.OpenAI_OAuth_Plugin(_FakeContext(), config={})
            self.assertIs(plugin._allow_insecure_local_http, False)
            plugin.OpenAI_OAuth_Plugin(
                _FakeContext(), config={"allow_insecure_local_http": "true"}
            )
            self.assertIs(plugin._allow_insecure_local_http, False)
        finally:
            plugin._config_mgr = original_manager
            plugin._allow_insecure_local_http = original_setting

    def test_remote_login_documentation_requires_https(self) -> None:
        for filename in ("README.md", "README_en.md"):
            with open(os.path.join(PLUGIN_ROOT, filename), encoding="utf-8") as source:
                content = source.read()
            self.assertNotIn("http://<host>", content)
            self.assertIn("https://<host>", content)
            self.assertIn("allow_insecure_local_http", content)

    def test_release_actions_are_pinned_to_full_commit_shas(self) -> None:
        workflow = os.path.join(PLUGIN_ROOT, ".github", "workflows", "release.yml")
        with open(workflow, encoding="utf-8") as source:
            content = source.read()
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)", content, flags=re.MULTILINE)
        self.assertGreaterEqual(len(uses), 3)
        for action in uses:
            self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
