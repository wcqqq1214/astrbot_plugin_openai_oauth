"""无网络设备登录验证：mock 掉 create_proxy_client，验证协议函数与
Web handler（start/poll/后台任务）的完整流转，以及 JWT account_id 提取。

从仓库根运行（需 AstrBot 仓库 venv，见 AGENTS.md）：
    /Users/wcqqq1214/Project/AstrBot/.venv/bin/python \
        /Users/wcqqq1214/Project/astrbot_plugin_openai_oauth/tests/login_test.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

# 解析 AstrBot 仓库根（本文件位于 Project/astrbot_plugin_openai_oauth/tests/ 下）
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
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

    async def get(self, url: str, **kwargs) -> _FakeResponse:
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


class _FakeConf(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = 0

    async def save_config_async(self) -> None:
        self.saved += 1


class _FakeConfigMgr:
    def __init__(self, conf: dict):
        self.default_conf = _FakeConf(conf)


def test_save_creds() -> None:
    print("\n=== 7. save_creds：更新已有 source / 自动创建 / 校验 ===")
    old_mgr = plugin_mod._config_mgr
    try:
        # 7a: 已有 source 时更新 key
        conf = {
            "provider_sources": [
                {
                    "type": plugin_mod._PROVIDER_TYPE,
                    "id": plugin_mod._PROVIDER_TYPE,
                    "key": "old",
                }
            ]
        }
        mgr = _FakeConfigMgr(conf)
        plugin_mod._config_mgr = mgr

        async def _update():
            req = _FakeRequest(
                {"creds": {"access_token": "at1", "refresh_token": "rt1"}}
            )
            with bind_request_context(PluginRequest(req)):
                return await plugin_mod._handle_save_creds()

        data = json.loads(asyncio.run(_update()).body)
        check(data["status"] == "ok", "已有 source 时 save_creds 返回 ok")
        key = json.loads(conf["provider_sources"][0]["key"])
        check(key["access_token"] == "at1", "凭据写入已有 source 的 key")
        check(len(conf["provider_sources"]) == 1, "不新增重复 source")
        check(mgr.default_conf.saved == 1, "配置已保存")

        # 7b: 无 source 时自动创建
        conf2 = {
            "provider_sources": [{"id": "deepseek", "type": "deepseek", "key": []}]
        }
        mgr2 = _FakeConfigMgr(conf2)
        plugin_mod._config_mgr = mgr2

        async def _create():
            req = _FakeRequest({"creds": {"access_token": "at2"}})
            with bind_request_context(PluginRequest(req)):
                return await plugin_mod._handle_save_creds()

        data2 = json.loads(asyncio.run(_create()).body)
        check(data2["status"] == "ok", "无 source 时自动创建返回 ok")
        created = [
            s
            for s in conf2["provider_sources"]
            if s.get("type") == plugin_mod._PROVIDER_TYPE
        ]
        check(len(created) == 1, "自动创建了 source")
        check(created[0]["id"] == plugin_mod._PROVIDER_TYPE, "创建的 source id=type")
        check(created[0]["enable"] is True, "创建的 source enable=True")
        check(created[0]["provider"] == "openai", "创建的 source 带图标字段")
        check(
            json.loads(created[0]["key"])["access_token"] == "at2",
            "创建的 source 带 key",
        )
        check(mgr2.default_conf.saved == 1, "创建后已保存")

        # 7c: 无效凭据
        async def _invalid():
            req = _FakeRequest({"creds": {}})
            with bind_request_context(PluginRequest(req)):
                return await plugin_mod._handle_save_creds()

        data3 = json.loads(asyncio.run(_invalid()).body)
        check(data3["status"] == "error", "空凭据返回 error")
    finally:
        plugin_mod._config_mgr = old_mgr


def test_persist_key() -> None:
    print("\n=== 8. _persist_key：刷新凭据写回 provider_sources 而非 provider ===")
    old_mgr = plugin_mod._config_mgr
    try:
        conf = {
            "provider_sources": [
                {
                    "type": plugin_mod._PROVIDER_TYPE,
                    "id": plugin_mod._PROVIDER_TYPE,
                    "key": "old",
                }
            ],
            "provider": [
                {
                    "id": f"{plugin_mod._PROVIDER_TYPE}/gpt-5.4-mini",
                    "provider_source_id": plugin_mod._PROVIDER_TYPE,
                    "model": "gpt-5.4-mini",
                }
            ],
        }
        mgr = _FakeConfigMgr(conf)
        plugin_mod._config_mgr = mgr
        provider = plugin_mod.ProviderOpenAICodex.__new__(
            plugin_mod.ProviderOpenAICodex
        )
        provider.creds = {"access_token": "new-at", "refresh_token": "new-rt"}
        provider.provider_config = {
            "id": f"{plugin_mod._PROVIDER_TYPE}/gpt-5.4-mini",
            "provider_source_id": plugin_mod._PROVIDER_TYPE,
        }
        asyncio.run(provider._persist_key())
        key = json.loads(conf["provider_sources"][0]["key"])
        check(key["access_token"] == "new-at", "刷新凭据写入 source key")
        check("key" not in conf["provider"][0], "不污染 provider 模型配置")
        check(mgr.default_conf.saved == 1, "配置已保存")

        # 找不到 source 时静默告警、不抛异常、不保存
        conf3 = {
            "provider_sources": [{"id": "deepseek", "type": "deepseek", "key": []}]
        }
        mgr3 = _FakeConfigMgr(conf3)
        plugin_mod._config_mgr = mgr3
        provider.provider_config = {"provider_source_id": "missing"}
        asyncio.run(provider._persist_key())
        check(mgr3.default_conf.saved == 0, "找不到 source 时不保存、不抛异常")
    finally:
        plugin_mod._config_mgr = old_mgr


def test_usage_fetch() -> None:
    print("\n=== 9. fetch_rate_limits：当前 schema / 旧版 schema / 401 ===")
    payload = {
        "plan_type": "plus",
        "rate_limit": {
            "allowed": True,
            "limit_reached": False,
            "primary_window": {
                "used_percent": 35,
                "limit_window_seconds": 18000,
                "reset_after_seconds": 1200,
                "reset_at": 1234567890,
            },
            "secondary_window": {
                "used_percent": 12,
                "limit_window_seconds": 604800,
                "reset_after_seconds": 95000,
                "reset_at": 1234567890,
            },
        },
    }
    client = _FakeClient([_FakeResponse(200, payload)])
    with mock.patch.object(oauth, "create_proxy_client", return_value=client):
        result = asyncio.run(oauth.fetch_rate_limits("at", "acc-1"))
    check(
        result["allowed"] is True and result["limit_reached"] is False,
        "解析 allowed/limit_reached",
    )
    windows = result["windows"]
    check(len(windows) == 2, "primary + secondary 两个窗口")
    check(
        windows[0]["used_percent"] == 35.0 and windows[0]["label_seconds"] == 18000,
        "primary 窗口 used_percent/窗口秒数",
    )
    check(windows[1]["reset_after_seconds"] == 95000, "secondary 窗口重置倒计时")
    url, kwargs = client.calls[0]
    check(url == oauth.CODEX_USAGE_URL, "请求 /wham/usage")
    check(kwargs["headers"]["Authorization"] == "Bearer at", "Authorization 头")
    check(kwargs["headers"]["ChatGPT-Account-Id"] == "acc-1", "账号 id 头")

    # 旧版 /wham/usage 形态：rate_limits.codex[] 带 usage/limit 秒数
    legacy = {
        "rate_limits": {
            "codex": [
                {
                    "key": "5h",
                    "usage_in_seconds": 6300,
                    "limit_in_seconds": 18000,
                    "resets_in_seconds": 1200,
                    "is_exceeded": False,
                },
                {
                    "key": "weekly",
                    "usage_in_seconds": 90000,
                    "limit_in_seconds": 750000,
                    "resets_in_seconds": 95000,
                    "is_exceeded": False,
                },
            ]
        }
    }
    client2 = _FakeClient([_FakeResponse(200, legacy)])
    with mock.patch.object(oauth, "create_proxy_client", return_value=client2):
        result2 = asyncio.run(oauth.fetch_rate_limits("at"))
    w2 = result2["windows"]
    check(len(w2) == 2, "旧版 schema 解析两个窗口")
    check(round(w2[0]["used_percent"], 1) == 35.0, "旧版 schema 换算百分比")
    check(w2[1]["label_seconds"] == 750000, "旧版 schema 保留窗口秒数")

    client3 = _FakeClient([_FakeResponse(401)])
    with mock.patch.object(oauth, "create_proxy_client", return_value=client3):
        try:
            asyncio.run(oauth.fetch_rate_limits("at"))
            check(False, "401 应抛 CredentialExpiredError")
        except oauth.CredentialExpiredError:
            check(True, "401 → CredentialExpiredError")


def test_usage_format() -> None:
    print("\n=== 10. format_usage：文本渲染 ===")
    local_tz = datetime.now(UTC).astimezone().tzinfo
    reset_ts = int(datetime(2026, 8, 8, 15, 30, tzinfo=local_tz).timestamp())
    msg = plugin_mod.format_usage(
        {
            "allowed": True,
            "limit_reached": False,
            "windows": [
                {
                    "label_seconds": 18000,
                    "used_percent": 35.0,
                    "reset_after_seconds": None,
                    "reset_at": reset_ts,
                },
                {
                    "label_seconds": 604800,
                    "used_percent": 12.0,
                    "reset_after_seconds": 95000,
                    "reset_at": None,
                },
            ],
        }
    )
    check(
        "5小时窗口" in msg and "剩余 65%" in msg and "已用" not in msg,
        "5 小时窗口渲染（不再显示已用比例）",
    )
    check("重置 8月8日 15:30" in msg, "reset_at → 准确本地时间")
    check("7天窗口" in msg and "剩余 88%" in msg, "7 天窗口渲染")
    check(
        re.search(r"\d{1,2}月\d{1,2}日 \d{2}:\d{2}", msg),
        "reset_after 推算出的准确时间",
    )
    check("状态：可用" not in msg, "正常状态不再渲染状态行")

    reached = plugin_mod.format_usage(
        {
            "allowed": False,
            "limit_reached": True,
            "windows": [],
        }
    )
    check(
        "已达额度上限" in reached and "当前账号暂无可用额度窗口" in reached,
        "上限/无窗口渲染",
    )


class _FakeEvent:
    def __init__(self):
        self.call_llm = True
        self.sent: list = []

    def should_call_llm(self, call_llm: bool) -> None:
        self.call_llm = call_llm

    async def send(self, message) -> None:
        self.sent.append(message)


def test_usage_command() -> None:
    print("\n=== 11. /usage 命令：未登录拦截 / 正常查询 ===")
    old_mgr = plugin_mod._config_mgr
    try:
        # 未登录：命令被拦截（静默，不触发默认 LLM，不回复）
        plugin_mod._config_mgr = _FakeConfigMgr({"provider_sources": []})
        ev = _FakeEvent()
        asyncio.run(plugin_mod.OpenAI_OAuth_Plugin.usage(None, ev))
        check(ev.call_llm is False, "未登录时阻止默认 LLM")
        check(ev.sent == [], "未登录时不发送任何内容")
        check(plugin_mod._is_logged_in() is False, "无 source 视为未登录")

        # 已登录：正常查询并回复
        mgr2 = _FakeConfigMgr(
            {
                "provider_sources": [
                    {
                        "type": plugin_mod._PROVIDER_TYPE,
                        "id": plugin_mod._PROVIDER_TYPE,
                        "key": oauth.dump_credentials(
                            {
                                "access_token": "at",
                                "account_id": "acc",
                                "refresh_token": "rt",
                            }
                        ),
                        "proxy": "",
                    }
                ]
            }
        )
        plugin_mod._config_mgr = mgr2
        check(plugin_mod._is_logged_in() is True, "有 access_token 视为已登录")

        async def _fetch(at: str, acc: str, proxy: str) -> dict:
            return {
                "allowed": True,
                "limit_reached": False,
                "windows": [
                    {
                        "label_seconds": 18000,
                        "used_percent": 35.0,
                        "reset_after_seconds": None,
                        "reset_at": None,
                    }
                ],
            }

        ev2 = _FakeEvent()
        with mock.patch.object(plugin_mod, "fetch_rate_limits", side_effect=_fetch):
            asyncio.run(plugin_mod.OpenAI_OAuth_Plugin.usage(None, ev2))
            msg2 = asyncio.run(plugin_mod.build_usage_message())
        check(len(ev2.sent) == 1, "已登录时发送一条回复")
        check(ev2.call_llm is True, "已登录时不改动 LLM 开关")
        check("剩余 65%" in msg2, "已登录时返回额度文本")
    finally:
        plugin_mod._config_mgr = old_mgr


def test_usage_retry() -> None:
    print("\n=== 12. /usage 查询：瞬时失败自动重试 / 持续失败信息非空 ===")
    old_mgr = plugin_mod._config_mgr
    try:
        conf = {
            "provider_sources": [
                {
                    "type": plugin_mod._PROVIDER_TYPE,
                    "id": plugin_mod._PROVIDER_TYPE,
                    "key": oauth.dump_credentials(
                        {"access_token": "at", "account_id": "acc"}
                    ),
                    "proxy": "",
                }
            ]
        }
        plugin_mod._config_mgr = _FakeConfigMgr(conf)
        creds = {"access_token": "at", "account_id": "acc"}

        # 瞬时超时：前两次失败后重试成功
        attempts = {"n": 0}

        async def _flaky(at, acc, proxy):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise TimeoutError()
            return {
                "allowed": True,
                "limit_reached": False,
                "windows": [
                    {
                        "label_seconds": 18000,
                        "used_percent": 35.0,
                        "reset_after_seconds": None,
                        "reset_at": None,
                    }
                ],
            }

        with mock.patch.object(
            plugin_mod, "load_credentials", return_value=creds
        ), mock.patch.object(plugin_mod, "fetch_rate_limits", side_effect=_flaky):
            msg = asyncio.run(plugin_mod.build_usage_message())
        check(attempts["n"] == 3, "瞬时超时自动重试到第 3 次")
        check("剩余 65%" in msg, "重试成功后返回额度文本")

        # 持续超时：重试耗尽后返回非空错误信息（TimeoutError 的 str 为空）
        async def _always_timeout(at, acc, proxy):
            raise TimeoutError()

        with mock.patch.object(
            plugin_mod, "load_credentials", return_value=creds
        ), mock.patch.object(
            plugin_mod, "fetch_rate_limits", side_effect=_always_timeout
        ):
            msg = asyncio.run(plugin_mod.build_usage_message())
        check(msg == "额度查询失败：TimeoutError", "持续超时报错信息非空")
    finally:
        plugin_mod._config_mgr = old_mgr


def main() -> int:
    test_usercode()
    test_poll()
    test_exchange()
    test_jwt()
    test_handlers()
    test_login_page()
    test_save_creds()
    test_persist_key()
    test_usage_fetch()
    test_usage_format()
    test_usage_command()
    test_usage_retry()
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
