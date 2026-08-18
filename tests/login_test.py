"""No-network device-login, account API, and Plugin Page regressions."""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

plugin = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
oauth = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.oauth")
from astrbot.api.web import PluginRequest, bind_request_context
from astrbot.core.star.filter.permission import PermissionType, PermissionTypeFilter
from astrbot.core.star.register.star_handler import star_handlers_registry

FAILED: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        FAILED.append(message)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def post(self, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((url, kwargs))
        if not self._responses:
            raise AssertionError("response queue exhausted")
        return self._responses.pop(0)

    async def get(self, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((url, kwargs))
        if not self._responses:
            raise AssertionError("response queue exhausted")
        return self._responses.pop(0)

    async def aclose(self) -> None:
        self.closed = True


class _FakeRequest:
    def __init__(self, body: dict | None = None) -> None:
        self._body = body or {}
        self.method = "POST"
        self.url = SimpleNamespace(path="/extension", scheme="https")
        self.headers = {"host": "astrbot.example"}
        self.cookies = {}
        self.client = SimpleNamespace(host="198.51.100.8")
        self.query_params = SimpleNamespace(multi_items=list)

    async def json(self) -> dict:
        return self._body


def request_context(body: dict | None = None, *, username: str = "astrbot"):
    return bind_request_context(PluginRequest(_FakeRequest(body), username=username))


class _FakeConfig(dict):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.saved = 0

    async def save_config_async(self) -> bool:
        self.saved += 1
        return True


class _FakeConfigManager:
    def __init__(self, conf: _FakeConfig) -> None:
        self.default_conf = conf


def source(*, key: str = "", proxy: str = "") -> dict:
    return {
        "id": plugin._PROVIDER_TYPE,
        "type": plugin._PROVIDER_TYPE,
        "provider": "openai",
        "provider_type": "chat_completion",
        "key": key,
        "proxy": proxy,
        "originator": oauth.DEFAULT_ORIGINATOR,
        "user_agent": oauth.DEFAULT_USER_AGENT,
        "enable": True,
    }


def set_config(sources: list[dict]) -> _FakeConfig:
    conf = _FakeConfig({"provider_sources": sources})
    plugin._config_mgr = _FakeConfigManager(conf)
    return conf


def payload(response) -> dict:
    return json.loads(response.body)


def sent_text(event) -> str:
    parts: list[str] = []
    for message in event.sent:
        for item in getattr(message, "chain", None) or []:
            parts.append(getattr(item, "text", str(item)))
    return "\n".join(parts)


def jwt(payload_data: dict) -> str:
    def encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = encode(json.dumps({"alg": "RS256"}).encode())
    return f"{header}.{encode(json.dumps(payload_data).encode())}.sig"


def test_oauth_protocol_helpers() -> None:
    print("=== OAuth protocol helpers ===")
    client = _FakeClient(
        [
            _FakeResponse(
                200, {"device_auth_id": "d1", "user_code": "ABCD-1234", "interval": 5}
            )
        ]
    )
    with mock.patch.object(oauth, "create_proxy_client", return_value=client):
        result = asyncio.run(oauth.request_device_user_code())
    check(result == ("d1", "ABCD-1234", 5), "device user code is parsed")
    check(client.closed, "device-code client is closed")

    poll_client = _FakeClient(
        [
            _FakeResponse(403),
            _FakeResponse(200, {"authorization_code": "ac", "code_verifier": "cv"}),
        ]
    )
    with mock.patch.object(oauth, "create_proxy_client", return_value=poll_client):
        result = asyncio.run(oauth.poll_device_authorization("d", "u", 0.01))
    check(result == ("ac", "cv"), "polling waits for authorization")

    exchange_client = _FakeClient(
        [
            _FakeResponse(
                200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
            )
        ]
    )
    with mock.patch.object(oauth, "create_proxy_client", return_value=exchange_client):
        tokens = asyncio.run(oauth.exchange_authorization_code("ac", "cv"))
    check(
        tokens["access_token"] == "at",
        "authorization code exchange returns token payload",
    )
    check(
        exchange_client.calls[0][1]["data"]["code_verifier"] == "cv",
        "PKCE verifier is sent",
    )

    token = jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "user-abc"}})
    creds = oauth.build_credentials(token, "refresh", 3600)
    check(creds["schema_version"] == 1, "new logins create schema-v1 credentials")
    check(creds["account_id"] == "user-abc", "nested JWT account ID is extracted")


