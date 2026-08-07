"""无网络设备登录验证：mock 掉 create_proxy_client，验证协议函数与
Web handler（start/poll/后台任务）的完整流转，以及 JWT account_id 提取。

从仓库根运行：
    .venv/bin/python /Users/wcqqq1214/Project/astrbot_plugin_openai_oauth/login_test.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest import mock

# 解析 AstrBot 仓库根（本文件位于 Project/astrbot_plugin_openai_oauth/ 下）
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "AstrBot"))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)  # 使 `data` 命名空间包可解析

import importlib

plugin_mod = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
oauth = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.oauth")
from astrbot.api.web import PluginRequest, bind_request_context

FAILED = []


def check(cond: bool, msg: str) -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {msg}")
    if not cond:
        FAILED.append(msg)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def post(self, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((url, kwargs))
        if self._responses:
            return self._responses.pop(0)
        raise AssertionError("_FakeClient response queue exhausted")

    async def aclose(self) -> None:
        self.closed = True


def _jwt(payload: dict) -> str:
    def enc(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = enc(json.dumps({"alg": "RS256"}).encode())
    body = enc(json.dumps(payload).encode())
    return f"{header}.{body}.sig"


def test_usercode() -> None:
    print("=== 1. request_device_user_code ===")
    client = _FakeClient(
        [
            _FakeResponse(
                200, {"device_auth_id": "d1", "user_code": "ABCD-1234", "interval": 5}
            )
        ]
    )
    with mock.patch.object(oauth, "create_proxy_client", return_value=client):
        result = asyncio.run(oauth.request_device_user_code())
    check(result == ("d1", "ABCD-1234", 5), "解析 device_auth_id/user_code/interval")
    check(client.closed, "client 已关闭")

    client2 = _FakeClient(
        [_FakeResponse(200, {"device_auth_id": "d2", "usercode": "WXYZ-9876"})]
    )
    with mock.patch.object(oauth, "create_proxy_client", return_value=client2):
        result2 = asyncio.run(oauth.request_device_user_code())
    check(result2 == ("d2", "WXYZ-9876", 5), "usercode 别名与默认 interval")

    client3 = _FakeClient([_FakeResponse(404)])
    with mock.patch.object(oauth, "create_proxy_client", return_value=client3):
        try:
            asyncio.run(oauth.request_device_user_code())
            check(False, "404 应抛出 DeviceAuthError")
        except oauth.DeviceAuthError as exc:
            check("device code 登录未启用" in str(exc), "404 → 未启用提示")


def test_poll() -> None:
    print("\n=== 2. poll_device_authorization ===")
    client = _FakeClient(
        [
            _FakeResponse(403),
            _FakeResponse(404),
            _FakeResponse(200, {"authorization_code": "ac1", "code_verifier": "cv1"}),
        ]
    )
    with mock.patch.object(oauth, "create_proxy_client", return_value=client):
        result = asyncio.run(oauth.poll_device_authorization("d", "u", 0.01))
    check(
        result == ("ac1", "cv1"),
        "403/404 等待后 200 返回 (authorization_code, code_verifier)",
    )

    timeout_client = _FakeClient([_FakeResponse(403)] * 50)
    with mock.patch.object(oauth, "create_proxy_client", return_value=timeout_client):
        try:
            asyncio.run(
                oauth.poll_device_authorization("d", "u", 0.01, timeout_seconds=0.05)
            )
            check(False, "持续等待应超时")
        except oauth.DeviceAuthTimeout:
            check(True, "超时抛 DeviceAuthTimeout")


def test_exchange() -> None:
    print("\n=== 3. exchange_authorization_code ===")
    payload = {"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600}
    client = _FakeClient([_FakeResponse(200, payload)])
    with mock.patch.object(oauth, "create_proxy_client", return_value=client):
        result = asyncio.run(oauth.exchange_authorization_code("ac1", "cv1"))
    check(result == payload, "返回原始 token 载荷")
    _, kwargs = client.calls[0]
    form = kwargs["data"]
    check(form["grant_type"] == "authorization_code", "grant_type=authorization_code")
    check(
        form["code"] == "ac1" and form["code_verifier"] == "cv1", "code + code_verifier"
    )
    check(form["redirect_uri"] == oauth.CODEX_OAUTH_REDIRECT_URI, "redirect_uri 正确")
    check(form["client_id"] == oauth.CODEX_OAUTH_CLIENT_ID, "client_id 正确")


def test_jwt() -> None:
    print("\n=== 4. extract_account_id / build_credentials ===")
    token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "user-abc"}})
    check(
        oauth.extract_account_id(token) == "user-abc", "从嵌套 auth claim 提取账号 id"
    )
    check(
        oauth.extract_account_id("sk-ant-oat01-" + token) == "user-abc",
        "带前缀也能提取",
    )
    check(
        oauth.extract_account_id(
            _jwt({"https://api.openai.com/auth.chatgpt_account_id": "user-abc"})
        )
        == "user-abc",
        "旧版平铺 claim 也能提取",
    )
    check(oauth.extract_account_id("not-a-jwt") == "", "非 JWT 返回空串")
    check(oauth.extract_account_id(_jwt({})) == "", "无账号 id claim 返回空串")

    creds = oauth.build_credentials(token, "rt2", 3600)
    check(creds["access_token"] == token, "build_credentials 保留 access_token")
    check(creds["refresh_token"] == "rt2", "保留 refresh_token")
    check(
        creds["expires"] > time.time() and creds["expires"] <= time.time() + 3600,
        "expires 为绝对时间",
    )
    check(creds["account_id"] == "user-abc", "自动写入 account_id")


class _FakeRequest:
    def __init__(self, json_data: dict):
        self.json_data = json_data
        self.method = "POST"
        self.url = SimpleNamespace(path="/x")
        self.headers = {}
        self.cookies = {}
        self.client = SimpleNamespace(host="test")
        self.query_params = SimpleNamespace(multi_items=list)

    async def json(self):
        return self.json_data


def test_handlers() -> None:
    print("\n=== 5. Web handler：start → 后台任务 → poll ===")
    plugin_mod._login_sessions.clear()
    req = _FakeRequest({})
    plugin_req = PluginRequest(req)

    async def _run():
        with bind_request_context(plugin_req):
            resp = await plugin_mod._handle_device_start()
        return resp

    with (
        mock.patch.object(
            plugin_mod,
            "request_device_user_code",
            new=mock.AsyncMock(return_value=("d", "CODE-1234", 5)),
        ),
        mock.patch.object(
            plugin_mod,
            "poll_device_authorization",
            new=mock.AsyncMock(return_value=("ac", "cv")),
        ),
        mock.patch.object(
            plugin_mod,
            "exchange_authorization_code",
            new=mock.AsyncMock(
                return_value={
                    "access_token": "at-ok",
                    "refresh_token": "rt-ok",
                    "expires_in": 3600,
                }
            ),
        ),
    ):
        start_resp = asyncio.run(_run())
    start_data = json.loads(start_resp.body)
    check(start_data["status"] == "pending", "start 立即返回 pending")
    check(start_data["verify_url"] == oauth.CODEX_DEVICE_VERIFY_URL, "返回验证 URL")
    check(start_data["user_code"] == "CODE-1234", "返回 user_code")
    session_id = start_data["session_id"]
    check(bool(session_id), "返回 session_id")

    async def _poll():
        req2 = _FakeRequest({"session_id": session_id})
        with bind_request_context(PluginRequest(req2)):
            return await plugin_mod._handle_device_poll()

    # 让后台任务跑完（协议函数都被打桩，无真实等待）
    async def _settle():
        for _ in range(10):
            await asyncio.sleep(0)
            session = plugin_mod._login_sessions.get(session_id)
            if session and session["status"] == "success":
                break

    asyncio.run(_settle())
    poll_data = json.loads(asyncio.run(_poll()).body)
    check(poll_data["status"] == "success", "后台任务完成后 poll 返回 success")
    check(poll_data["creds"]["access_token"] == "at-ok", "凭据含 access_token")
    check(poll_data["creds"]["refresh_token"] == "rt-ok", "凭据含 refresh_token")
    check(poll_data["creds"]["account_id"] == "", "无账号 id 时为空串")

    # 未启用：start 应返回 error
    plugin_mod._login_sessions.clear()

    async def _start_error():
        with bind_request_context(PluginRequest(_FakeRequest({}))):
            return await plugin_mod._handle_device_start()

    with mock.patch.object(
        plugin_mod,
        "request_device_user_code",
        new=mock.AsyncMock(side_effect=oauth.DeviceAuthError("device code 登录未启用")),
    ):
        err_resp = asyncio.run(_start_error())
    err_data = json.loads(err_resp.body)
    check(
        err_data["status"] == "error" and "未启用" in err_data["message"],
        "未启用时 start 返回 error",
    )


def test_login_page() -> None:
    print("\n=== 6. 登录页 HTML 可服务 ===")
    resp = asyncio.run(plugin_mod._handle_login_page())
    html = resp.body.decode()
    check(
        resp.status_code == 200 and html.startswith("<!doctype html>"), "返回 HTML 页面"
    )
    check(
        "/device/start" in html and "/device/poll" in html, "页面调用 start/poll 接口"
    )
    check("开始登录" in html, "页面含登录按钮")


def main() -> int:
    test_usercode()
    test_poll()
    test_exchange()
    test_jwt()
    test_handlers()
    test_login_page()
    print()
    if FAILED:
        print(f"=== 登录验证失败：{len(FAILED)} 项 ===")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("=== 登录验证全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
