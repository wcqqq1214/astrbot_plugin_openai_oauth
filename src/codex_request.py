"""Shape Responses requests the way Codex CLI sends them to the ChatGPT backend.

Following yetone/magpie's codex_request.go: the backend keeps no state, finds a
conversation's cached prompt by Codex's session headers, and rejects several
parameters that the public Responses API accepts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from astrbot import logger

# The ChatGPT backend rejects sampling knobs, output limits and explicit cache
# options that the public Responses API accepts. Codex never sends them.
_UNSUPPORTED_REQUEST_PARAMS = (
    "max_output_tokens",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "user",
    "safety_identifier",
    "prompt_cache_options",
)
# Codex's Fast mode sends "priority" and Ultrafast sends "ultrafast".
_SUPPORTED_SERVICE_TIERS = frozenset({"priority", "ultrafast"})
# Call IDs from other providers can exceed the backend's 64-character limit.
_CALL_ID_LIMIT = 64
_reported_unsupported_params: set[str] = set()


def bound_call_id(call_id: Any) -> Any:
    """Shorten an oversized call ID the same way on every request."""
    if not isinstance(call_id, str) or len(call_id) <= _CALL_ID_LIMIT:
        return call_id
    return hashlib.sha256(call_id.strip().encode()).hexdigest()


def drop_unsupported_params(*bodies: dict[str, Any]) -> None:
    dropped: set[str] = set()
    for body in bodies:
        for key in _UNSUPPORTED_REQUEST_PARAMS:
            if key in body:
                body.pop(key)
                dropped.add(key)
        tier = body.get("service_tier")
        if tier is not None and tier not in _SUPPORTED_SERVICE_TIERS:
            body.pop("service_tier")
            dropped.add("service_tier")
    new = dropped - _reported_unsupported_params
    if new:
        _reported_unsupported_params.update(new)
        logger.warning(
            "OpenAI Codex ignores request parameters it does not support: %s",
            ", ".join(sorted(new)),
        )


def shape_replayed_input(items: list[dict]) -> list[dict]:
    """Shape replayed history for a backend that stores nothing.

    Stored item IDs and message statuses refer to state the backend never kept,
    and a reasoning item can only be replayed with its encrypted content. The
    backend also rejects role "system" in input; "developer" carries the same
    meaning.
    """
    shaped: list[dict] = []
    for item in items:
        item_type = item.get("type")
        if item_type == "reasoning" and not item.get("encrypted_content"):
            continue
        item.pop("id", None)
        if item_type in {None, "message", "reasoning"}:
            item.pop("status", None)
        if "call_id" in item:
            item["call_id"] = bound_call_id(item["call_id"])
        if item_type in {None, "message"} and item.get("role") == "system":
            item["role"] = "developer"
        shaped.append(item)
    return shaped


def session_headers(cache_key: Any) -> dict[str, str]:
    """Name the conversation in the headers the backend's prompt cache follows."""
    if not isinstance(cache_key, str) or not cache_key:
        return {}
    return {"session-id": cache_key, "thread-id": cache_key}


def prompt_cache_key(session_id: Any, payloads: dict[str, Any]) -> str | None:
    """Name the conversation so the backend reuses its cached prompt prefix.

    Codex sends its thread ID. An AstrBot session is the closest stable
    equivalent and survives context truncation; without one, the start of
    the conversation (instructions and input up to the first user message),
    which every later turn repeats, identifies it. Only a hash is sent.
    """
    digest = hashlib.sha256()
    if isinstance(session_id, str) and session_id:
        digest.update(b"astrbot-session\0")
        digest.update(session_id.encode())
        digest.update(b"\0")
        digest.update(str(payloads.get("model", "")).encode())
    else:
        digest.update(str(payloads.get("instructions", "")).encode())
        found_user = False
        for item in payloads.get("input") or []:
            digest.update(json.dumps(item, sort_keys=True, ensure_ascii=False).encode())
            if isinstance(item, dict) and item.get("role") == "user":
                found_user = True
                break
        if not found_user:
            return None
    value = digest.hexdigest()
    return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:32]}"


def request_reasoning_state(
    payloads: dict[str, Any], extra_body: dict[str, Any]
) -> None:
    """Ask for reasoning the way Codex does, unless reasoning is off.

    With ``store`` disabled, the encrypted reasoning content is the only
    way to carry reasoning into the next turn or tool call. A summary lets
    the reasoning stream instead of arriving silently.
    """
    reasoning = extra_body.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning = payloads.pop("reasoning", None)
        reasoning = dict(reasoning) if isinstance(reasoning, dict) else {}
    if reasoning.get("effort") == "none":
        if reasoning:
            extra_body["reasoning"] = reasoning
        return
    reasoning.setdefault("summary", "auto")
    extra_body["reasoning"] = reasoning
    include = extra_body.get("include", payloads.pop("include", None))
    include = list(include) if isinstance(include, (list, tuple)) else []
    if "reasoning.encrypted_content" not in include:
        include.append("reasoning.encrypted_content")
    extra_body["include"] = include
