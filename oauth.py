"""Codex OAuth token handling for the ChatGPT subscription backend.

Protocol constants and helpers follow the implementations in opencode,
openclaw and hermes-agent. The access token is a JWT (typically carrying an
`sk-ant-oat01-` prefix glued to the header) obtained from a Codex OAuth flow;
API calls go to the Responses-style endpoint under
`chatgpt.com/backend-api/codex`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

from astrbot import logger
from astrbot.core.utils.network_utils import create_proxy_client

CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_BASE = "https://chatgpt.com/backend-api/codex"
CODEX_MODELS_URL = f"{CODEX_BASE}/models"

# Codex CLI 的新版设备登录流程（device_code_auth.rs）：先取 user_code，
# 用户去 codex/device 输入并授权，轮询到 authorization_code 后换 token。
# PKCE 的 code_verifier 由服务端在授权后随 authorization_code 一并下发。
CODEX_DEVICE_ACCOUNTS_BASE = "https://auth.openai.com/api/accounts"
CODEX_DEVICE_USERCODE_URL = f"{CODEX_DEVICE_ACCOUNTS_BASE}/deviceauth/usercode"
CODEX_DEVICE_TOKEN_URL = f"{CODEX_DEVICE_ACCOUNTS_BASE}/deviceauth/token"
CODEX_DEVICE_VERIFY_URL = "https://auth.openai.com/codex/device"
CODEX_OAUTH_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
CODEX_DEVICE_LOGIN_TIMEOUT = 15 * 60

# JWT payload 里承载 ChatGPT 账号 id 的 claim。新版 token 是嵌套对象
# `https://api.openai.com/auth` 下的 `chatgpt_account_id`；旧版是平铺 claim。
_CHATGPT_AUTH_CLAIM = "https://api.openai.com/auth"
_CHATGPT_ACCOUNT_ID_KEY = "chatgpt_account_id"
_CHATGPT_ACCOUNT_ID_CLAIM = "https://api.openai.com/auth.chatgpt_account_id"

# Models reachable through a ChatGPT subscription. The live catalog comes from
# GET /codex/models; this list is the offline fallback for the WebUI dropdown.
CODEX_FALLBACK_MODELS = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
]

# Cloudflare whitelists first-party clients by the originator header; the real
# Rust Codex CLI sends `codex_cli_rs`. Both are overridable per-provider.
DEFAULT_ORIGINATOR = "codex_cli_rs"
DEFAULT_USER_AGENT = "codex_cli_rs/0.0.0 (astrbot-plugin-openai-oauth)"


def load_credentials(raw: Any) -> dict:
    """Parse the credential JSON stored in the provider key field."""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def dump_credentials(creds: dict) -> str:
    return json.dumps(creds, ensure_ascii=False)


async def refresh_access_token(creds: dict, proxy: str | None = None) -> dict:
    """Refresh the access token via the OAuth refresh-token grant.

    Refresh tokens are single-use and may rotate, so the response's
    refresh_token (when present) replaces the stored one. Returns an updated
    credential dict (access_token, refresh_token, expires).
    """
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        raise ValueError("No refresh_token available to refresh with")
    client = create_proxy_client("OpenAI Codex", proxy)
    try:
        resp = await client.post(
            CODEX_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_OAUTH_CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"OpenAI Codex token refresh request failed: {e}")
        raise
    finally:
        await client.aclose()

    updated = dict(creds)
    updated["access_token"] = data["access_token"]
    if data.get("refresh_token"):
        updated["refresh_token"] = data["refresh_token"]
    updated["expires"] = int(time.time()) + int(data.get("expires_in", 3600))
    return updated


def extract_model_ids(data: Any) -> list[str]:
    """Defensively extract model identifiers from the /codex/models payload."""
    ids: list[str] = []

    def add(item: Any) -> None:
        if not isinstance(item, dict):
            return
        for key in ("slug", "id", "model", "name"):
            value = item.get(key)
            if isinstance(value, str) and value and value not in ids:
                ids.append(value)

    if isinstance(data, dict):
        for key in ("data", "models", "items"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    add(item)
    elif isinstance(data, list):
        for item in data:
            add(item)
    return ids


class DeviceAuthError(Exception):
    """设备登录流程的硬性失败（未启用、被拒绝等）。"""


class DeviceAuthTimeout(DeviceAuthError):
    """设备码在有效期内未被用户授权。"""


async def request_device_user_code(proxy: str | None = None) -> tuple[str, str, int]:
    """请求一个设备码，返回 ``(device_auth_id, user_code, interval)``。

    该流程要求 ChatGPT 账号已开启 “Enable device code authentication for
    Codex”（安全设置），否则接口返回 404。
    """
    client = create_proxy_client("OpenAI Codex", proxy)
    try:
        resp = await client.post(
            CODEX_DEVICE_USERCODE_URL,
            json={"client_id": CODEX_OAUTH_CLIENT_ID},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if resp.status_code == 404:
            raise DeviceAuthError(
                "device code 登录未启用：请先在 ChatGPT 安全设置中开启"
                " “Enable device code authentication for Codex”"
            )
        resp.raise_for_status()
        data = resp.json()
    finally:
        await client.aclose()
    device_auth_id = data["device_auth_id"]
    user_code = data.get("user_code") or data.get("usercode")
    if not user_code:
        raise DeviceAuthError("OpenAI 未返回 user_code。")
    interval = int(data.get("interval", 5))
    return device_auth_id, user_code, interval


async def poll_device_authorization(
    device_auth_id: str,
    user_code: str,
    interval: int,
    proxy: str | None = None,
    timeout_seconds: int = CODEX_DEVICE_LOGIN_TIMEOUT,
) -> tuple[str, str]:
    """轮询用户是否完成授权，返回 ``(authorization_code, code_verifier)``。

    403/404 表示仍在等待；到时抛 ``DeviceAuthTimeout``。
    """
    client = create_proxy_client("OpenAI Codex", proxy)
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            try:
                resp = await client.post(
                    CODEX_DEVICE_TOKEN_URL,
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Accept": "application/json"},
                    timeout=30,
                )
            except Exception:  # noqa: BLE001 - 瞬时网络错误只需继续轮询
                logger.warning("Codex 设备登录轮询网络错误，重试。")
                continue
            if resp.status_code == 200:
                data = resp.json()
                return data["authorization_code"], data["code_verifier"]
            if resp.status_code in (403, 404):
                continue  # 尚未授权
            raise DeviceAuthError(f"设备登录轮询失败：HTTP {resp.status_code}")
    finally:
        await client.aclose()
    raise DeviceAuthTimeout("设备码已过期，请在 15 分钟内完成授权。")


async def exchange_authorization_code(
    authorization_code: str,
    code_verifier: str,
    proxy: str | None = None,
) -> dict:
    """用授权码换取 token，返回原始 token 载荷（access_token 等）。"""
    client = create_proxy_client("OpenAI Codex", proxy)
    try:
        resp = await client.post(
            CODEX_OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CODEX_OAUTH_CLIENT_ID,
                "code": authorization_code,
                "code_verifier": code_verifier,
                "redirect_uri": CODEX_OAUTH_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        await client.aclose()


def extract_account_id(access_token: str) -> str:
    """从 access_token（JWT，可能带 sk-ant-oat01- 前缀）里解出 ChatGPT 账号 id。

    账号 id 在嵌套 claim ``https://api.openai.com/auth`` 的
    ``chatgpt_account_id`` 字段；旧版平铺 claim 也兼容。
    """
    token = access_token.removeprefix("sk-ant-oat01-")
    try:
        _, payload_b64, _ = token.split(".", 2)
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    except Exception:  # noqa: BLE001 - 非 JWT 时静默返回空串
        return ""
    auth_claims = payload.get(_CHATGPT_AUTH_CLAIM)
    if isinstance(auth_claims, dict):
        value = auth_claims.get(_CHATGPT_ACCOUNT_ID_KEY)
        if isinstance(value, str) and value:
            return value
    value = payload.get(_CHATGPT_ACCOUNT_ID_CLAIM)
    return value if isinstance(value, str) else ""


def build_credentials(
    access_token: str,
    refresh_token: str,
    expires_in: int,
) -> dict:
    """把登录/刷新结果组装成 provider key 字段使用的凭据 JSON。"""
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires": int(time.time()) + int(expires_in),
        "account_id": extract_account_id(access_token),
    }
