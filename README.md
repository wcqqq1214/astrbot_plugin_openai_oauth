<h1 align="center">OpenAI 订阅登录</h1>

<p align="center">
  <a href="https://github.com/wcqqq1214/astrbot_plugin_openai_oauth/releases/tag/v1.3.2"><img src="https://img.shields.io/badge/version-1.3.2-4b8bbe?style=flat-square" alt="Version 1.3.2"></a>
  <a href="https://github.com/AstrBotDevs/AstrBot"><img src="https://img.shields.io/badge/AstrBot-%E2%89%A54.27.1-4b8bbe?style=flat-square" alt="AstrBot ≥ 4.27.1"></a>
  <img src="https://img.shields.io/badge/Python-%E2%89%A53.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python ≥ 3.12">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square" alt="License: AGPL-3.0"></a>
</p>

<p align="center">
  <img src="logo.png" alt="OpenAI Subscribe" width="240">
</p>

<p align="center">
  <a href="README_en.md">English</a>
</p>

这个插件把你的 ChatGPT 账号接到 AstrBot 里。安装后，AstrBot 会多出一个
`OpenAI Subscribe` 模型来源；选择它的模型即可使用 ChatGPT/Codex 的额度，
不用另外创建或填写 OpenAI API Key。

简单说：这里消耗的是 ChatGPT 账号可用的 Codex 额度，不是 OpenAI API 预付余额。

## 开始前，先确认这几件事

- AstrBot 版本需要为 `4.27.1` 或更高。
- 你需要一个可以使用 Codex 的 ChatGPT 账号。
- 如果 Dashboard 暴露在公网，请优先配置 HTTPS、VPN 或 SSH 隧道。明文 HTTP
  也能完成设备码登录，但 Dashboard 会话可能被窃取，不建议这样用。
- 如果需要备用设备码登录，打开 ChatGPT 的 **设置 → 账户安全与登录**，开启
  **为 Codex 启用设备代码授权**。

![在 ChatGPT 账户安全与登录设置中启用 Codex 设备代码授权](images/enable-device-code-auth-codex-zh.png)

*图：在 ChatGPT 的 **设置 → 账户安全与登录** 中，打开
**为 Codex 启用设备代码授权**。*

> 设备码和密码一样敏感：只在 OpenAI 的验证页面输入，不要发给别人。

## 默认：跟随本地 Codex 账号

安装后默认读取 **AstrBot 所在机器**的 Codex 当前登录账号，无需进入 Plugin Page
再次登录。先在该机器登录 Codex，再在 AstrBot 的模型配置中选择 `OpenAI Subscribe`。

- 默认读取 `$CODEX_HOME/auth.json`；未设置 `CODEX_HOME` 时读取 `~/.codex/auth.json`。
  也可以在插件设置的 `codex_auth_path` 中填写完整文件路径。
- 每次模型请求和额度查询都会重新读取当前账号；切换账号后，下次请求自动跟随。
  已经开始的请求继续使用其开始时的账号。
- 本地凭据不会复制到 AstrBot 配置。自动刷新会将轮换后的 token 原子写回 Codex
  原文件，并保留其他字段。AstrBot 需要该文件的读取权限和所在目录的写入权限。
- Docker 需要将整个 Codex 凭据目录挂载到容器，并配置容器内的文件路径；只挂载
  单个文件可能导致原子替换失败。云端 AstrBot 无法直接读取你电脑的登录状态。
- 当前支持文件中的 ChatGPT OAuth 登录；仅存于系统钥匙串的登录、API Key 登录和
  浏览器 ChatGPT 登录不属于此模式，使用下方设备码登录即可。

本地文件不存在、不可读或格式不受支持时，会使用 Plugin Page 保存的备用账号。
本地账号额度耗尽或刷新失败时不会自动切换到另一个账号；可以重新登录 Codex，或在
插件设置中关闭 `follow_local_codex`，仅使用备用账号。修改插件设置后重载插件。
Plugin Page 会显示当前使用本地 Codex 还是插件保存的账号。

## 备用：Plugin Page 设备码登录

