"""astrbot_plugin_openai_oauth — ChatGPT 订阅 (Codex OAuth) provider.

注册一个 `openai_codex` provider：登录 ChatGPT 账号后，AI 调用走账号订阅额度。
个人自用场景使用。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator

from astrbot import logger
from astrbot.api import AstrBotConfig
from astrbot.api.star import Context, Star, register
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.register import register_provider_adapter
from astrbot.core.provider.sources.openai_responses_source import (
    ProviderOpenAIResponses,
)
from astrbot.core.utils.network_utils import create_proxy_client

from .oauth import (
    CODEX_BASE,
    CODEX_FALLBACK_MODELS,
    CODEX_MODELS_URL,
    DEFAULT_ORIGINATOR,
    DEFAULT_USER_AGENT,
    dump_credentials,
    extract_model_ids,
    load_credentials,
    refresh_access_token,
)

_REFRESH_SKEW_SECONDS = 120


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
        "originator": DEFAULT_ORIGINATOR,
        "user_agent": DEFAULT_USER_AGENT,
    },
)
class ProviderOpenAICodex(ProviderOpenAIResponses):
    """ChatGPT subscription provider backed by the Codex OAuth flow.

    The key field holds a credential JSON blob:
    ``{"access_token", "refresh_token", "expires", "account_id"}``
    """

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        raw_key = provider_config.get("key")
        self.creds = load_credentials(raw_key)
        if not self.creds and raw_key:
            # 允许直接粘贴裸 access_token（缺少 account_id 时模型列表等接口不可用）
            self.creds = {"access_token": str(raw_key)}
        self._originator = str(provider_config.get("originator", DEFAULT_ORIGINATOR))
        self._user_agent = str(provider_config.get("user_agent", DEFAULT_USER_AGENT))
        provider_config["api_base"] = CODEX_BASE

        if not isinstance(provider_config.get("custom_headers"), dict):
            provider_config["custom_headers"] = {}
        account_id = self.creds.get("account_id", "")
        if account_id:
            provider_config["custom_headers"]["chatgpt-account-id"] = account_id
        provider_config["custom_headers"].setdefault("originator", self._originator)
        provider_config["custom_headers"].setdefault(
            "OpenAI-Beta", "responses=experimental"
        )

        super().__init__(provider_config, provider_settings)
        # 基类用原始 key 值构建了 client，这里用解析出的 access_token 修正。
        self._sync_client_key()
        self._refresh_lock = asyncio.Lock()
        self.set_model(provider_config.get("model", "gpt-5.4-mini"))

    def _sync_client_key(self) -> None:
        token = self.creds.get("access_token", "")
        self.api_keys = [token]
        self.chosen_api_key = token
        self.client.api_key = token

    def get_keys(self) -> list[str]:
        return [self.creds.get("access_token", "")]

    def get_current_key(self) -> str:
        return self.creds.get("access_token", "")

    def set_key(self, key: str) -> None:
        creds = load_credentials(key)
        if "access_token" not in creds and key:
            creds = {"access_token": key}
        self.creds = creds
        # AsyncOpenAI 构造时持有同一个 custom_headers dict，这里就地更新
        # chatgpt-account-id，client.default_headers 下次访问时即生效。
        headers = self.provider_config.get("custom_headers")
        if isinstance(headers, dict):
            account_id = creds.get("account_id", "")
            if account_id:
                headers["chatgpt-account-id"] = account_id
            else:
                headers.pop("chatgpt-account-id", None)
        self._sync_client_key()

    async def get_models(self) -> list[str]:
        token = self.creds.get("access_token", "")
        if not token:
            return list(CODEX_FALLBACK_MODELS)
        headers = {
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": self.creds.get("account_id", ""),
            "originator": self._originator,
            "User-Agent": self._user_agent,
            "accept": "application/json",
        }
        try:
            client = create_proxy_client(
                "OpenAI Codex",
                self.provider_config.get("proxy", ""),
            )
            async with client:
                resp = await client.get(
                    f"{CODEX_MODELS_URL}?client_version=1.0.0",
                    headers=headers,
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
            models = extract_model_ids(data)
            if models:
                return models
            logger.warning("OpenAI Codex /models returned no ids; using fallback.")
        except Exception as e:  # noqa: BLE001 - network/catalog failure falls back to the offline list
            logger.error(f"Failed to fetch OpenAI Codex model list: {e}")
        return list(CODEX_FALLBACK_MODELS)

    async def _ensure_fresh_token(self) -> None:
        if not self.creds.get("refresh_token"):
            return
        if self.creds.get("expires", 0) > time.time() + _REFRESH_SKEW_SECONDS:
            return
        async with self._refresh_lock:
            # 等锁期间可能已被刷新，双重检查。
            if self.creds.get("expires", 0) > time.time() + _REFRESH_SKEW_SECONDS:
                return
            try:
                self.creds = await refresh_access_token(
                    self.creds,
                    self.provider_config.get("proxy", ""),
                )
                self.provider_config["key"] = dump_credentials(self.creds)
                self._sync_client_key()
                logger.info("OpenAI Codex token refreshed.")
            except Exception as e:  # noqa: BLE001 - a failed refresh must not break the request
                logger.error(f"OpenAI Codex token refresh failed: {e}")

    async def text_chat(self, *args, **kwargs) -> LLMResponse:
        await self._ensure_fresh_token()
        return await super().text_chat(*args, **kwargs)

    async def text_chat_stream(
        self, *args, **kwargs
    ) -> AsyncGenerator[LLMResponse, None]:
        await self._ensure_fresh_token()
        async for item in super().text_chat_stream(*args, **kwargs):
            yield item
