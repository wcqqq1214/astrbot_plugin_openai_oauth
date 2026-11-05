"""Prepare inline images for Codex requests."""

from __future__ import annotations

import asyncio
import json
from base64 import b64decode, b64encode
from collections.abc import Iterator
from io import BytesIO

from astrbot import logger
from astrbot.core.utils.media_utils import resolve_media_ref_to_base64_data
from PIL import Image, ImageOps

_IMAGE_MIME_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
_IMAGE_ID_PREFIX = "astrbot-openai-oauth:image:"


def image_metadata(image_id: object) -> dict | None:
    if not isinstance(image_id, str):
        return None
    if not image_id.startswith(_IMAGE_ID_PREFIX):
        return None
    try:
        metadata = json.loads(image_id.removeprefix(_IMAGE_ID_PREFIX))
    except (ValueError, TypeError):
        return None
    return metadata if isinstance(metadata, dict) else None


def with_image_metadata(image: dict, **values) -> dict:
    metadata = image_metadata(image.get("id")) or {"id": image.get("id")}
    metadata.update(values)
    return {**image, "id": _IMAGE_ID_PREFIX + json.dumps(metadata)}


def preserve_original_detail(image: dict) -> dict:
    """Carry original detail through AstrBot's typed messages and saved history."""
    if image.get("detail") != "original":
        return image
    return with_image_metadata(image, detail="original")


def _long_edge_limit(detail: str | None) -> int:
    return 6000 if detail == "original" else 2048


async def prepare_original_ref(ref: str, detail: str | None) -> str | None:
    """Prepare a recovered attachment before AstrBot captures it into history."""
    image = await resolve_media_ref_to_base64_data(ref, media_type="image")
    if image is None or image.mime_type not in _IMAGE_MIME_TYPES.values():
        return None
    return await asyncio.to_thread(
        _resize_data_url, image.to_data_url(), _long_edge_limit(detail)
    )


def _image_parts(items: list[dict]) -> Iterator[dict]:
    for item in items:
        content = item.get("content")
        if item.get("type") == "message" and isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "input_image":
                    yield part


def restore_original_detail(messages: list[dict], items: list[dict]) -> None:
    """Restore Codex's extra detail level after AstrBot's ordered conversion."""
    chat_images = (
        image
        for message in messages
        if isinstance(message, dict)
        and message.get("role") in {"user", "system", "developer"}
        and isinstance(message.get("content"), list)
        for part in message["content"]
        if isinstance(part, dict)
        and part.get("type") == "image_url"
        and isinstance(image := part.get("image_url"), dict)
        and image.get("url")
    )
    for image, part in zip(chat_images, _image_parts(items)):
        if image.get("detail") == "original" and image["url"] == part.get("image_url"):
            part["detail"] = "original"


def _resize_data_url(url: str, limit: int) -> str | None:
    header, _, encoded = url.partition(",")
    if not header.lower().endswith(";base64") or not encoded:
        return url
    try:
        with Image.open(BytesIO(b64decode(encoded, validate=True))) as image:
            source_format = image.format
            if source_format not in _IMAGE_MIME_TYPES or max(image.size) <= limit:
                return url

            ImageOps.exif_transpose(image, in_place=True)
            output_format = "PNG" if source_format == "GIF" else source_format
            high_bit_grayscale = source_format == "PNG" and image.mode == "I;16"
            transparent = "transparency" in image.info
            if not high_bit_grayscale and (image.mode in {"1", "P"} or transparent):
                image = image.convert("RGBA")
            # A 16-bit PNG color key must keep its exact sample value.
            resample = (
                Image.Resampling.NEAREST
                if high_bit_grayscale and transparent
                else Image.Resampling.LANCZOS
            )
            image.thumbnail(
                (limit, limit),
                resample,
                reducing_gap=None if high_bit_grayscale else 2.0,
            )

            options = {}
            if output_format == "JPEG":
                options["quality"] = 85
            elif output_format == "WEBP":
                options["lossless"] = True
            if icc_profile := image.info.get("icc_profile"):
                options["icc_profile"] = icc_profile
            with BytesIO() as output:
                image.save(output, format=output_format, **options)
                encoded = b64encode(output.getbuffer()).decode("ascii")
            return f"data:{_IMAGE_MIME_TYPES[output_format]};base64,{encoded}"
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        logger.warning("OpenAI Codex could not resize an inline image.")
        return None


def _resize_parts(parts: list[dict]) -> None:
    resized: dict[tuple[str, int], str] = {}
    for part in parts:
        url = part["image_url"]
        limit = _long_edge_limit(part.get("detail"))
        key = (url, limit)
        if key not in resized:
            resized[key] = _resize_data_url(url, limit) or url
        part["image_url"] = resized[key]


async def resize_input_images(items: list[dict]) -> None:
    parts = [
        part
        for part in _image_parts(items)
        if isinstance(url := part.get("image_url"), str)
        and url.startswith("data:image/")
    ]
    if parts:
        await asyncio.to_thread(_resize_parts, parts)
