# 云端 Docker 部署下的 OpenAI OAuth 交互方案调研

日期：2026-08-09

## 结论

当前插件把 HTTPS 作为设备登录接口的强制前提，这不适合作为 AstrBot 插件市场的默认体验。OpenAI 的设备码流程要求插件服务器能够访问 OpenAI 的 HTTPS 端点，但不要求承载 AstrBot Dashboard 的用户入口必须使用 HTTPS，也不要求 OAuth 回调到 AstrBot。

面向普通用户的推荐设计如下：

1. 使用 AstrBot 原生 Plugin Page 作为主要登录入口，通过 Dashboard 提供的 bridge 调用插件扩展 API。
2. 设备码申请、轮询、令牌交换和持久化都继续在 AstrBot 服务端完成；浏览器只接收验证网址、一次性用户码、会话 ID 和状态。
3. 设备登录接口继续要求已认证的 Dashboard 管理员身份，并拒绝 API Key 身份；保留会话所有者绑定、过期时间、并发限额和一次性消费。
4. 不再按 `http`/`https` 协议拒绝请求。若 Dashboard 使用公网 HTTP，在页面中展示明确安全警告并推荐 HTTPS、VPN 或 SSH 隧道，但不阻断登录。
5. 增加仅管理员可用的私聊命令作为无 WebUI/旧浏览器环境下的兜底入口，例如 `/openai_login`。命令发出验证网址和用户码，服务端后台轮询并保存凭据。
6. 原来的独立 `/login` 页面不再作为推荐入口。浏览器直接导航不会自动携带 Dashboard 存在 `localStorage` 中的 Bearer JWT，而生产模式的安全 Cookie 在 HTTP 下也不会发送，因此会在进入插件处理器之前得到 `Missing API key`。

## 本地故障链路

在 AstrBot v4.27.2 的真实请求对象上，已认证管理员通过公网 HTTP 调用当前登录处理器时，会稳定得到：

```text
status=403 body='设备登录必须通过 HTTPS 访问'
```

实际用户还可能更早遇到另一层问题：AstrBot Dashboard 的前端 API 请求由 Axios 拦截器附加 `Authorization: Bearer ...`，但浏览器直接打开插件的 `/login` URL 不会附加该请求头。生产环境的认证 Cookie 默认带 `Secure`，在 HTTP 下同样不会发送，于是 AstrBot 扩展路由先返回：

```json
{"status":"error","message":"Missing API key"}
```

因此，仅删除 HTTPS 判断还不够；必须把主要入口迁移到 AstrBot 原生 Plugin Page bridge，或使用管理员聊天命令。

## OpenAI 官方边界

OpenAI 官方 Codex 认证文档把设备码登录作为远程、无头或 localhost 回调不可用环境的解决方案：用户在另一台有浏览器的设备打开验证页面并输入一次性代码。这个流程不需要业务服务器接收浏览器 OAuth 回调。

来源：[OpenAI Codex authentication](https://learn.chatgpt.com/docs/auth)

## OpenClaw 的处理方式

OpenClaw 同样遇到了远程服务器和回调不可达问题，并提供了多条设备码入口：

- CLI：`openclaw models auth login --provider openai --device-code`。
- 管理员私聊：`/login codex`，仅允许授权用户，并限制在私聊或 Web UI 会话中使用。
- Web UI 向导：通过已认证的宿主通信层启动 provider 的设备码流程。

设备码申请、轮询、令牌交换和凭据保存均由服务端完成。OpenClaw 的远程 Control UI 本身仍建议使用 HTTPS 或安全隧道，因为浏览器 WebCrypto 等宿主功能需要安全上下文；但它没有把 OAuth 的可用性只绑定在这一条 WebUI 路径上，终端和私聊设备码仍可完成登录。

来源：

- [OpenClaw OpenAI provider docs](https://github.com/openclaw/openclaw/blob/main/docs/providers/openai.md)
- [OpenClaw device-code implementation](https://github.com/openclaw/openclaw/blob/3aec297be03f77cc474059a2fbe92dea7da53109/extensions/openai/openai-chatgpt-device-code.ts)
- [OpenClaw private `/login` implementation](https://github.com/openclaw/openclaw/blob/3aec297be03f77cc474059a2fbe92dea7da53109/src/auto-reply/reply/commands-login.ts)
- [OpenClaw Control UI docs](https://github.com/openclaw/openclaw/blob/main/docs/web/control-ui.md)

## Hermes Agent 的处理方式

Hermes Agent 也采用服务端设备码流程：

- CLI 的 `hermes auth add openai-codex` 输出验证网址和一次性代码，在服务端轮询并把凭据保存到 `~/.hermes/auth.json`。
- Dashboard 提供受宿主认证保护的 OAuth start/status API；后台任务完成轮询和凭据保存。
- Dashboard 绑定非 loopback 地址时强制启用宿主级认证，但没有给 OpenAI 设备码接口额外增加“必须 HTTPS”的协议判断。

Hermes 的重点是保护整个管理面，而不是单独阻断 OAuth 功能。这与 AstrBot 插件应采用的边界更接近：依赖 AstrBot 已认证管理员上下文，同时对公网 HTTP 给出全局风险提示。

来源：

- [Hermes provider docs](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md)
- [Hermes CLI authentication source](https://github.com/NousResearch/hermes-agent/blob/3a915c46d34682a1299188dae63a4a06987f9790/hermes_cli/auth.py)
- [Hermes Dashboard OAuth source](https://github.com/NousResearch/hermes-agent/blob/3a915c46d34682a1299188dae63a4a06987f9790/hermes_cli/web_server.py)
- [Hermes Web Dashboard docs](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/web-dashboard.md)

## AstrBot 适配依据

AstrBot v4.27.2 已提供 Plugin Pages：插件可以在 `pages/<page_name>/index.html` 中提供页面，并通过 `window.AstrBotPluginPage` bridge 调用当前插件的扩展 API。调用由 Dashboard 父页面发起，因此会沿用宿主的 Bearer JWT 认证，同时 iframe 无法直接读取 Dashboard 的 Cookie、`localStorage` 或 DOM。

这条路径同时解决了以下问题：

- 用户无需配置域名、证书、Nginx 或 Caddy，即可在现有 Docker Dashboard 中启动设备登录。
- 不把 Dashboard JWT 暴露给插件 iframe。
- 不依赖浏览器直接导航时缺失的 Authorization 请求头。
- 与 AstrBot 插件详情页和插件市场的使用习惯一致。

## 建议的发布验收场景

发布到插件市场前至少覆盖：

1. 本机 loopback HTTP Dashboard。
2. 云服务器 Docker、公网 IP + HTTP Dashboard。
3. 域名 + HTTPS 反向代理。
4. Dashboard Plugin Page 主流程。
5. 管理员私聊命令兜底流程。
6. 未登录用户、API Key 身份和普通用户被拒绝。
7. 会话串用、过期、重复轮询、并发上限和插件卸载时任务取消。
8. OpenAI 超时、拒绝授权、网络中断和令牌交换失败时不写入半成品凭据。

