"""AstrBot entry point for the OpenAI subscription plugin."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import copy
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import Image
from astrbot.core.star.filter.command import GreedyStr

from .src import (
    bot_citations,
    chatui_citations,
    effort,
    image_generation,
    login,
    messages,
    oauth,
    runtime,
    usage,
    web_api,
)
from .src.credential_store import (
    CredentialCooldownError,
    CredentialError,
    CredentialRefreshError,
    ReauthenticationRequiredError,
)
from .src.provider import ProviderOpenAICodex

__all__ = ["OpenAI_OAuth_Plugin", "ProviderOpenAICodex"]

MAX_IMAGE_PROMPT_LENGTH = 32_000


async def _resolve_reply_language(plugin_obj: Any, event: AstrMessageEvent) -> str:
    context = getattr(plugin_obj, "context", None) or runtime.get_context()
    return await messages.resolve_language(
        context, getattr(event, "unified_msg_origin", None)
    )


@register(
    "astrbot_plugin_openai_oauth",
    "wcqqq1214",
    "用 ChatGPT 订阅在 AstrBot 聊天，无需 API Key。",
    "2.8.0",
)
class OpenAI_OAuth_Plugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context)
        self.config = config if config is not None else AstrBotConfig()
        self._version_task: asyncio.Task[None] | None = None
        self._image_accounts: OrderedDict[
            tuple[str, str | None], image_generation.ChatAccount
        ] = OrderedDict()
        runtime.configure(context, self.config)
        web_api.register_routes(self.context)

    async def initialize(self) -> None:
        """Expose the default model source without requiring a device login."""
        await runtime.initialize(self.context)
        if self._version_task is None:
            self._version_task = asyncio.create_task(self._refresh_codex_version())

    async def _refresh_codex_version(self) -> None:
        while True:
            gateway = runtime.get_coordinator().providers.gateway() or {}
            await oauth.refresh_published_version(gateway.get("proxy") or None)
            await asyncio.sleep(6 * 60 * 60)

    @filter.command("usage")
    async def usage(self, event: AstrMessageEvent) -> None:
        """Show the remaining subscription quota for the selected provider."""
        reply_language = await _resolve_reply_language(self, event)
        with messages.use_language(reply_language):
            await usage.handle_usage(self.context, event)

    @filter.on_llm_request()
    async def prepare_image_tool(
        self, event: AstrMessageEvent, request: ProviderRequest
    ):
        event.set_extra(
            "_codex_image_conversation",
            (
                event.unified_msg_origin,
                request.conversation.cid if request.conversation else None,
            ),
        )
        if not request.func_tool:
            return
        request.func_tool = copy(request.func_tool)
        if not self.config.get("image_enabled", False):
            request.func_tool.remove_tool(image_generation.TOOL_NAME)
            request.func_tool.remove_tool(image_generation.EDIT_TOOL_NAME)
        elif any(isinstance(part, Image) for part in event.get_messages()):
            request.func_tool.remove_tool(image_generation.TOOL_NAME)
        elif chatui_citations.active_chat_run(event) is None:
            request.func_tool.remove_tool(image_generation.EDIT_TOOL_NAME)

    @filter.on_llm_response()
    async def remember_image_account(
        self, event: AstrMessageEvent, response: LLMResponse
    ):
        scope = event.get_extra("_codex_image_conversation")
        if scope is None:
            return
        self._image_accounts.pop(scope, None)
        account = getattr(response, "_codex_image_account", None)
        if account is not None and response.role != "err":
            self._image_accounts[scope] = account
            if len(self._image_accounts) > 1024:
                self._image_accounts.popitem(last=False)

    @filter.after_message_sent()
    async def send_bot_sources(self, event: AstrMessageEvent) -> None:
        await bot_citations.deliver_card(event, after_send=True)

    @filter.on_decorating_result()
    async def prepare_bot_sources(self, event: AstrMessageEvent) -> None:
        await bot_citations.deliver_card(event, after_send=False)

    @filter.command("draw")
    async def draw(self, event: AstrMessageEvent, prompt: GreedyStr):
        """Generate an image using this conversation's last successful Codex chat."""
        event.should_call_llm(False)
        reply_language = await _resolve_reply_language(self, event)
        with messages.use_language(reply_language):
            umo = event.unified_msg_origin
            cid = (
                await self.context.conversation_manager.get_curr_conversation_id(umo)
                if self.config.get("image_enabled", False)
                else None
            )
            error = await self._send_image(
                event, self._image_accounts.get((umo, cid)), prompt
            )
            if error:
                await event.send(MessageChain().message(error))

    @filter.llm_tool(name=image_generation.TOOL_NAME)
    async def codex_generate_image(self, event: AstrMessageEvent, prompt: str) -> str:
        """Generate and send a new image when the user asks for one from text.

        For edits to an existing image, use codex_edit_image when available.
        If the source is unavailable, ask the user to attach it.

        Args:
            prompt(string): Describe the image, including any requested orientation and composition.
        """
        if error := event.get_extra("_codex_image_edit_error"):
            return error
        return await self._run_image_tool(event, prompt, edit=False)

    @filter.llm_tool(name=image_generation.EDIT_TOOL_NAME)
    async def codex_edit_image(self, event: AstrMessageEvent, prompt: str) -> str:
        """Edit an image only when the user asks to change it.

        Use the current attachment first. In ChatUI, a follow-up such as
        "keep the composition and change the background to daytime" edits
        the most recent image sent by the assistant in this chat, even if
        text-only replies followed it.
        Answer questions about the image directly without calling this tool.
        Use codex_generate_image for a new image. If editing fails, report the error.

        Args:
            prompt(string): Describe the requested changes and what to preserve. The plugin supplies the attachment.
        """
        return await self._run_image_tool(event, prompt, edit=True)

    async def _run_image_tool(
        self, event: AstrMessageEvent, prompt: str, *, edit: bool
    ) -> str:
        reply_language = await _resolve_reply_language(self, event)
        with messages.use_language(reply_language):
            invocation = image_generation.tool_invocation.get()
            error = await self._send_image(
                event,
                invocation.account if invocation is not None else None,
                prompt,
                edit=edit,
                runner_timeout=invocation.runner_timeout
                if invocation is not None
                else None,
            )
            if edit:
                event.set_extra("_codex_image_edit_error", error)
            return error or messages.text("image.sent")

    async def _send_image(
        self,
        event: AstrMessageEvent,
        account: image_generation.ChatAccount | None,
        prompt: str,
        *,
        edit: bool = False,
        runner_timeout: float | None = None,
    ) -> str | None:
        if not self.config.get("image_enabled", False):
            return messages.text("image.disabled")
        instructions = prompt.strip() if isinstance(prompt, str) else ""
        if not instructions or (edit and len(instructions) > MAX_IMAGE_PROMPT_LENGTH):
            return messages.text(
                "image.edit_prompt" if edit else "image.prompt",
                limit=MAX_IMAGE_PROMPT_LENGTH,
            )
        if account is None:
            return messages.text("image.no_account")
        allowed = str(self.config.get("image_account") or "").strip()
        if allowed and allowed != account.source_id:
            return messages.text("image.account_restricted")
        provider = self.context.get_provider_by_id(account.provider_id)
        if not isinstance(provider, ProviderOpenAICodex):
            return messages.text("image.no_account")
        try:
            timeout = image_generation.timeout_for_session(
                self.context.get_config(umo=event.unified_msg_origin),
                runner_timeout=runner_timeout,
            )
            async with asyncio.timeout(timeout):
                async with chatui_citations.image_generation_indicator(event) as card:
                    reference = (
                        await image_generation.read_edit_image(event) if edit else None
                    )
                    image = await image_generation.generate(
                        provider,
                        account,
                        instructions if edit else prompt,
                        reference_image=reference,
                    )
                    if card is None:
                        await event.send(MessageChain(chain=[Image.fromBytes(image)]))
                    else:
                        await card.deliver(image)
        except TimeoutError:
            return messages.text("image.timeout")
        except image_generation.ImageError as exc:
            return messages.text(str(exc))
        except CredentialCooldownError:
            return messages.text("image.usage_limit")
        except ReauthenticationRequiredError:
            return messages.text("usage.reauth_required")
        except CredentialRefreshError:
            return messages.text("image.failed")
        except CredentialError:
            return messages.text("image.account_changed")
        except Exception as exc:  # noqa: BLE001 - do not disclose upstream or adapter details
            logger.warning(
                "Codex image generation or delivery failed: %s",
                oauth.safe_error_summary(exc),
            )
            return messages.text("image.failed")
        return None

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("effort")
    async def effort(
        self,
        event: AstrMessageEvent,
        value: str | None = None,
    ) -> None:
        """View or override reasoning effort for the current session."""
        reply_language = await _resolve_reply_language(self, event)
        with messages.use_language(reply_language):
            await effort.handle_effort(self.context, event, value)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("openai_login")
    async def openai_login(
        self,
        event: AstrMessageEvent,
        action: str | None = None,
    ) -> None:
        """Start, or with "cancel" stop, an administrator private-chat login."""
        reply_language = await _resolve_reply_language(self, event)
        with messages.use_language(reply_language):
            await login.handle_login(event, action)

    async def terminate(self) -> None:
        """Stop background discovery and device login during plugin unload."""
        if self._version_task is not None:
            self._version_task.cancel()
            await asyncio.gather(self._version_task, return_exceptions=True)
            self._version_task = None
        await login.terminate()
        runtime.terminate()
