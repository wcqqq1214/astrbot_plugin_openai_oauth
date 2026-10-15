"""AstrBot entry point for the OpenAI subscription plugin."""

from __future__ import annotations

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .src import effort, login, runtime, usage, web_api
from .src.provider import ProviderOpenAICodex

__all__ = ["OpenAI_OAuth_Plugin", "ProviderOpenAICodex"]


@register(
    "astrbot_plugin_openai_oauth",
    "wcqqq1214",
    "ChatGPT 订阅 (Codex OAuth) provider 插件",
    "2.1.0",
)
class OpenAI_OAuth_Plugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context)
        self.config = config if config is not None else AstrBotConfig()
        runtime.configure(context, self.config)
        web_api.register_routes(self.context)

    async def initialize(self) -> None:
        """Expose the default model source without requiring a device login."""
        await runtime._get_credential_coordinator().ensure_default_source()

    @filter.command("usage")
    async def usage(self, event: AstrMessageEvent) -> None:
        """Show the remaining subscription quota for the selected provider."""
        await usage.handle_usage(self.context, event)

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
    async def openai_login(self, event: AstrMessageEvent) -> None:
        """Start administrator-only private-chat device login."""
        await login.handle_login(event)

    async def terminate(self) -> None:
        """Cancel outstanding device-login work during plugin unload."""
        await login.terminate()
