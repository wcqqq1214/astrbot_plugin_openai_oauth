"""Generate a single image with the OAuth account that served the chat."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass
from io import BytesIO
from math import isfinite
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
from PIL import Image

from . import oauth, runtime
from .credential_store import CredentialSnapshot, jwt_claims

if TYPE_CHECKING:
    from .provider import ProviderOpenAICodex

IMAGE_MODEL = "gpt-image-2"
TOOL_NAME = "codex_generate_image"
SIZES = ("auto", "1024x1024", "1024x1536", "1536x1024")
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 16 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 300
_PNG_END = b"\x00\x00\x00\x00IEND\xaeB\x60\x82"


def _valid_timeout(timeout: object) -> bool:
    return (
        isinstance(timeout, (int, float))
        and not isinstance(timeout, bool)
        and isfinite(timeout)
        and timeout > 0
    )


def timeout_for_session(config: dict, *, runner_timeout: float | None = None) -> float:
    runner = config.get("agent", config.get("agent_runner", {}))
    timeout = runner.get("config", {}).get("misc", {}).get("tool_call_timeout", 120)
    if not _valid_timeout(timeout):
        timeout = 120
    if runner_timeout is not None and _valid_timeout(runner_timeout):
        timeout = min(timeout, runner_timeout)
    # Leave time for AstrBot to receive the tool result before its own deadline.
    return min(MAX_TIMEOUT_SECONDS, timeout - min(1.0, timeout / 10))


@dataclass(frozen=True)
class ChatAccount:
    provider_id: str
    source_id: str
    identity: str


@dataclass(frozen=True)
class ToolInvocation:
    account: ChatAccount
    runner_timeout: float | None


tool_invocation: ContextVar[ToolInvocation | None] = ContextVar(
    "codex_image_tool_invocation", default=None
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

    def validate_account(snapshot: CredentialSnapshot) -> None:
        if account_identity(snapshot) != account.identity:
            raise ImageError("image.account_changed")

    def current() -> CredentialSnapshot:
        snapshot = coordinator.ensure_inference_available(account.source_id)
        validate_account(snapshot)
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
        for refresh in (False, True):
            current()
            snapshot = await coordinator.get_snapshot(
                account.source_id,
                force_refresh=refresh,
                validate_snapshot=validate_account,
            )
            validate_account(snapshot)
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
                    timeout=MAX_TIMEOUT_SECONDS,
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
                    return await asyncio.to_thread(_decode_image, body)
    except httpx.TimeoutException as exc:
        raise ImageError("image.timeout") from exc
    except httpx.HTTPError as exc:
        raise ImageError("image.failed") from exc
    raise ImageError("image.failed")


def _decode_image(body: bytearray) -> bytes:
    try:
        encoded = json.loads(body)["data"][0]["b64_json"]
        image = base64.b64decode(encoded, validate=True)
        if not image.endswith(_PNG_END):
            raise ValueError("Missing PNG end chunk.")
        stream = BytesIO(image)
        with Image.open(stream, formats=("PNG",)) as png:
            if png.width * png.height > MAX_IMAGE_PIXELS:
                raise ValueError("PNG exceeds the pixel limit.")
            png.verify()
        stream.seek(0)
        with Image.open(stream, formats=("PNG",)) as png:
            png.load()
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as exc:
        raise ImageError("image.failed") from exc
    return image