def test_server_owned_web_login_and_source_proxy() -> None:
    print("\n=== Server-owned web login and source proxy ===")
    plugin._discard_all_login_sessions()
    conf = set_config([source(key="old", proxy="http://source-proxy:8080")])
    observed_proxy: list[str | None] = []

    async def request_code(proxy: str | None):
        observed_proxy.append(proxy)
        return "device", "CODE-1234", 1

    async def run():
        with (
            mock.patch.object(plugin, "request_device_user_code", new=request_code),
            mock.patch.object(
                plugin,
                "poll_device_authorization",
                new=mock.AsyncMock(return_value=("authorization", "verifier")),
            ),
            mock.patch.object(
                plugin,
                "exchange_authorization_code",
                new=mock.AsyncMock(
                    return_value={
                        "access_token": "sk-ant-oat01-server.server.server",
                        "refresh_token": "rt-server",
                        "expires_in": 3600,
                    }
                ),
            ),
        ):
            with request_context({"proxy": "http://browser-controlled:8080"}):
                started = await plugin._handle_device_start()
            start = payload(started)
            for _ in range(20):
                await asyncio.sleep(0)
                session = plugin._login_sessions.get(start["session_id"])
                if session and session["status"] != "pending":
                    break
            with request_context({"session_id": start["session_id"]}):
                completed = await plugin._handle_device_poll()
            return started, completed

    started, completed = asyncio.run(run())
    start = payload(started)
    done = payload(completed)
    stored = json.loads(conf["provider_sources"][0]["key"])
    check(start["status"] == "pending", "device start returns a pending session")
    check(start["user_code"] == "CODE-1234", "device code is returned to its owner")
    check(
        done == {"status": "success", "error": None},
        "completed poll returns no credential",
    )
    check(
        "access_token" not in done and "refresh_token" not in done,
        "browser never receives tokens",
    )
    check(
        observed_proxy == ["http://source-proxy:8080"], "browser proxy input is ignored"
    )
    check(stored["schema_version"] == 1, "login persists canonical credentials")
    check(
        stored["access_token"].endswith("server.server.server"),
        "server stores access token",
    )
    check(conf.saved == 1, "login saves configuration once")


def test_login_error_and_cancel() -> None:
    print("\n=== Login errors and cancellation ===")
    plugin._discard_all_login_sessions()
    set_config([source()])

    async def failed_start():
        with (
            mock.patch.object(
                plugin,
                "request_device_user_code",
                new=mock.AsyncMock(side_effect=oauth.DeviceAuthError("not enabled")),
            ),
            request_context(),
        ):
            return await plugin._handle_device_start()

    response = asyncio.run(failed_start())
    check(response.status_code == 400, "device-code setup errors are reported safely")

    async def wait_forever(*_args):
        await asyncio.Event().wait()

    async def run_cancel():
        with (
            mock.patch.object(
                plugin,
                "request_device_user_code",
                new=mock.AsyncMock(return_value=("device", "CODE", 5)),
            ),
            mock.patch.object(plugin, "_run_device_login", side_effect=wait_forever),
        ):
            with request_context(username="owner-a"):
                started = await plugin._handle_device_start()
            session_id = payload(started)["session_id"]
            with request_context({"session_id": session_id}, username="owner-b"):
                stolen = await plugin._handle_device_cancel()
            with request_context({"session_id": session_id}, username="owner-a"):
                cancelled = await plugin._handle_device_cancel()
            await asyncio.sleep(0)
            return stolen, cancelled, session_id

    stolen, cancelled, session_id = asyncio.run(run_cancel())
    check(stolen.status_code == 404, "another WebUI user cannot cancel a session")
    check(
        payload(cancelled) == {"status": "cancelled"},
        "owner can cancel a login session",
    )
    check(
        session_id not in plugin._login_sessions, "cancelling removes the login session"
    )


