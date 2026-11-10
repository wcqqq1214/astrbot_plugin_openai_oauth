"""Generate a single image with the OAuth account that served the chat."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx

from . import oauth, runtime
from .credential_store import CredentialSnapshot, jwt_claims

if TYPE_CHECKING:
    from .provider import ProviderOpenAICodex

IMAGE_MODEL = "gpt-image-2"
TOOL_NAME = "codex_generate_image"
SIZES = ("auto", "1024x1024", "1024x1536", "1536x1024")
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class ChatAccount:
    provider_id: str
    source_id: str
    identity: str


tool_account: ContextVar[ChatAccount | None] = ContextVar(
    "codex_image_account", default=None
)


def account_identity(snapshot: CredentialSnapshot) -> str:
    if snapshot.account_id:
        claims = jwt_claims(snapshot.access_token)
        auth = claims.get("https://api.openai.com/auth")
        user = auth.get("chatgpt_user_id") if isinstance(auth, dict) else None
        return f"account:{snapshot.account_id}:{user or claims.get('sub') or ''}"
    return "token:" + hashlib.sha256(snapshot.access_token.encode()).hexdigest()


class ImageError(RuntimeError):
    """A message catalog key safe to show in chat."""


async def generate(
    provider: ProviderOpenAICodex, account: ChatAccount, prompt: str, size: str
) -> bytes:
    prompt = prompt.strip()
    if not prompt or len(prompt) > 32000:
        raise ImageError("image.prompt")
    if size not in SIZES:
        raise ImageError("image.size")
    coordinator = runtime.get_coordinator()

    def current() -> CredentialSnapshot:
        snapshot = coordinator.ensure_inference_available(account.source_id)
        if account_identity(snapshot) != account.identity:
            raise ImageError("image.account_changed")
        return snapshot

    payload = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "size": size,
        "n": 1,
        "output_format": "png",
    }
    turn_id = str(uuid4())
    try:
        async with asyncio.timeout(300):
            for refresh in (False, True):
                current()
                snapshot = await coordinator.get_snapshot(
                    account.source_id, force_refresh=refresh
                )
                if account_identity(snapshot) != account.identity:
                    raise ImageError("image.account_changed")
                async with provider.source_transport(snapshot) as (
                    transport,
                    headers,
                ):
                    if current().access_token != snapshot.access_token:
                        raise ImageError("image.account_changed")
                    headers = {
                        name: value
                        for name, value in headers.items()
                        if name.lower()
                        not in {
                            "accept",
                            "authorization",
                            "content-type",
                            "x-codex-imagegen-request-id",
                            "x-codex-image-turn-id",
                        }
                    }
                    headers.update(
                        {
                            "Accept": "application/json",
                            "Authorization": f"Bearer {snapshot.access_token}",
                            "x-codex-imagegen-request-id": str(uuid4()),
                            "x-codex-image-turn-id": turn_id,
                        }
                    )
                    async with transport.stream(
                        "POST",
                        f"{oauth.CODEX_BASE}/images/generations",
                        json=payload,
                        headers=headers,
                        follow_redirects=False,
                        timeout=300,
                    ) as response:
                        if response.status_code == 401 and not refresh:
                            continue
                        if response.status_code == 401:
                            coordinator.mark_reauthentication(snapshot)
                            raise ImageError("usage.reauth_required")
                        if response.status_code == 403:
                            raise ImageError("image.forbidden")
                        if response.status_code == 429:
                            raise ImageError("image.limit")
                        if not response.is_success:
                            raise ImageError("image.failed")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                                raise ImageError("image.failed")
                            body.extend(chunk)
                        return _decode_image(body)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ImageError("image.timeout") from exc
    except httpx.HTTPError as exc:
        raise ImageError("image.failed") from exc
    raise ImageError("image.failed")


def _decode_image(body: bytearray) -> bytes:
    try:
        encoded = json.loads(body)["data"][0]["b64_json"]
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ImageError("image.failed") from exc
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ImageError("image.failed")
    return image
