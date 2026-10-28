"""Codex OAuth token handling for the ChatGPT subscription backend.

Protocol constants and helpers follow the implementations in opencode,
openclaw, hermes-agent and magpie. The access token is a JWT obtained from a
Codex OAuth flow; API calls go to the Responses-style endpoint under
`chatgpt.com/backend-api/codex`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import platform
import re
import time
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.core.utils.network_utils import create_proxy_client, is_connection_error
from httpx import HTTPStatusError
from openai import APIConnectionError, APIError

CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_BASE = "https://chatgpt.com/backend-api/codex"
CODEX_MODELS_URL = f"{CODEX_BASE}/models"
# Window durations come from the response; Pro may return only a weekly window.
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

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

# The backend gates its newest models on the Codex version a client names, in
# both its User-Agent and the model catalog query: an older or placeholder
# version can get 404 "Model not found" for a model the catalog lists.
CODEX_CLIENT_VERSION = "0.162.0"
_USER_AGENT_MARKER = "astrbot-plugin-openai-oauth"
_VERSION_PATTERN = re.compile(r"\d+(?:\.\d+)+")
_VERSION_CACHE_SECONDS = 600
_codex_home: Path | None = None
_version_cache: tuple[float, Path | None, str] | None = None


def _platform_label() -> str:
    """Describe the host like Codex CLI does, e.g. ``Linux 6.8.0; x86_64``."""
    system = platform.system() or "Unknown"
    if system == "Darwin":
        system, release = "Mac OS", platform.mac_ver()[0]
    else:
        release = platform.release()
    match = _VERSION_PATTERN.search(release or "")
    label = f"{system} {match.group(0)}" if match else system
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine() or "unknown"
    )
    return f"{label}; {machine}"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def set_codex_home(path: str | os.PathLike[str] | None) -> None:
    """Remember where local Codex keeps its files for version discovery."""
    global _codex_home, _version_cache
    _codex_home = Path(path) if path else None
    _version_cache = None


def codex_client_version() -> str:
    """Name the newest of the built-in Codex version and local Codex's catalog.

    Codex CLI records the version it last fetched the catalog with in
    ``models_cache.json``. After a Codex update brings new models, that version
    is newer than the built-in one and unlocks them.
    """
    global _version_cache
    now = time.monotonic()
    if (
        _version_cache is not None
        and _version_cache[1] == _codex_home
        and now - _version_cache[0] < _VERSION_CACHE_SECONDS
    ):
        return _version_cache[2]
    version = CODEX_CLIENT_VERSION
    home = (
        _codex_home
        or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    )
    try:
        cached = json.loads((home / "models_cache.json").read_text("utf-8"))
        match = _VERSION_PATTERN.fullmatch(str(cached.get("client_version", "")))
        if match and _version_key(match.group(0)) > _version_key(version):
            version = match.group(0)
    except (OSError, ValueError, AttributeError):
        pass
    _version_cache = (now, _codex_home, version)
    return version


def default_user_agent() -> str:
    """Return a Codex CLI style User-Agent naming the current client version."""
    return (
        f"codex_cli_rs/{codex_client_version()} ({_platform_label()}) "
        f"{_USER_AGENT_MARKER}"
    )


DEFAULT_USER_AGENT = (
    f"codex_cli_rs/{CODEX_CLIENT_VERSION} ({_platform_label()}) {_USER_AGENT_MARKER}"
)


def resolve_user_agent(configured: Any) -> str:
    """Use a custom User-Agent as is; plugin defaults track the Codex version."""
    value = configured.strip() if isinstance(configured, str) else ""
    if not value or (value.startswith("codex_cli_rs/") and _USER_AGENT_MARKER in value):
        return default_user_agent()
    return value


def client_version_header(user_agent: str) -> str:
    """Name the same Codex version in the ``version`` header as the User-Agent."""
    match = re.match(r"codex_cli_rs/(\d+(?:\.\d+)+)", user_agent)
    return match.group(1) if match else codex_client_version()


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
    except Exception as exc:
        logger.error(
            "OpenAI Codex token refresh request failed: %s", type(exc).__name__
        )
        raise
    finally:
        await client.aclose()

    updated = dict(creds)
    updated["access_token"] = data["access_token"]
    if data.get("refresh_token"):
        updated["refresh_token"] = data["refresh_token"]
    if data.get("id_token"):
        updated["id_token"] = data["id_token"]
    updated["expires"] = int(time.time()) + int(data.get("expires_in", 3600))
    return updated


_MODEL_ID_KEYS = ("slug", "id", "model", "name")


def _catalog_items(data: Any) -> list[dict]:
    """Return the visible model entries of a /codex/models payload in order."""
    items: list[Any] = []
    if isinstance(data, dict):
        for key in ("models", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                items.extend(value)
    elif isinstance(data, list):
        items = list(data)
    entries = [
        item
        for item in items
        if isinstance(item, dict) and item.get("visibility") != "hide"
    ]

    def priority(item: dict) -> int | float:
        value = item.get("priority")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return math.inf
        return value

    # Codex orders its picker by priority; entries without one keep their place.
    return sorted(entries, key=priority)


def _catalog_model_id(item: dict) -> str:
    for key in _MODEL_ID_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# Reasoning levels each model accepts, from the live catalog. A level the model
# does not list is rejected by the backend with HTTP 400.
_catalog_efforts: dict[str, tuple[str, ...]] = {}
_local_catalog: tuple[Path, int, dict[str, tuple[str, ...]]] | None = None


def _effort_name(value: str) -> str:
    # Codex CLI calls the top level "ultra" and sends it as "max".
    value = value.strip().lower()
    return "max" if value == "ultra" else value


def _catalog_efforts_by_model(data: Any) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for item in _catalog_items(data):
        model_id = _catalog_model_id(item)
        levels = item.get("supported_reasoning_levels")
        if not model_id or not isinstance(levels, list):
            continue
        efforts = tuple(
            dict.fromkeys(
                _effort_name(level["effort"])
                for level in levels
                if isinstance(level, dict)
                and isinstance(level.get("effort"), str)
                and level["effort"].strip()
            )
        )
        if efforts:
            result[model_id] = efforts
    return result


def remember_catalog(data: Any) -> None:
    """Keep the reasoning levels a fetched catalog reports for each model."""
    _catalog_efforts.update(_catalog_efforts_by_model(data))


def supported_efforts(model: Any) -> tuple[str, ...] | None:
    """Return a model's reasoning levels when a catalog has listed them.

    The live catalog is fetched when models are listed; local Codex keeps the
    same catalog in ``models_cache.json``, which covers the time before that.
    """
    global _local_catalog
    if not isinstance(model, str) or not model:
        return None
    if model in _catalog_efforts:
        return _catalog_efforts[model]
    home = (
        _codex_home
        or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    )
    path = home / "models_cache.json"
    try:
        mtime = path.stat().st_mtime_ns
        if _local_catalog is None or _local_catalog[:2] != (path, mtime):
            parsed = _catalog_efforts_by_model(json.loads(path.read_text("utf-8")))
            _local_catalog = (path, mtime, parsed)
    except (OSError, ValueError):
        return None
    return _local_catalog[2].get(model)


def extract_model_ids(data: Any) -> list[str]:
    """Defensively extract one identifier per visible model from /codex/models."""
    ids: list[str] = []
    for item in _catalog_items(data):
        model_id = _catalog_model_id(item)
        if model_id and model_id not in ids:
            ids.append(model_id)
    return ids


async def fetch_models(
    access_token: str,
    account_id: str = "",
    proxy: str | None = None,
    originator: str = DEFAULT_ORIGINATOR,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    """Fetch and normalize the live Codex model catalog."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "originator": originator,
        "User-Agent": user_agent,
        "version": client_version_header(user_agent),
        "Accept": "application/json",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    client = create_proxy_client("OpenAI Codex", proxy)
    try:
        resp = await client.get(
            CODEX_MODELS_URL,
            params={"client_version": client_version_header(user_agent)},
            headers=headers,
            timeout=10,
        )
        try:
            resp.raise_for_status()
        except HTTPStatusError as exc:
            if classify_codex_error(exc) == "credential":
                raise CredentialExpiredError() from exc
            raise
        data = resp.json()
        remember_catalog(data)
        return extract_model_ids(data)
    finally:
        await client.aclose()


