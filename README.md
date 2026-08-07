# astrbot_plugin_openai_oauth

[English](README_EN.md)

一个 [AstrBot](https://astrbot.app) 插件：用你的 ChatGPT 账号（Plus / Pro 订阅）登录，将账号订阅额度作为模型 provider 使用——无需 API Key。

它在 WebUI 模型配置中注册了一个 `OpenAI Subscribe` provider。AI 调用通过 OpenAI 的 Codex 后端（`chatgpt.com/backend-api/codex`）发出，使用设备码登录获取的 OAuth token，因此计费走你的**订阅额度**，而不是预付的 API 余额。

## 使用方法

1. 从 AstrBot 插件市场安装（或克隆到 `data/plugins/`）。
2. 在 WebUI 模型配置中添加一个类型为 **OpenAI Subscribe** 的 provider。
3. 登录你的 ChatGPT 账号。在 WebUI 插件详情页点击 [打开登录页](/api/v1/plugins/extensions/astrbot_plugin_openai_oauth/login) 直达（地址自适应，无需改动插件）。在 GitHub 等外部页面看到本说明时该相对链接不可用，请手动打开：

   ```text
   http://<host>/api/v1/plugins/extensions/astrbot_plugin_openai_oauth/login
   ```

   把 `<host>` 换成你访问 WebUI 的地址（localhost、局域网 IP、域名、端口均可）。点击 **开始登录**，复制显示的链接（到新标签页打开）并输入设备码完成授权。登录成功后凭据会自动写入 provider 的 `key` 字段，无需复制粘贴；只有自动写入失败时才需要把显示的凭据 JSON 手动复制到 `key` 字段。

   > 需要在你的 ChatGPT 安全设置中开启设备码登录（“Enable device code authentication for Codex”）；未开启时页面会提示。

4. 选择模型（例如 `gpt-5.4-mini`）并启用该 provider。

## 架构

- `main.py` — 注册 `OpenAI Subscribe` provider 适配器、插件 Star、设备登录 Web API（`device/start`、`device/poll`、`save_creds`）以及独立登录页（`/login`，链接登录入口，登录成功后自动写回凭据）。
- `oauth.py` — Codex OAuth 协议常量、凭据辅助、token 刷新以及设备码登录协议（user-code 请求、轮询、授权码交换、JWT account-id 提取）。
- `smoke_test.py` — 验证插件能注册 provider，且 WebUI 元数据构建器能看到它。
- `wiring_test.py` — 用假凭据实例化 provider，验证端点接线、key 处理与刷新短路（无网络）。
- `login_test.py` — 用 mock 网络走一遍设备登录协议与 web handler（无网络）。

协议参考 [opencode](https://github.com/sst/opencode)、[openclaw](https://github.com/openclaw/openclaw) 与 [hermes-agent](https://github.com/NousResearch/hermes-agent) 的实现。

## License / 许可证

AGPL-3.0。
