"""Local Claude subscription provider using the genuine Claude Code binary."""

from __future__ import annotations

import asyncio
import math
import weakref
from contextlib import aclosing
from copy import copy, deepcopy
from pathlib import Path
from typing import Any

from astrbot.core.provider.register import provider_cls_map, register_provider_adapter
from astrbot.core.provider.sources.anthropic_source import ProviderAnthropic
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .claude_bridge import ClaudeBridge
from .claude_sessions import digest
from .local_claude import (
    CLAUDE_MODE,
    CLAUDE_PROVIDER_TYPE,
    ClaudeError,
    LocalClaude,
    default_claude_source,
)

_options: dict[str, Any] = {}
_instances: weakref.WeakSet = weakref.WeakSet()


def configure_claude(config: dict) -> None:
    _options.clear()
    _options.update(
        {k: config.get(k, "") for k in ("claude_command", "claude_config_dir")}
    )


def local_host(source: dict) -> LocalClaude:
    return LocalClaude(
        *(
            str(source.get(k) or _options.get(k) or "")
            for k in ("claude_command", "claude_config_dir")
        )
    )


async def account_view(source: dict) -> dict:
    try:
        status = await local_host(source).status()
    except ClaudeError:
        status = {"status": "unknown"}
    return {
        **status,
        "id": source["id"],
        "name": source.get("name", "Local Claude"),
        "credential_mode": CLAUDE_MODE,
        "credential_source": CLAUDE_MODE,
    }


async def ensure_source(registry: Any) -> None:
    async with registry.lock:
        sources = registry.sources()
        if any(s.get("type") == CLAUDE_PROVIDER_TYPE for s in sources):
            return
        source = default_claude_source()
        if any(s["id"] == source["id"] for s in sources):
            raise ClaudeError(
                "The Local Claude provider ID is already used by another source."
            )
        previous = deepcopy(sources)
        sources.append(source)
        await registry._save(previous)


async def close_claude() -> None:
    await asyncio.gather(*(p.terminate() for p in list(_instances)))


def register(cls: type) -> type:
    if CLAUDE_PROVIDER_TYPE in provider_cls_map:
        provider_cls_map[CLAUDE_PROVIDER_TYPE].cls_type = cls
        return cls
    template = default_claude_source()
    template.pop("id")
    template.pop("name")
    template["model"] = "sonnet"
    return register_provider_adapter(
        CLAUDE_PROVIDER_TYPE,
        "Local Claude Code subscription provider",
        provider_display_name="Claude Subscribe",
        default_config_tmpl=template,
    )(cls)


@register
class ProviderLocalClaude(ProviderAnthropic):
    """Reuse AstrBot's content conversion while keeping CLI auth and execution."""

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        config = deepcopy(provider_config)
        config["key"] = ""
        super().__init__(config, provider_settings, use_api_key=False)
        self.host = local_host(config)
        timeout = float(config.get("timeout") or 180)
        if not math.isfinite(timeout) or not 1 <= timeout <= 1800:
            raise ClaudeError("Claude timeout must be between 1 and 1800 seconds.")
        self.bridge = ClaudeBridge(
            self.host,
            Path(get_astrbot_plugin_data_path())
            / "astrbot_plugin_openai_oauth"
            / "claude"
            / digest(
                config.get("id")
                or [config.get("provider_source_id"), config.get("model")]
            )[:16],
            timeout,
        )
        self.set_model(config.get("model") or "sonnet")
        _instances.add(self)

    def get_current_key(self) -> str:
        return ""

    def get_keys(self) -> list[str]:
        return [""]

    def set_key(self, key: str) -> None:
        if key:
            raise ClaudeError(
                "Local Claude uses the host login; do not configure an API key."
            )

    async def get_models(self) -> list[str]:
        # Official CLI aliases track the models available to the signed-in plan.
        return ["sonnet", "opus", "haiku"]

    async def terminate(self) -> None:
        await self.bridge.close()

    def _request_worker(self, args, kwargs):
        # AstrBot may drive each anext/aclose in a different asyncio task.
        # Keep ownership on a request-local copy rather than in task context.
        worker = copy(self)
        worker._request_owner = kwargs.get("conversation_id") or kwargs.get(
            "session_id"
        )
        if worker._request_owner is None and len(args) > 1:
            worker._request_owner = args[1]
        worker._active_stream = None
        return worker

    async def text_chat(self, *args, **kwargs):
        worker = self._request_worker(args, kwargs)
        try:
            return await ProviderAnthropic.text_chat(worker, *args, **kwargs)
        finally:
            if worker._active_stream is not None:
                await worker._active_stream.aclose()

    async def text_chat_stream(self, *args, **kwargs):
        worker = self._request_worker(args, kwargs)
        try:
            async with aclosing(
                ProviderAnthropic.text_chat_stream(worker, *args, **kwargs)
            ) as responses:
                async for response in responses:
                    yield response
        finally:
            # Some framework versions do not close their inner query generator.
            if worker._active_stream is not None:
                await worker._active_stream.aclose()

    async def _query(self, payloads, tools, **kwargs):
        final = None
        async for response in self._query_stream(payloads, tools, **kwargs):
            if not response.is_chunk:
                final = response
        if final is None:
            raise ClaudeError("Claude Code returned no response.")
        return final

    def _query_stream(self, payloads, tools, *, conversation_id=None, **kwargs):
        responses = self._stream_responses(
            payloads, tools, conversation_id=conversation_id
        )
        # Hold the query itself so framework finalization cannot race our close.
        self._active_stream = responses
        return responses

    async def _stream_responses(self, payloads, tools, *, conversation_id=None):
        definitions = tools.get_func_desc_anthropic_style() if tools else []
        choice = payloads.get("tool_choice", "auto")
        if choice == "none":
            definitions = []
        elif choice != "auto":
            raise ClaudeError(
                "Local Claude currently supports automatic tool selection only."
            )
        if self.provider_config.get("custom_extra_body"):
            raise ClaudeError(
                "Local Claude does not support custom HTTP request bodies."
            )
        effort = (self.thinking_config or {}).get("effort", "")
        if effort not in {"", "low", "medium", "high", "xhigh", "max"}:
            raise ClaudeError("Unsupported Claude reasoning effort.")
        responses = self.bridge.stream(
            payloads,
            definitions,
            owner=conversation_id or getattr(self, "_request_owner", None),
            effort=effort,
        )
        async with aclosing(responses):
            async for response in responses:
                yield response
