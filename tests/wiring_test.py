"""无网络 provider 接线验证：用假凭据实例化 ProviderOpenAICodex，
断言 api_base / client key / custom_headers / get_keys / set_key /
无 token 时 get_models 回退 / 无需刷新时 _ensure_fresh_token 短路。

从仓库根运行（需 AstrBot 仓库 venv，见 AGENTS.md）：
    /Users/wcqqq1214/Project/AstrBot/.venv/bin/python \
        /Users/wcqqq1214/Project/astrbot_plugin_openai_oauth/tests/wiring_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest import mock

# 解析 AstrBot 仓库根（本文件位于 Project/astrbot_plugin_openai_oauth/tests/ 下）
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)  # 使 `data` 命名空间包可解析

import importlib

module = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
oauth = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.oauth")
ProviderOpenAICodex = module.ProviderOpenAICodex

FAILED = []

ACCESS_TOKEN = "sk-ant-oat01-aaaa.bbbb.cccc"
REFRESH_TOKEN = "rt-fake-refresh-token"
ACCOUNT_ID = "user-12345"


def check(cond: bool, msg: str) -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {msg}")
    if not cond:
        FAILED.append(msg)


def make_config(creds: dict) -> dict:
    return {
        "type": module._PROVIDER_TYPE,
        "key": json.dumps(creds),
        "model": "gpt-5.4-mini",
        "proxy": "",
        "originator": oauth.DEFAULT_ORIGINATOR,
        "user_agent": oauth.DEFAULT_USER_AGENT,
    }


def main() -> int:
    print("=== 1. 实例化：api_base / client key / 自定义头 ===")
    creds = {
        "access_token": ACCESS_TOKEN,
        "refresh_token": REFRESH_TOKEN,
        "expires": int(__import__("time").time()) + 99999,
        "account_id": ACCOUNT_ID,
    }
    prov = ProviderOpenAICodex(make_config(creds), {})
    check(
        prov.provider_config["api_base"] == oauth.CODEX_BASE, "api_base 指向 Codex 后端"
    )
    check(
        str(prov.client.base_url).rstrip("/") == oauth.CODEX_BASE,
        "client.base_url == CODEX_BASE",
    )
    check(prov.client.api_key == ACCESS_TOKEN, "client.api_key 已修正为 access_token")
    check(prov.api_keys == [ACCESS_TOKEN], "api_keys 列表同步")
    headers = prov.client.default_headers or {}
    check(
        headers.get("chatgpt-account-id") == ACCOUNT_ID,
        f"自定义头含 chatgpt-account-id: {headers.get('chatgpt-account-id')}",
    )
    check(
        headers.get("originator") == oauth.DEFAULT_ORIGINATOR, "自定义头含 originator"
    )
    check("OpenAI-Beta" in headers, "自定义头含 OpenAI-Beta")
    check(prov.model_name == "gpt-5.4-mini", f"model_name: {prov.model_name}")

    print("\n=== 2. get_keys / get_current_key ===")
    check(prov.get_keys() == [ACCESS_TOKEN], "get_keys 返回 access_token")
    check(prov.get_current_key() == ACCESS_TOKEN, "get_current_key 返回 access_token")

    print("\n=== 3. set_key：裸 token 与 JSON 凭据 ===")
    prov.set_key("sk-ant-oat01-new.new.new")
    check(
        prov.get_current_key() == "sk-ant-oat01-new.new.new",
        "裸 token 直接作为 access_token",
    )
    check(prov.client.api_key == "sk-ant-oat01-new.new.new", "client key 同步")
    check(
        (prov.client.default_headers or {}).get("chatgpt-account-id") is None,
        "裸 token 无 account_id 时清掉旧头",
    )
    new_creds = {
        "access_token": "sk-ant-oat01-two.two.two",
        "refresh_token": "rt-two",
        "expires": 9999999999,
        "account_id": "user-999",
    }
    prov.set_key(json.dumps(new_creds))
    check(
        prov.get_current_key() == "sk-ant-oat01-two.two.two",
        "JSON 凭据解析 access_token",
    )
    check(
        (prov.client.default_headers or {}).get("chatgpt-account-id") == "user-999",
        "JSON 凭据更新 account_id 头",
    )

    print("\n=== 4. 无 access_token 时 get_models 回退离线列表（不发网络请求） ===")
    no_token = ProviderOpenAICodex(make_config({"refresh_token": "rt-only"}), {})
    models = asyncio.run(no_token.get_models())
    check(models == list(oauth.CODEX_FALLBACK_MODELS), "无 token 返回离线模型列表")

    print("\n=== 5. _ensure_fresh_token 无需刷新时短路（不发网络请求） ===")
    future = ProviderOpenAICodex(
        make_config(
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "expires": 9999999999,
            }
        ),
        {},
    )
    asyncio.run(future._ensure_fresh_token())
    check(future.get_current_key() == ACCESS_TOKEN, "未过期时 token 不变")

    expired_no_refresh = ProviderOpenAICodex(
        make_config({"access_token": ACCESS_TOKEN, "expires": 1}), {}
    )
    asyncio.run(expired_no_refresh._ensure_fresh_token())
    check(
        expired_no_refresh.get_current_key() == ACCESS_TOKEN,
        "过期但无 refresh_token 时静默跳过",
    )

    print("\n=== 6. _persist_key：把凭据写回 provider_sources 的 source key ===")
    FRESH = {
        "access_token": "sk-ant-oat01-fresh.fresh.fresh",
        "refresh_token": "rt-fresh",
        "expires": 9999999999,
        "account_id": ACCOUNT_ID,
    }

    class _FakeConfig(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.saved = None

        async def save_config_async(self):
            self.saved = dict(self)
            return True

    class _FakeCfgMgr:
        def __init__(self, conf):
            self.default_conf = conf

    persist_prov = ProviderOpenAICodex(make_config(creds), {})
    persist_prov.provider_config["provider_source_id"] = "prov-1"
    stored = {
        "id": "prov-1",
        "type": module._PROVIDER_TYPE,
        "key": json.dumps(creds),
    }
    fake_conf = _FakeConfig({"provider_sources": [stored]})
    module._config_mgr = _FakeCfgMgr(fake_conf)
    persist_prov.creds = dict(FRESH)
    try:
        asyncio.run(persist_prov._persist_key())
        parsed = json.loads(stored["key"])
        check(
            parsed["access_token"] == FRESH["access_token"],
            "刷新后的 access_token 写回 key",
        )
        check(
            parsed["refresh_token"] == FRESH["refresh_token"], "refresh_token 一并写回"
        )
        check(parsed["account_id"] == ACCOUNT_ID, "account_id 一并写回")
        check(fake_conf.saved is not None, "save_config_async 被调用")
    finally:
        module._config_mgr = None

    no_mgr = ProviderOpenAICodex(make_config(creds), {})
    no_mgr.provider_config["provider_source_id"] = "prov-1"
    asyncio.run(no_mgr._persist_key())  # _config_mgr 为 None 时静默跳过
    check(True, "无 _config_mgr 时静默跳过")

    print(
        "\n=== 7.5 消息转换：system 角色映射为 developer（Codex 后端不接受 system） ==="
    )
    conv = ProviderOpenAICodex(make_config(creds), {})
    items = conv._convert_chat_messages_to_response_input(
        [
            {"role": "system", "content": "You are an assistant."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "bye"},
        ]
    )
    check(
        not [i for i in items if i.get("role") == "system"],
        "input 中不含 system 角色消息",
    )
    developer = [
        i.get("content")
        for i in items
        if i.get("type") == "message" and i.get("role") == "developer"
    ]
    check(
        developer == ["You are an assistant."],
        f"system 消息映射为 developer 且内容保留: {developer}",
    )
    roles = [i.get("role") for i in items if i.get("type") == "message"]
    check(
        roles == ["developer", "user", "assistant", "user"],
        f"消息角色序列正确: {roles}",
    )
    tool_items = conv._convert_chat_messages_to_response_input(
        [
            {"role": "user", "content": "call a tool"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {"name": "search", "arguments": '{"q":"x"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
        ]
    )
    types = [i.get("type") for i in tool_items]
    check(
        types == ["message", "function_call", "function_call_output"],
        f"function_call 链路转换不受影响: {types}",
    )

    print("\n=== 8. _ensure_fresh_token 刷新后自动持久化 ===")
    stored2 = {
        "id": "prov-2",
        "type": module._PROVIDER_TYPE,
        "key": json.dumps(creds),
    }
    fake_conf2 = _FakeConfig({"provider_sources": [stored2]})
    module._config_mgr = _FakeCfgMgr(fake_conf2)
    expired = ProviderOpenAICodex(
        make_config(
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "expires": 1,
                "account_id": ACCOUNT_ID,
            }
        ),
        {},
    )
    expired.provider_config["provider_source_id"] = "prov-2"
    try:
        with mock.patch.object(
            module,
            "refresh_access_token",
            new=mock.AsyncMock(return_value=dict(FRESH)),
        ):
            asyncio.run(expired._ensure_fresh_token())
        check(
            expired.get_current_key() == FRESH["access_token"],
            "内存 token 已刷新",
        )
        parsed2 = json.loads(stored2["key"])
        check(
            parsed2["access_token"] == FRESH["access_token"],
            "刷新结果持久化到配置",
        )
        check(
            parsed2["refresh_token"] == FRESH["refresh_token"],
            "轮换的 refresh_token 持久化",
        )
        check(fake_conf2.saved is not None, "save_config_async 被调用")
    finally:
        module._config_mgr = None

    print()
    if FAILED:
        print(f"=== 接线验证失败：{len(FAILED)} 项 ===")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("=== 接线验证全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