class DeviceAuthError(Exception):
    """设备登录流程的硬性失败（未启用、被拒绝等）。"""


class DeviceAuthTimeout(DeviceAuthError):
    """设备码在有效期内未被用户授权。"""


class CredentialExpiredError(Exception):
    """The upstream rejected the access token; credential recovery is required."""


def _status_code(error: BaseException) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _error_details(error: BaseException) -> tuple[str, str]:
    code = getattr(error, "code", "")
    message = ""
    body = getattr(error, "body", None)
    if body is None and isinstance(error, HTTPStatusError):
        try:
            body = error.response.json()
        except ValueError:
            pass
    if isinstance(body, dict):
        nested = body.get("error")
        payload = nested if isinstance(nested, dict) else body
        code = payload.get("code", nested if isinstance(nested, str) else code)
        message = payload.get("message", "")
    elif isinstance(body, str) and body.lower() in {"invalid_grant", "invalid_token"}:
        code = body
    if not message:
        message = str(error)
    return str(code or "").lower(), str(message or "").lower()


def classify_codex_error(error: BaseException) -> str:
    """Classify an upstream failure without exposing its raw payload."""
    if isinstance(error, APIConnectionError) or is_connection_error(error):
        return "temporary"
    status_code = _status_code(error)
    code, message = _error_details(error)
    if status_code == 401 or code in {"invalid_grant", "invalid_token"}:
        return "credential"
    if code == "usage_limit_reached" or (
        status_code == 429
        and ("usage_limit_reached" in code or "usage_limit_reached" in message)
    ):
        return "usage_limit"
    if status_code == 429 or code == "rate_limit_exceeded":
        return "rate_limit"
    if status_code in {408, 409, 500, 502, 503, 504, 529}:
        return "temporary"
    # SSE errors arrive as APIError without an HTTP error status. Only accept
    # explicit service failures; a generic "try again" is not sufficient.
    if status_code is None and isinstance(error, APIError):
        if code in {
            "server_error",
            "internal_server_error",
            "service_unavailable",
            "overloaded",
            "overloaded_error",
        }:
            return "temporary"
        if not code and "servers are currently overloaded" in message:
            return "temporary"
    return "other"


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


