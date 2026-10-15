"""astrbot_plugin_openai_oauth — OpenAI 订阅登录插件。"""

from .claude_provider import ProviderLocalClaude
from .main import OpenAI_OAuth_Plugin, ProviderOpenAICodex

__all__ = ["OpenAI_OAuth_Plugin", "ProviderLocalClaude", "ProviderOpenAICodex"]
