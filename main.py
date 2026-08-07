"""astrbot_plugin_openai_oauth — ChatGPT 订阅 (Codex OAuth) provider.

注册一个 `openai_subscription_oauth` provider：登录 ChatGPT 账号后，AI 调用
走账号订阅额度。个人自用场景使用。
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncGenerator
from typing import Any

from astrbot import logger
from astrbot.api import AstrBotConfig
from astrbot.api.star import Context, Star, register
from astrbot.api.web import json_response, request
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.register import (
    provider_cls_map,
    register_provider_adapter,
)
from astrbot.core.provider.sources.openai_responses_source import (
    ProviderOpenAIResponses,
)
from astrbot.core.utils.network_utils import create_proxy_client
from starlette.responses import HTMLResponse

from .oauth import (
    CODEX_BASE,
    CODEX_DEVICE_VERIFY_URL,
    CODEX_FALLBACK_MODELS,
    CODEX_MODELS_URL,
    DEFAULT_ORIGINATOR,
    DEFAULT_USER_AGENT,
    DeviceAuthError,
    DeviceAuthTimeout,
    build_credentials,
    dump_credentials,
    exchange_authorization_code,
    extract_model_ids,
    load_credentials,
    poll_device_authorization,
    refresh_access_token,
    request_device_user_code,
)

_REFRESH_SKEW_SECONDS = 120

# WebUI 模型配置里展示的 provider 类型名。
_PROVIDER_TYPE = "openai_subscription_oauth"

# 由 OpenAI_OAuth_Plugin 注入，供 provider 把刷新的凭据写回 AstrBot 配置。
_config_mgr: Any = None


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
        global _config_mgr
        super().__init__(context)
        _config_mgr = context.astrbot_config_mgr
        self.config = config if config is not None else AstrBotConfig()
        # 设备登录的后端接口与页面：/api/plugins/extensions/<route>
        self.context.register_web_api(
            "/astrbot_plugin_openai_oauth/device/start",
            _handle_device_start,
            ["POST"],
            "开始 Codex 设备登录",
        )
        self.context.register_web_api(
            "/astrbot_plugin_openai_oauth/device/poll",
            _handle_device_poll,
            ["POST"],
            "查询 Codex 设备登录状态",
        )
        self.context.register_web_api(
            "/astrbot_plugin_openai_oauth/login",
            _handle_login_page,
            ["GET"],
            "Codex 设备登录页面",
        )


def _register_provider_adapter_if_absent(cls: type) -> type:
    """仅在类型未注册时才注册 provider 适配器。

    AstrBot 的 provider 注册不幂等：插件热重载（astrbot run --reload）会清掉
    sys.modules 里的插件模块，却不清 provider_cls_map；重导入会再次执行注册并
    抛“已经注册”错误。这里跳过已注册类型，保证 reload 后插件仍能正常加载。
    """
    if _PROVIDER_TYPE not in provider_cls_map:
        return register_provider_adapter(
            _PROVIDER_TYPE,
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
        )(cls)
    return cls


@_register_provider_adapter_if_absent
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
                await self._persist_key()
                logger.info("OpenAI Codex token refreshed.")
            except Exception as e:  # noqa: BLE001 - a failed refresh must not break the request
                logger.error(f"OpenAI Codex token refresh failed: {e}")

    async def _persist_key(self) -> None:
        """把当前凭据写回 AstrBot 配置里的 provider key，重启后免重新登录。"""
        cfg_mgr = _config_mgr
        provider_id = self.provider_config.get("id")
        if cfg_mgr is None or not provider_id:
            return
        try:
            conf = cfg_mgr.default_conf
            for provider in conf["provider"]:
                if provider.get("id") == provider_id:
                    provider["key"] = dump_credentials(self.creds)
                    await conf.save_config_async()
                    return
            logger.warning(
                f"OpenAI Codex provider {provider_id} not found in config; "
                "refreshed token not persisted."
            )
        except Exception as e:  # noqa: BLE001 - a failed persist must not break the request
            logger.error(f"OpenAI Codex failed to persist refreshed token: {e}")

    async def text_chat(self, *args, **kwargs) -> LLMResponse:
        await self._ensure_fresh_token()
        # Codex 后端只接受 stream=true，非流式路径也改走流式并聚合出完整响应。
        final_response = None
        async for chunk in super().text_chat_stream(*args, **kwargs):
            if not chunk.is_chunk:
                final_response = chunk
        if final_response is None:
            raise RuntimeError("OpenAI Codex 未返回完整响应。")
        return final_response

    async def text_chat_stream(
        self, *args, **kwargs
    ) -> AsyncGenerator[LLMResponse, None]:
        await self._ensure_fresh_token()
        async for item in super().text_chat_stream(*args, **kwargs):
            yield item


# ---- 设备登录 Web API（个人自用，进程内存即可） ----

# session_id -> {status, device_auth_id, user_code, interval, creds, error, task}
_login_sessions: dict[str, dict] = {}


async def _handle_device_start() -> Any:
    body = await request.json(default={}) or {}
    proxy = str(body.get("proxy", "") or "")
    session_id = secrets.token_hex(8)
    try:
        device_auth_id, user_code, interval = await request_device_user_code(proxy)
    except DeviceAuthError as exc:
        return json_response({"status": "error", "message": str(exc)})
    session = {
        "status": "pending",
        "device_auth_id": device_auth_id,
        "user_code": user_code,
        "interval": interval,
        "creds": None,
        "error": None,
    }
    _login_sessions[session_id] = session
    session["task"] = asyncio.create_task(_run_device_login(session_id, proxy))
    return json_response(
        {
            "status": "pending",
            "session_id": session_id,
            "verify_url": CODEX_DEVICE_VERIFY_URL,
            "user_code": user_code,
            "interval": interval,
        }
    )


async def _run_device_login(session_id: str, proxy: str) -> None:
    session = _login_sessions.get(session_id)
    if session is None:
        return
    try:
        authorization_code, code_verifier = await poll_device_authorization(
            session["device_auth_id"],
            session["user_code"],
            session["interval"],
            proxy,
        )
        tokens = await exchange_authorization_code(
            authorization_code, code_verifier, proxy
        )
        session["creds"] = build_credentials(
            tokens["access_token"],
            tokens.get("refresh_token", ""),
            tokens.get("expires_in", 3600),
        )
        session["status"] = "success"
        logger.info("OpenAI Codex 设备登录成功。")
    except DeviceAuthTimeout as exc:
        session["status"] = "timeout"
        session["error"] = str(exc)
    except DeviceAuthError as exc:
        session["status"] = "error"
        session["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - 把任何意外失败透传到页面
        session["status"] = "error"
        session["error"] = f"登录失败：{exc}"
        logger.exception("OpenAI Codex 设备登录失败。")


async def _handle_device_poll() -> Any:
    body = await request.json(default={}) or {}
    session_id = str(body.get("session_id", "") or "")
    session = _login_sessions.get(session_id)
    if session is None:
        return json_response({"status": "error", "message": "登录会话不存在或已过期"})
    return json_response(
        {
            "status": session["status"],
            "creds": session.get("creds"),
            "error": session.get("error"),
        }
    )


async def _handle_login_page() -> HTMLResponse:
    return HTMLResponse(_LOGIN_PAGE_HTML)


_LOGIN_PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenAI 订阅登录 (Codex)</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 620px; margin: 40px auto; padding: 0 16px; line-height: 1.6; }
  h1 { font-size: 20px; }
  button { font-size: 14px; padding: 8px 16px; border: none; border-radius: 8px; background: #10a37f; color: #fff; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  code, textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  #steps { margin-top: 16px; }
  #steps p { margin: 8px 0; }
  .url { color: #10a37f; }
  .code { font-size: 18px; font-weight: 600; background: #f0f0f0; padding: 2px 8px; border-radius: 6px; }
  textarea { width: 100%; height: 130px; box-sizing: border-box; font-size: 12px; margin: 8px 0; }
  #status { margin-top: 12px; color: #666; }
  #error { margin-top: 12px; color: #c00; white-space: pre-wrap; }
  .ok { color: #0a7a3d; }
</style>
</head>
<body>
  <h1>OpenAI 订阅登录 (Codex OAuth)</h1>
  <p>用你的 ChatGPT 账号授权，生成 provider 的凭据。</p>
  <button id="start">开始登录</button>
  <div id="steps" hidden>
    <p>1. 打开链接：<a id="url" class="url" target="_blank" rel="noopener"></a></p>
    <p>2. 输入设备码：<span class="code" id="code"></span></p>
  </div>
  <div id="status"></div>
  <div id="result" hidden>
    <p class="ok">登录成功！复制下方凭据，粘贴到模型配置中该 provider 的 <code>key</code> 字段：</p>
    <textarea id="creds" readonly></textarea>
    <button id="copy">复制凭据</button>
  </div>
  <div id="error" hidden></div>
  <script>
    const BASE = "/api/plugins/extensions/astrbot_plugin_openai_oauth";
    const $ = (id) => document.getElementById(id);
    const startBtn = $("start");
    startBtn.addEventListener("click", async () => {
      startBtn.disabled = true;
      try {
        const resp = await fetch(BASE + "/device/start", { method: "POST" });
        const data = await resp.json();
        if (data.status === "error") { showError(data.message || "启动失败"); return; }
        $("steps").hidden = false;
        $("url").textContent = data.verify_url;
        $("url").href = data.verify_url;
        $("code").textContent = data.user_code;
        setStatus("等待授权：请在打开的页面完成登录……");
        poll(data.session_id, Math.max(2, Number(data.interval) || 5));
      } catch (e) { showError(String(e)); }
    });
    function poll(sessionId, interval) {
      const timer = setInterval(async () => {
        try {
          const resp = await fetch(BASE + "/device/poll", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
          });
          const data = await resp.json();
          if (data.status === "success") {
            clearInterval(timer);
            $("result").hidden = false;
            $("creds").value = JSON.stringify(data.creds, null, 2);
            setStatus("登录成功。");
          } else if (data.status === "error" || data.status === "timeout") {
            clearInterval(timer);
            showError(data.error || "登录失败");
          }
        } catch (e) { /* 瞬时错误继续轮询 */ }
      }, interval * 1000);
    }
    $("copy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText($("creds").value);
      } catch (e) {
        $("creds").select();
        document.execCommand("copy");
      }
      $("copy").textContent = "已复制";
    });
    function setStatus(text) {
      $("status").textContent = text;
      $("error").hidden = true;
    }
    function showError(text) {
      $("status").textContent = "";
      $("error").hidden = false;
      $("error").textContent = text;
      startBtn.disabled = false;
    }
  </script>
</body>
</html>
"""