async def fetch_rate_limits(
    access_token: str,
    account_id: str = "",
    proxy: str | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict:
    """查询 ChatGPT 订阅剩余额度（GET /wham/usage）。

    返回 ``{"allowed": bool, "limit_reached": bool, "windows": [...]}``，
    每个 window 含 ``used_percent``/``label_seconds``/``reset_after_seconds``/
    ``reset_at``。当前后端返回 ``rate_limit.primary_window/secondary_window``
    （各带 used_percent）；兼容旧版 ``rate_limits.codex[]`` 的
    usage_in_seconds/limit_in_seconds 形态。
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": user_agent,
        "version": client_version_header(user_agent),
        "Accept": "application/json",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    client = create_proxy_client("OpenAI Codex", proxy)
    try:
        resp = await client.get(CODEX_USAGE_URL, headers=headers, timeout=15)
        try:
            resp.raise_for_status()
        except HTTPStatusError as exc:
            # A plain 403 (Cloudflare, region) says nothing about the token.
            if classify_codex_error(exc) == "credential":
                raise CredentialExpiredError() from exc
            raise
        data = resp.json()
    finally:
        await client.aclose()
    return _parse_usage_payload(data)


def _parse_usage_payload(data: Any) -> dict:
    allowed = True
    limit_reached = False
    windows: list[dict] = []
    rate_limit = data.get("rate_limit") if isinstance(data, dict) else None
    if isinstance(rate_limit, dict):
        allowed = bool(rate_limit.get("allowed", True))
        limit_reached = bool(rate_limit.get("limit_reached", False))
        for window in ("primary_window", "secondary_window"):
            item = rate_limit.get(window)
            if isinstance(item, dict):
                used = item.get("used_percent")
                if (
                    isinstance(used, bool)
                    or not isinstance(used, (int, float))
                    or not math.isfinite(used)
                ):
                    used = None
                windows.append(
                    {
                        "label_seconds": item.get("limit_window_seconds"),
                        "used_percent": float(used) if used is not None else None,
                        "reset_after_seconds": item.get("reset_after_seconds"),
                        "reset_at": item.get("reset_at"),
                    }
                )
    # 旧版 /wham/usage 形态：rate_limits.codex[].{usage_in_seconds,
    # limit_in_seconds, resets_in_seconds}
    if not windows and isinstance(data, dict):
        codex = data.get("rate_limits")
        if isinstance(codex, dict):
            codex = codex.get("codex")
        if isinstance(codex, list):
            for item in codex:
                if not isinstance(item, dict):
                    continue
                limit_s = item.get("limit_in_seconds")
                usage_s = item.get("usage_in_seconds")
                if (
                    not isinstance(limit_s, bool)
                    and isinstance(limit_s, (int, float))
                    and math.isfinite(limit_s)
                    and limit_s > 0
                ):
                    used = None
                    if (
                        not isinstance(usage_s, bool)
                        and isinstance(usage_s, (int, float))
                        and math.isfinite(usage_s)
                    ):
                        used = min(100.0, max(0.0, usage_s / limit_s * 100))
                    windows.append(
                        {
                            "label_seconds": int(limit_s),
                            "used_percent": used,
                            "reset_after_seconds": item.get("resets_in_seconds"),
                            "reset_at": None,
                        }
                    )
    return {
        "allowed": allowed,
        "limit_reached": limit_reached,
        "windows": windows,
        "plan_type": (
            data.get("plan_type")
            if isinstance(data, dict)
            and data.get("plan_type")
            in ("free", "go", "plus", "pro", "team", "business", "enterprise", "edu")
            else None
        ),
    }


def extract_account_id(access_token: str) -> str:
    """Read the ChatGPT account ID from an access token (a JWT).

    The ID is ``chatgpt_account_id`` inside the nested
    ``https://api.openai.com/auth`` claim; older tokens use a flat claim.
    """
    try:
        _, payload_b64, _ = access_token.split(".", 2)
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
        "schema_version": 1,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires": int(time.time()) + int(expires_in),
        "account_id": extract_account_id(access_token),
    }
