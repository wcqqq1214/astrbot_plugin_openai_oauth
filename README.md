<h1 align="center">OpenAI 订阅登录</h1>

<p align="center">
  <img src="logo.png" alt="OpenAI Subscribe" width="240">
</p>

<p align="center">
  <a href="README_en.md">English</a>
</p>

一个 [AstrBot](https://astrbot.app) 插件：用你的 ChatGPT 账号（Plus / Pro 订阅）登录，将账号订阅额度作为模型 provider 使用——无需 API Key。

它在 WebUI 模型配置中注册了一个 `OpenAI Subscribe` provider。AI 调用通过 OpenAI 的 Codex 后端（`chatgpt.com/backend-api/codex`）发出，使用设备码登录获取的 OAuth token，因此计费走你的**订阅额度**，而不是预付的 API 余额。

## 使用方法

1. 从 AstrBot 插件市场安装（或克隆到 `data/plugins/`）。
2. 在 WebUI 模型配置中添加一个类型为 **OpenAI Subscribe** 的 provider。
3. 登录你的 ChatGPT 账号。在 WebUI 插件详情页点击 [打开登录页](/api/v1/plugins/extensions/astrbot_plugin_openai_oauth/login) 直达（地址自适应，无需改动插件）。在 GitHub 等外部页面看到本说明时该相对链接不可用，请手动打开：

   ```text
   https://<host>/api/v1/plugins/extensions/astrbot_plugin_openai_oauth/login
   ```

   把 `<host>` 换成你访问 WebUI 的局域网地址或域名（可带端口）。设备登录默认始终要求 HTTPS，包括从本机访问。使用 TLS 反向代理时，需要按 AstrBot/ASGI 的可信代理配置正确传递请求 scheme；插件不会自行信任客户端提供的 `X-Forwarded-Proto`。

   只有在隔离的本机开发环境中，才可在插件配置中显式开启 `allow_insecure_local_http`，然后通过 `http://localhost:<port>/...` 或 `http://127.0.0.1:<port>/...` 访问。即使开启，该例外也同时要求连接对端和 Host 都是回环地址。不要在反向代理或任何远程可达的部署中开启：本机代理可能把远程浏览器伪装成回环连接，而明文 HTTP 无法保护 WebUI 会话或 OAuth 流程。

   点击 **开始登录**，复制显示的 OpenAI 链接（到新标签页打开）并输入设备码完成授权。登录成功后，服务端会把凭据自动写入 provider 的 `key` 字段，浏览器不会接收或显示 access token / refresh token。如果自动写入失败，页面会提示重新登录或检查配置。

   > 需要在你的 ChatGPT 安全设置中开启设备码登录（“Enable device code authentication for Codex”）；未开启时页面会提示。

4. 选择模型（例如 `gpt-5.4-mini`）并启用该 provider。

### 设置模型思考强度（可选）

在 WebUI 的模型配置中，打开 `OpenAI Subscribe` 下具体模型的编辑窗口，找到
`自定义请求体参数（custom_extra_body）`。在可视化编辑器中点击添加，填写：

- 键名：`reasoning_effort`
- 值类型：`string`
- 值：`max` 或 `ultra`

如果直接编辑底层 JSON，等价配置为：

```json
{
  "reasoning_effort": "max"
}
```

插件会把它转换为 Codex Responses API 的
`{"reasoning": {"effort": "max"}}`。可按模型能力使用
`none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max` 或 `ultra`。
`max`/`ultra` 不是所有模型或后端都支持；插件不会预先拦截这些值，最终以接口返回为准。

对支持它们的 Codex 模型，把示例中的值改成 `max` 或 `ultra` 即可。这里的
`ultra` 仅作为 `reasoning.effort` 转发；本插件不会额外开启 Codex Multi-agent
beta。如果后端要求额外的 Multi-agent 参数，当前插件尚未实现该扩展。
`max_tokens` 则是输出长度上限，不是思考强度。

## 网络与凭据流向

- 插件只与 OpenAI 官方域名通信：`auth.openai.com`（OAuth 设备登录、token 刷新）与 `chatgpt.com`（`backend-api/codex` 推理与模型列表、`backend-api/wham/usage` 额度查询）。访问令牌只出现在发给这两个域的请求头/请求体中，不会发往任何第三方。
- `proxy` 默认留空（直连），仅当你的网络无法直连 OpenAI 时才配置；配置后相关请求经该代理转发。`originator` 默认 `codex_cli_rs`，与官方 Codex CLI 一致（Cloudflare 对首方客户端白名单放行）；做成可配置是为了能跟随 OpenAI 后续接受的值，无需等待插件发版。
- 登录页与 `device/start` / `device/poll` 均挂在 AstrBot 的 `/api/v1/plugins/extensions/` 下，只接受 WebUI 用户会话，不接受通用 API Key。设备会话与登录用户绑定、数量受限，并在完成或超时后清理。OAuth 凭据只在服务端交换和保存，不会返回浏览器。登录后的凭据（access_token / refresh_token）保存在 provider 的 `key` 字段，落盘为 AstrBot 配置（`data/cmd_config.json`）中的明文；请限制该文件及备份的读取权限。
- 本项目是个人自用工具：用你自己的 ChatGPT 账号订阅额度（Codex OAuth）跑模型，不提供免费 API 途径。请自行确认你的使用方式符合 OpenAI 服务条款。

## License / 许可证

AGPL-3.0。
