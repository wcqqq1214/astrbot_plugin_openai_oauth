"""Codex OAuth token handling for the ChatGPT subscription backend.

Protocol constants and helpers follow the implementations in opencode,
openclaw and hermes-agent. The access token is a JWT (typically carrying an
`sk-ant-oat01-` prefix glued to the header) obtained from a Codex OAuth flow;
API calls go to the Responses-style endpoint under
`chatgpt.com/backend-api/codex`.
"""

from __future__ import annotations

import json
import time
from typing import Any

from astrbot import logger
from astrbot.core.utils.network_utils import create_proxy_client

CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_BASE = "https://chatgpt.com/backend-api/codex"
CODEX_MODELS_URL = f"{CODEX_BASE}/models"

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
