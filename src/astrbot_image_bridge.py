"""Keep provider-specific image variants across AstrBot fallback and reloads."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import aclosing
from copy import copy
from functools import wraps
from weakref import WeakKeyDictionary

from astrbot.core.agent.message import ImageURLPart
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.utils.media_utils import resolve_media_ref_to_base64_data

from .image_input import (
    image_metadata,
    prepare_original_ref,
    preserve_original_detail,
    with_image_metadata,
)

_STATE_ATTR = "_openai_subscribe_image_bridge_state"
_MONTAGE_STATUS = "; animation converted to a 3x3 frame montage]"
_MONTAGE_ADVICE = (
    "<system_notice>\n"
    "Images labeled as animation montages contain frames in reading order. "
    "Treat them as animations; do not mention the conversion or frame layout.\n"
    "</system_notice>"
)


def _preserve_history_details(message):
    if not isinstance(message, dict) or not isinstance(
        content := message.get("content"), list
    ):
        return message
    parts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            image = part.get("image_url")
            if isinstance(image, dict):
                part = {**part, "image_url": preserve_original_detail(image)}
        parts.append(part)
    return {**message, "content": parts}


def _preserve_request_details(request):
    preserved = copy(request)
    preserved.contexts = [
        _preserve_history_details(message) for message in request.contexts or []
    ]
    parts = []
    for part in request.extra_user_content_parts:
        if isinstance(part, dict) and part.get("type") == "image_url":
            image = part.get("image_url")
            if isinstance(image, dict):
                data = {**part, "image_url": preserve_original_detail(image)}
                part = ImageURLPart.model_validate(data)
                if data.get("_no_save"):
                    part.mark_as_temp()
        parts.append(part)
    preserved.extra_user_content_parts = parts
    if (
        preserved.contexts == request.contexts
        and parts == request.extra_user_content_parts
    ):
        return request
    return preserved


async def _capture_variants(request, message, originals):
    content = message.get("content")
    if not isinstance(content, list):
        return message
    refs = []
    for part in request.extra_user_content_parts:
        if isinstance(part, ImageURLPart):
            refs.append(part.image_url.url)
        elif isinstance(part, dict) and part.get("type") == "image_url":
            refs.append(part["image_url"]["url"])
    refs.extend(request.image_urls)
    # Assemble in the same visual order as ProviderRequest.assemble_context.
    captured = dict(message)
    captured["content"] = [dict(part) for part in content]
    image_parts = [
        part for part in captured["content"] if part.get("type") == "image_url"
    ]
    if len(refs) == len(image_parts):
        origins = [originals.get(ref) for ref in refs]
    else:
        # A source can disappear while assembling another image. Match surviving
        # images by their actual bytes instead of shifting positional metadata.
        by_url = defaultdict(deque)
        for ref in refs:
            resolved = await resolve_media_ref_to_base64_data(ref, media_type="image")
            if resolved is not None:
                by_url[resolved.to_data_url()].append(originals.get(ref))
        origins = []
        for part in image_parts:
            candidates = by_url.get(part["image_url"]["url"])
            origins.append(candidates.popleft() if candidates else None)
    prepared = {}
    for origin, part in zip(origins, image_parts):
        if origin is None:
            continue
        original, montage = origin
        image = part["image_url"]
        metadata = image_metadata(image.get("id")) or {}
        detail = metadata.get("detail", image.get("detail"))
        key = (original, detail)
        if key not in prepared:
            prepared[key] = await prepare_original_ref(original, detail)
        if url := prepared[key]:
            part["image_url"] = with_image_metadata(
                image, detail=detail, url=url, montage=original if montage else None
            )
    return captured


def shape_messages(messages, *, codex: bool):
    """Select image variants in a copy belonging to the current provider call."""
    shaped = []
    for message in messages:
        message = message.model_dump() if hasattr(message, "model_dump") else message
        if not isinstance(message, dict) or not isinstance(
            content := message.get("content"), list
        ):
            shaped.append(message)
            continue
        parts = []
        montages = set()
        for part in content:
            image = part.get("image_url") if isinstance(part, dict) else None
            metadata = (
                image_metadata(image.get("id")) if isinstance(image, dict) else None
            )
            if metadata is not None:
                image = {**image, "id": metadata.get("id")}
                if codex:
                    if url := metadata.get("url"):
                        image["url"] = url
                    if detail := metadata.get("detail"):
                        image["detail"] = detail
                    if montage := metadata.get("montage"):
                        montages.add(montage)
                part = {**part, "image_url": image}
            parts.append(part)
        if montages:
            suffixes = tuple(
                f": original path {ref}{_MONTAGE_STATUS}" for ref in montages
            )
            parts = [
                {**part, "text": part["text"].removesuffix(_MONTAGE_STATUS) + "]"}
                if part.get("type") == "text"
                and part.get("text", "").endswith(suffixes)
                else part
                for part in parts
            ]
            if not any(
                part.get("text", "").endswith(_MONTAGE_STATUS) for part in parts
            ):
                parts = [part for part in parts if part.get("text") != _MONTAGE_ADVICE]
        shaped.append({**message, "content": parts})
    return shaped


def install(provider_type: str):
    """Enable stable dispatchers without removing another plugin's wrappers."""
    from astrbot.core import astr_main_agent
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner

    from .image_generation import ToolInvocation, tool_invocation

    state = getattr(ToolLoopAgentRunner, _STATE_ATTR, None)
    first_install = state is None
    if first_install:
        state = {"active": False, "previews": WeakKeyDictionary()}
        setattr(ToolLoopAgentRunner, _STATE_ATTR, state)

    def patch(target, name, handler):
        original = getattr(target, name)
        if asyncio.iscoroutinefunction(original):

            @wraps(original)
            async def dispatch(*args, **kwargs):
                if state["active"] or handler in {"prepare", "compress"}:
                    return await state[handler](original, *args, **kwargs)
                return await original(*args, **kwargs)
        else:

            @wraps(original)
            def dispatch(*args, **kwargs):
                if state["active"] or handler == "sanitize":
                    return state[handler](original, *args, **kwargs)
                return original(*args, **kwargs)

        setattr(target, name, dispatch)

    if first_install:
        if hasattr(astr_main_agent, "_compress_image_for_provider"):
            patch(astr_main_agent, "_compress_image_for_provider", "compress")
        else:
            from astrbot.core.utils import image_input

            patch(image_input, "prepare_model_image", "prepare")
        patch(ToolLoopAgentRunner, "reset", "reset")
        patch(ProviderRequest, "assemble_context", "assemble")
        patch(ToolLoopAgentRunner, "_sanitize_contexts_for_provider", "sanitize")
    if not state.get("draw_patched"):
        patch(ToolLoopAgentRunner, "_handle_function_tools", "tool_scope")
        if hasattr(ToolLoopAgentRunner, "_resolve_tool_exec"):
            patch(ToolLoopAgentRunner, "_resolve_tool_exec", "tool_requery")
        state["draw_patched"] = True

    def remember(preview, original, montage=False):
        if preview != original and (task := asyncio.current_task()) is not None:
            state["previews"].setdefault(task, {})[preview] = (original, montage)

    async def prepare(original, *args, **kwargs):
        result = await original(*args, **kwargs)
        if result is not None:
            preview, montage, _, ref = result
            remember(preview, ref, montage)
        return result

    async def compress(original, ref, *args, **kwargs):
        preview = await original(ref, *args, **kwargs)
        remember(preview, ref)
        return preview

    async def reset(original, runner, provider, request, *args, **kwargs):
        return await original(
            runner, provider, _preserve_request_details(request), *args, **kwargs
        )

    async def assemble(original, request):
        message = await original(request)
        task = asyncio.current_task()
        originals = state["previews"].get(task, {}) if task is not None else {}
        return await _capture_variants(request, message, originals)

    def sanitize(original, runner, messages):
        return shape_messages(
            original(runner, messages),
            codex=state["active"]
            and runner.provider.provider_config.get("type") == provider_type,
        )

    async def tool_requery(original, runner, response, *args, **kwargs):
        result = await original(runner, response, *args, **kwargs)
        # The runner copies the new tool calls onto the original response.
        response._codex_image_account = getattr(result[0], "_codex_image_account", None)
        return result

    async def tool_scope(original, runner, request, response, *args, **kwargs):
        binding = getattr(response, "_codex_image_account", None)
        invocation = (
            ToolInvocation(binding, runner.run_context.tool_call_timeout)
            if binding is not None
            else None
        )
        async with aclosing(
            original(runner, request, response, *args, **kwargs)
        ) as stream:
            while True:
                token = tool_invocation.set(invocation)
                try:
                    item = await anext(stream)
                except StopAsyncIteration:
                    return
                finally:
                    tool_invocation.reset(token)
                yield item

    generation = object()
    state.update(
        active=True,
        generation=generation,
        prepare=prepare,
        compress=compress,
        reset=reset,
        assemble=assemble,
        sanitize=sanitize,
        tool_scope=tool_scope,
        tool_requery=tool_requery,
    )

    def remove():
        if state["generation"] is generation:
            state["active"] = False

    return remove