def test_account_status_and_usage_api() -> None:
    print("\n=== Account status and quota APIs ===")
    token = "sk-ant-oat01-account.account.account"
    conf = set_config(
        [
            source(
                key=json.dumps(
                    {
                        "access_token": token,
                        "refresh_token": "rt-account",
                        "expires": 9999999999,
                        "account_id": "user-private",
                    }
                )
            )
        ]
    )

    async def usage(*_args):
        return {
            "allowed": True,
            "limit_reached": False,
            "windows": [
                {
                    "label_seconds": 18000,
                    "used_percent": 35.0,
                    "reset_after_seconds": 1200,
                    "reset_at": None,
                }
            ],
        }

    async def run():
        with request_context():
            status = await plugin._handle_account_status()
        with (
            mock.patch.object(plugin, "fetch_rate_limits", new=usage),
            request_context(),
        ):
            quota = await plugin._handle_account_usage()
        return status, quota

    status, quota = asyncio.run(run())
    status_data = payload(status)
    quota_data = payload(quota)
    serialized = json.dumps({"status": status_data, "quota": quota_data})
    check(status_data["status"] == "ready", "status API exposes ready state")
    check(quota_data["status"] == "success", "usage API returns normalized quota")
    check(
        quota_data["usage"]["windows"][0]["used_percent"] == 35.0, "usage is normalized"
    )
    check(
        token not in serialized and "user-private" not in serialized,
        "account APIs do not expose credentials",
    )
    check(
        status.headers["cache-control"] == "no-store", "account status is never cached"
    )
    check(conf.saved == 0, "normal quota query does not rewrite credentials")


def test_private_command_fallback() -> None:
    print("\n=== Private administrator command fallback ===")
    set_config([source()])
    handler = next(
        item
        for item in star_handlers_registry
        if item.handler_name == "openai_login"
        and item.handler_module_path == plugin.__name__
    )
    check(
        any(
            isinstance(filter_, PermissionTypeFilter)
            and filter_.permission_type == PermissionType.ADMIN
            for filter_ in handler.event_filters
        ),
        "command keeps the AstrBot ADMIN filter",
    )

    class _Event:
        def __init__(self, private: bool = True) -> None:
            self.private = private
            self.unified_msg_origin = "test:FriendMessage:admin-1"
            self.call_llm = True
            self.sent: list = []

        def should_call_llm(self, value: bool) -> None:
            self.call_llm = value

        def is_private_chat(self) -> bool:
            return self.private

        async def send(self, message) -> None:
            self.sent.append(message)

    async def run():
        event = _Event()
        with (
            mock.patch.object(
                plugin,
                "request_device_user_code",
                new=mock.AsyncMock(return_value=("device", "CODE", 0)),
            ),
            mock.patch.object(
                plugin,
                "poll_device_authorization",
                new=mock.AsyncMock(return_value=("authorization", "verifier")),
            ),
            mock.patch.object(
                plugin,
                "exchange_authorization_code",
                new=mock.AsyncMock(
                    return_value={
                        "access_token": "sk-ant-oat01-command.command.command",
                        "refresh_token": "rt-command",
                        "expires_in": 3600,
                    }
                ),
            ),
        ):
            await plugin.OpenAI_OAuth_Plugin.openai_login(None, event)
            for _ in range(10):
                await asyncio.sleep(0)
        return event

    event = asyncio.run(run())
    sent = sent_text(event)
    check(event.call_llm is False, "command suppresses the default LLM")
    check("CODE" in sent, "command sends a one-time device code")
    check(
        "rt-command" not in sent and "command.command.command" not in sent,
        "command never sends tokens",
    )
    plugin._cancel_all_command_login_tasks()