1. 在 AstrBot 插件市场安装本插件；手动安装则把项目放进 `data/plugins/`。
2. 打开该插件的详情页，进入它的 **Plugin Views**（旧称 Plugin Page），点击 **添加备用登录**，再点击 **开始登录**。
3. 页面会给出一个 OpenAI 验证网址和一串设备码。打开该网址，登录你的 ChatGPT
   账号，然后输入设备码并确认授权。
4. 回到 AstrBot，等待页面显示“备用账号已保存”。凭据只会保存在 AstrBot 服务端，不会显示在
   浏览器或聊天消息里。
5. 如果本地 Codex 凭据可用，它仍然优先；若要立即使用刚登录的备用账号，关闭插件
   设置中的 `follow_local_codex` 并重载插件。然后使用 `OpenAI Subscribe` 模型来源。

账号页展示当前来源、登录状态、备用账号是否已保存及真实订阅类型；页面可见时每 30 秒更新。额度按接口实际返回的窗口展示，例如 Pro 只返回每周窗口时仅显示每周剩余比例和重置时间，不补造 5 小时额度。查询失败或缺失数据会显示暂不可用，不视为无限额。

设备码还在等待授权时，也可以点 **取消登录**。
登录后，在聊天中发送 `/usage` 也能查询额度。

如果暂时打不开 WebUI，管理员可以在与机器人的**私聊**中发送：

```text
/openai_login
```

机器人会回复验证网址和一次性设备码。请在私聊里完成它；群聊不会启动登录流程。

## 想调整模型的思考强度？（可选）

不设置也可以正常使用，模型会采用默认行为。

1. 进入模型配置，编辑使用 `OpenAI Subscribe` 的那一个模型。
2. 找到 **自定义请求体参数（`custom_extra_body`）**。
3. 在 **Reasoning Effort** 输入框中填写想要的值，然后点击右下角 **确认** 保存。

![在内置的 Reasoning Effort 预设中填写 max](images/reasoning-effort-preset-zh.png)

*图：AstrBot 内置的 **Reasoning Effort** 预设。填写 `max` 后点击 **确认** 即可。*

本插件支持以下值，填写时请使用小写英文：

| WebUI 里常见的显示名 | 要填写的值 |
| --- | --- |
| Light | `low` |
| Medium | `medium` |
| High | `high` |
| Extra High | `xhigh` |
| Max | `max` |

请填写右侧的值，不要把左侧显示名直接填进去。插件会自动转换为 Codex 所需的请求格式。

### 只给当前会话调整思考强度

管理员可以在私聊或群聊的当前会话里使用：

```text
/effort
/effort low
/effort medium
/effort high
/effort xhigh
/effort max
/effort default
```

`/effort` 用来查看当前设置；指定一个值后，会在下一次请求时生效。
`/effort default` 会取消这次会话的覆盖，恢复模型配置里的默认值。它不会改动其他会话，
也不会改掉模型的全局配置。

## 网络、额度和安全

- 默认直连时，插件只会访问 OpenAI 的 `auth.openai.com` 和 `chatgpt.com`。登录、刷新凭据、获取模型、查询额度和调用模型都走这两个域名。
- 只有网络无法直连 OpenAI 时才需要填写插件的 `proxy`。如果 AstrBot 跑在 Docker 或云服务器，并使用已获授权的出站代理，请在 **AstrBot 容器**中同时设置 `HTTP_PROXY` 和 `HTTPS_PROXY`，插件自己的 `proxy` 留空即可；插件里填写的 `proxy` 优先级更高。
- 登录凭据不会返回到浏览器，也不会发到聊天里。本地模式使用 Codex 的 `auth.json`；
  设备码登录的备用凭据以明文保存在 AstrBot 的 `data/cmd_config.json`。
  请限制这些文件及其备份的读取权限。
- 一个 `OpenAI Subscribe` 模型来源对应一个 ChatGPT 账号。达到额度时，页面会显示冷却和重置时间；插件不会自动轮换账号。
- 如果看到 `unsupported_country_region_territory`，表示 OpenAI 不接受当前部署出口网络或账号条件。插件无法绕过这个限制。

请使用你自己的账号，并确认使用方式符合 OpenAI 的服务条款。

## 开发验证

使用本地 AstrBot 的解释器执行 `tests/run_tests.py`。它会测试当前插件仓库而非
已部署的插件副本，并使用临时 Codex 目录，避免读取或刷新真实账号凭据。

## License / 许可证

AGPL-3.0。
