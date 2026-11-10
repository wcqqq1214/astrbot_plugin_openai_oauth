"""AstrBot entry point for the OpenAI subscription plugin."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import copy

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import Image
from astrbot.core.star.filter.command import GreedyStr

from .src import effort, image_generation, login, messages, runtime, usage, web_api
from .src.credential_store import (
    CredentialCooldownError,
    CredentialError,
    ReauthenticationRequiredError,
)
from .src.provider import ProviderOpenAICodex

__all__ = ["OpenAI_OAuth_Plugin", "ProviderOpenAICodex"]


@register(
    "astrbot_plugin_openai_oauth",
    "wcqqq1214",
    "ChatGPT 订阅 (Codex OAuth) provider 插件",
    "2.3.0",
)
class OpenAI_OAuth_Plugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context)
        self.config = config if config is not None else AstrBotConfig()
        self._image_accounts: OrderedDict[
            tuple[str, str | None], image_generation.ChatAccount
        ] = OrderedDict()
        runtime.configure(context, self.config)
        web_api.register_routes(self.context)

    async def initialize(self) -> None:
        """Expose the default model source without requiring a device login."""
        await runtime.initialize(self.context)

    @filter.command("usage")
    async def usage(self, event: AstrMessageEvent) -> None:
        """Show the remaining subscription quota for the selected provider."""
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
        if not self.config.get("image_enabled", False) and request.func_tool:
            request.func_tool = copy(request.func_tool)
            request.func_tool.remove_tool(image_generation.TOOL_NAME)

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

    @filter.command("draw")
    async def draw(self, event: AstrMessageEvent, prompt: GreedyStr):
        """Generate an image using this conversation's last successful Codex chat."""
        event.should_call_llm(False)
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
        """Generate and send an image when the user asks for one.

        Args:
            prompt(string): A description of the image to generate.
        """
        invocation = image_generation.tool_invocation.get()
        error = await self._send_image(
            event,
            invocation.account if invocation is not None else None,
            prompt,
            runner_timeout=invocation.runner_timeout
            if invocation is not None
            else None,
        )
        return error or messages.text("image.sent")

    async def _send_image(
        self,
        event: AstrMessageEvent,
        account: image_generation.ChatAccount | None,
        prompt: str,
        *,
        runner_timeout: float | None = None,
    ) -> str | None:
        if not self.config.get("image_enabled", False):
            return messages.text("image.disabled")
        if not isinstance(prompt, str) or not prompt.strip():
            return messages.text("image.prompt")
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
                image = await image_generation.generate(
                    provider, account, prompt, self.config.get("image_size", "auto")
                )
                await event.send(MessageChain(chain=[Image.fromBytes(image)]))
        except TimeoutError:
            return messages.text("image.timeout")
        except image_generation.ImageError as exc:
            return messages.text(str(exc))
        except CredentialCooldownError:
            return messages.text("image.limit")
        except ReauthenticationRequiredError:
            return messages.text("usage.reauth_required")
        except CredentialError:
            return messages.text("image.account_changed")
        except Exception as exc:  # noqa: BLE001 - do not disclose upstream or adapter details
            logger.warning(
                "Codex image generation or delivery failed: %s", type(exc).__name__
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
        await effort.handle_effort(self.context, event, value)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("openai_login")
    async def openai_login(
        self,
        event: AstrMessageEvent,
        action: str | None = None,
    ) -> None:
        """Start, or with "cancel" stop, an administrator private-chat login."""
        await login.handle_login(event, action)

    async def terminate(self) -> None:
        """Cancel outstanding device-login work during plugin unload."""
        await login.terminate()
        runtime.terminate()