def test_effort_command() -> None:
    print("\n=== Session reasoning-effort command ===")
    handler = next(
        item
        for item in star_handlers_registry
        if item.handler_name == "effort" and item.handler_module_path == plugin.__name__
    )
    check(
        any(
            isinstance(filter_, PermissionTypeFilter)
            and filter_.permission_type == PermissionType.ADMIN
            for filter_ in handler.event_filters
        ),
        "/effort keeps the AstrBot ADMIN filter",
    )

    class _Provider:
        def __init__(self, provider_type: str) -> None:
            self.provider_type = provider_type
            self.provider_config = {"custom_extra_body": {"reasoning_effort": "medium"}}

        def meta(self):
            return SimpleNamespace(type=self.provider_type)

    class _Context:
        def __init__(self, provider) -> None:
            self.provider = provider
            self.umos: list[str] = []

        async def get_using_provider_async(self, umo: str):
            self.umos.append(umo)
            return self.provider

    class _Event:
        def __init__(self) -> None:
            self.unified_msg_origin = "test:FriendMessage:effort-session"
            self.call_llm = True
            self.sent: list = []

        def should_call_llm(self, value: bool) -> None:
            self.call_llm = value

        async def send(self, message) -> None:
            self.sent.append(message)

    provider = _Provider(plugin._PROVIDER_TYPE)
    context = _Context(provider)
    plugin_instance = SimpleNamespace(context=context)
    event = _Event()
    fake_sp = SimpleNamespace(
        get_async=mock.AsyncMock(return_value="high"),
        put_async=mock.AsyncMock(),
        remove_async=mock.AsyncMock(),
    )

    async def run() -> None:
        with mock.patch.object(plugin, "sp", fake_sp):
            await plugin.OpenAI_OAuth_Plugin.effort(plugin_instance, event, "max")
            await plugin.OpenAI_OAuth_Plugin.effort(plugin_instance, event)
            await plugin.OpenAI_OAuth_Plugin.effort(
                plugin_instance,
                event,
                "default",
            )
            await plugin.OpenAI_OAuth_Plugin.effort(
                plugin_instance,
                event,
                "unsupported",
            )

    asyncio.run(run())
    check(event.call_llm is False, "/effort suppresses the default LLM")
    check(
        context.umos == [event.unified_msg_origin] * 4,
        "/effort resolves the active provider for the current UMO",
    )
    fake_sp.put_async.assert_awaited_once_with(
        "umo",
        event.unified_msg_origin,
        plugin._SESSION_EFFORT_KEY,
        "max",
    )
    fake_sp.remove_async.assert_awaited_once_with(
        "umo",
        event.unified_msg_origin,
        plugin._SESSION_EFFORT_KEY,
    )
    text = sent_text(event)
    check("high" in text, "/effort shows the current session override")
    check("不支持" in text, "/effort rejects unsupported values")

    other_event = _Event()
    other_context = _Context(_Provider("openai"))
    other_instance = SimpleNamespace(context=other_context)
    other_sp = SimpleNamespace(
        get_async=mock.AsyncMock(),
        put_async=mock.AsyncMock(),
        remove_async=mock.AsyncMock(),
    )

    async def run_other_provider() -> None:
        with mock.patch.object(plugin, "sp", other_sp):
            await plugin.OpenAI_OAuth_Plugin.effort(
                other_instance,
                other_event,
                "high",
            )

    asyncio.run(run_other_provider())
    other_sp.put_async.assert_not_awaited()
    check(
        "未使用 OpenAI Subscribe" in sent_text(other_event),
        "/effort rejects non-OpenAI providers",
    )


def test_plugin_page_assets() -> None:
    print("\n=== Plugin Page bridge assets ===")
    page_root = os.path.join(os.path.dirname(__file__), "..", "pages", "login")
    with open(os.path.join(page_root, "index.html"), encoding="utf-8") as source_file:
        html = source_file.read()
    with open(os.path.join(page_root, "app.js"), encoding="utf-8") as source_file:
        app = source_file.read()

    check("./app.js" in html, "Plugin Page loads external JavaScript")
    check("/api/plugin/page/bridge-sdk.js" in html, "Plugin Page loads the bridge SDK")
    check("window.AstrBotPluginPage" in app, "Plugin Page uses the scoped bridge")
    check('bridge.apiPost("device/start", {})' in app, "page starts through the bridge")
    check('bridge.apiPost("device/poll"' in app, "page polls through the bridge")
    check('bridge.apiPost("device/cancel"' in app, "page can cancel through the bridge")
    check('bridge.apiPost("account/status"' in app, "page reads safe account status")
    check('bridge.apiPost("account/usage"' in app, "page queries quota explicitly")
    check("fetch(" not in app, "page does not bypass the bridge")
    check(
        "localStorage" not in app and "document.cookie" not in app,
        "page does not read credentials",
    )
    check("Authorization" not in app, "page does not handle Dashboard tokens")
    check("location.protocol" in app and "HTTPS" in app, "page warns on plain HTTP")


def main() -> int:
    old_manager = plugin._config_mgr
    try:
        test_oauth_protocol_helpers()
        test_server_owned_web_login_and_source_proxy()
        test_login_error_and_cancel()
        test_account_status_and_usage_api()
        test_private_command_fallback()
        test_effort_command()
        test_plugin_page_assets()
    finally:
        plugin._discard_all_login_sessions()
        plugin._cancel_all_command_login_tasks()
        plugin._config_mgr = old_manager
    print()
    if FAILED:
        print(f"=== Login regressions failed: {len(FAILED)} assertion(s) ===")
        for failure in FAILED:
            print(f"  - {failure}")
        return 1
    print("=== Login regressions passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
