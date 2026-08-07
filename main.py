"""astrbot_plugin_openai_oauth — ChatGPT 订阅 (Codex OAuth) provider.

注册一个 `openai_codex` provider：登录 ChatGPT 账号后，AI 调用走账号订阅额度。
个人自用场景使用。当前为最小骨架，仅验证插件注册 provider 的链路。
"""

from astrbot.api import AstrBotConfig
from astrbot.api.star import Context, Star, register
from astrbot.core.provider.register import register_provider_adapter
from astrbot.core.provider.sources.openai_responses_source import (
    ProviderOpenAIResponses,
)


@register(
    "astrbot_plugin_openai_oauth",
    "wcqqq1214",
    "ChatGPT 订阅 (Codex OAuth) provider 插件",
    "0.1.0",
)
class OpenAI_OAuth_Plugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context)
        self.config = config if config is not None else AstrBotConfig()


@register_provider_adapter(
    "openai_codex",
    "OpenAI 订阅登录 (Codex OAuth) Provider",
    provider_display_name="OpenAI 订阅 (ChatGPT 登录)",
    default_config_tmpl={
        # key 存放凭据 JSON：{access_token, refresh_token, expires, account_id}
        "key": "",
        "model": "gpt-5.4-mini",
        "proxy": "",
    },
)
class ProviderOpenAICodex(ProviderOpenAIResponses):
    """占位实现，仅验证注册链路。登录/刷新/模型列表在下一步实现。"""

    CODEX_BASE = "https://chatgpt.com/backend-api/codex"
    CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
