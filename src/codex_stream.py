"""Assemble AstrBot responses from the Codex backend's Responses stream."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import astrbot.core.message.components as Comp
from astrbot.api.event import MessageChain
from astrbot.core.exceptions import EmptyModelOutputError
from astrbot.core.provider.entities import LLMResponse, TokenUsage


class CodexStreamMixin:
    """Stream parsing for a Responses provider talking to the Codex backend.

    Codex completes with an empty ``output`` list: text and reasoning arrive as
    deltas and the complete items in ``response.output_item.done`` events. The
    host class supplies ``_field`` and ``_parse_response``.
    """

    @staticmethod
    def _response_with_output(
        response: Any, response_id: str | None, items: dict[int, Any]
    ) -> dict[str, Any]:
        """Give a terminal response the output items its stream delivered.

        Codex completes with an empty ``output`` list; the items arrive in
        ``response.output_item.done`` events instead.
        """

        def field(name: str) -> Any:
            if isinstance(response, dict):
                return response.get(name)
            return getattr(response, name, None)

        return {
            "id": field("id") or response_id,
            "status": field("status"),
            "incomplete_details": field("incomplete_details"),
            "usage": field("usage"),
            "output": [items[index] for index in sorted(items)],
        }

    async def _consume_stream(
        self, stream: Any, tools: Any
    ) -> AsyncGenerator[LLMResponse, None]:
        """Keep partial response state scoped to a single stream attempt."""
        response_id: str | None = None
        text_parts: list[str] = []
        # Deltas are fragments of one text; a new item or summary part starts
        # a new segment, matching how complete responses separate them.
        reasoning_parts: list[str] = []
        reasoning_segment: tuple[Any, Any, Any] | None = None
        function_calls: list[dict] = []
        output_items: dict[int, Any] = {}

        async for event in stream:
            event_type = self._field(event, "type", "")
            event_response = self._field(event, "response")
            if event_response is not None:
                response_id = self._field(event_response, "id", response_id)

            if event_type == "error":
                code = self._field(event, "code", "stream_error")
                raise RuntimeError(
                    f"Responses API stream failed: {code}. response_id={response_id}"
                )

            if event_type in {"response.output_text.delta", "response.refusal.delta"}:
                delta = self._field(event, "delta", "")
                if delta:
                    text_parts.append(str(delta))
                    yield LLMResponse(
                        "assistant",
                        result_chain=MessageChain(chain=[Comp.Plain(str(delta))]),
                        is_chunk=True,
                        id=response_id,
                    )
                continue

            if event_type in {
                "response.reasoning_text.delta",
                "response.reasoning_summary_text.delta",
            }:
                delta = self._field(event, "delta", "")
                if delta:
                    segment = (
                        self._field(event, "item_id"),
                        self._field(event, "summary_index"),
                        self._field(event, "content_index"),
                    )
                    if not reasoning_parts or segment != reasoning_segment:
                        reasoning_parts.append("")
                        reasoning_segment = segment
                    reasoning_parts[-1] += str(delta)
                    yield LLMResponse(
                        "assistant",
                        reasoning_content=str(delta),
                        is_chunk=True,
                        id=response_id,
                    )
                continue

            if event_type == "response.output_item.done":
                item = self._field(event, "item")
                if item is not None:
                    index = self._field(event, "output_index")
                    if isinstance(index, bool) or not isinstance(index, int):
                        index = max(output_items, default=-1) + 1
                    output_items[index] = item
                continue

            if event_type == "response.output_item.added":
                item = self._field(event, "item")
                if self._field(item, "type") == "function_call":
                    arguments = self._field(item, "arguments", "")
                    if isinstance(arguments, dict):
                        arguments = json.dumps(arguments, ensure_ascii=False)
                    function_calls.append(
                        {
                            "item_id": self._field(item, "id"),
                            "call_id": str(self._field(item, "call_id", "") or ""),
                            "name": str(self._field(item, "name", "") or ""),
                            "arguments": str(arguments or ""),
                        }
                    )
                continue

            if event_type == "response.function_call_arguments.delta":
                # Parallel calls stream their arguments by item ID.
                item_id = self._field(event, "item_id")
                call = next(
                    (c for c in function_calls if item_id and c["item_id"] == item_id),
                    function_calls[-1] if function_calls else None,
                )
                if call is not None:
                    call["arguments"] += str(self._field(event, "delta", "") or "")
                continue

            if event_type in {
                "response.completed",
                "response.incomplete",
                "response.failed",
            }:
                if event_response is not None:
                    status = self._field(event_response, "status")
                    if status == "failed":
                        error = self._field(event_response, "error")
                        code = self._field(error, "code", "unknown_error")
                        raise RuntimeError(
                            f"Responses API request failed: {code}. "
                            f"response_id={response_id}"
                        )
                    if (
                        self._field(
                            self._field(event_response, "incomplete_details"),
                            "reason",
                        )
                        == "content_filter"
                    ):
                        raise RuntimeError(
                            "Responses API output was rejected by the provider "
                            f"content filter. response_id={response_id}"
                        )
                    if self._field(event_response, "output"):
                        yield await self._parse_response(event_response, tools)
                        return
                    if output_items:
                        try:
                            parsed = await self._parse_response(
                                self._response_with_output(
                                    event_response, response_id, output_items
                                ),
                                tools,
                            )
                        except EmptyModelOutputError:
                            parsed = None
                        if parsed is not None:
                            yield parsed
                            return
                final = self._assemble_streamed_response(
                    response_id,
                    text_parts,
                    reasoning_parts,
                    function_calls,
                    usage=self._extract_response_usage(event_response),
                )
                if final is not None:
                    yield final
                    return
                raise EmptyModelOutputError(
                    f"Responses stream returned no usable output. "
                    f"response_id={response_id}"
                )

        raise EmptyModelOutputError(
            f"Responses stream ended without a terminal event. response_id={response_id}"
        )

    def _assemble_streamed_response(
        self,
        response_id: str | None,
        text_parts: list[str],
        reasoning_parts: list[str],
        function_calls: list[dict],
        usage: TokenUsage | None = None,
    ) -> LLMResponse | None:
        """Build a final LLMResponse from streamed deltas like ``_parse_response``."""
        llm_response = LLMResponse("assistant", id=response_id)
        llm_response.usage = usage if usage is not None else TokenUsage()
        completion_text = "".join(text_parts)
        if completion_text:
            llm_response.result_chain = MessageChain().message(completion_text)
        if reasoning_parts:
            llm_response.reasoning_content = "\n".join(reasoning_parts)
        for call in function_calls:
            arguments = call["arguments"]
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed = {}
            elif arguments is None:
                parsed = {}
            else:
                parsed = arguments
            llm_response.tools_call_args.append(parsed)
            llm_response.tools_call_name.append(call["name"])
            llm_response.tools_call_ids.append(call["call_id"])
        if llm_response.tools_call_args:
            llm_response.role = "tool"
        has_text = bool((llm_response.completion_text or "").strip())
        has_reasoning = bool((llm_response.reasoning_content or "").strip())
        if not has_text and not has_reasoning and not llm_response.tools_call_args:
            return None
        return llm_response

    def _extract_response_usage(self, response: Any) -> TokenUsage | None:
        """Extract usage from a terminal Responses event.

        Codex may send the completed response with an empty ``output`` list while
        the actual text arrived through delta events. In that case the base
        Responses parser is intentionally skipped, so preserve the usage here.
        """
        usage = self._field(response, "usage")
        if usage is None:
            return None

        input_details = self._field(usage, "input_tokens_details")
        cached_tokens = self._field(input_details, "cached_tokens", 0) or 0
        input_tokens = self._field(usage, "input_tokens", 0) or 0
        output_tokens = self._field(usage, "output_tokens", 0) or 0
        return TokenUsage(
            input_other=max(input_tokens - cached_tokens, 0),
            input_cached=cached_tokens,
            output=output_tokens,
        )
