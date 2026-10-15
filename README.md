<h1 align="center">OpenAI 订阅登录</h1>

<p align="center">
  <a href="https://github.com/wcqqq1214/astrbot_plugin_openai_oauth/releases/tag/v2.0.0"><img src="https://img.shields.io/badge/version-2.0.0-4b8bbe?style=flat-square" alt="Version 2.0.0"></a>
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
- 如果需要设备码登录，打开 ChatGPT 的 **设置 → 账户安全与登录**，开启
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

Plugin Views 统一展示 Provider，本地 Codex 默认排在第一项，即使尚未登录也会保留。
每个 Provider 独立绑定凭据；本地文件不可用、额度耗尽或刷新失败时不会切到其他 Provider。
修改 `codex_auth_path` 后重载插件生效。

## 新增 Provider：设备码登录

1. 打开插件详情页的 **Plugin Views → providers**，点击 **新增 Provider**，输入名称，再点击 **开始登录**。
2. 在 OpenAI 验证网址登录 ChatGPT，输入设备码并确认授权。
3. 回到 AstrBot，等待“Provider 已保存”。每次新增都会创建独立模型来源，不覆盖已有登录。
4. 在 AstrBot 模型配置中选择对应来源（页面详情显示其 ID），添加或绑定模型后使用。
   点击列表项只是查看该项的状态与额度，不会改变当前会话使用的模型。

每项都可以独立查看登录状态、订阅套餐和额度。设备登录项支持重新授权、重命名及删除；
重新授权只更新该项。删除前需先在 AstrBot 中移除绑定该来源的模型，本地 Codex 项保留。
页面可见时每 30 秒刷新列表及当前查看项的额度。额度按接口实际返回的窗口展示，
例如 Pro 只返回每周窗口时，不补造 5 小时额度。查询失败或缺失数据不视为无限额。
等待授权时可取消登录；未完成授权的新增流程不会留下空 Provider。
聊天中的 `/usage` 查询当前选择的 OpenAI Subscribe 模型所绑定的来源。

### 旧配置迁移

插件初始化时自动迁移，重复加载不会重复创建。原 ID 与模型绑定保留：

- 旧版开启本地跟随且本地登录可用：原来源变成本地 Codex，原来保存的设备登录拆成独立来源。
- 旧版关闭本地跟随，或本地不可用且存在已保存凭据：原来源保留设备登录，另建本地 Codex。
- 其他已有 OpenAI Subscribe 来源保留 ID、凭据及连接设置，作为独立设备登录 Provider。

旧 `follow_local_codex` 设置仅用于首次迁移，不再作为账号切换开关。
凭据格式无效时保留原数据并显示需处理状态，便于重新授权。

如果暂时打不开 WebUI，管理员可以在与机器人的**私聊**中发送：

```text
/openai_login
```

机器人会回复验证网址和一次性设备码。成功后新增独立 Provider，并返回其 ID；请在模型配置中选择。群聊不会启动登录流程。

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
  设备码登录的凭据以明文保存在 AstrBot 的 `data/cmd_config.json`。
  请限制这些文件及其备份的读取权限。
- 一个 `OpenAI Subscribe` 模型来源对应一个 ChatGPT 账号。达到额度时，页面会显示冷却和重置时间；插件不会自动轮换账号。
- 如果看到 `unsupported_country_region_territory`，表示 OpenAI 不接受当前部署出口网络或账号条件。插件无法绕过这个限制。

请使用你自己的账号，并确认使用方式符合 OpenAI 的服务条款。

## 开发验证

`main.py` 只保留 AstrBot 插件入口、生命周期和命令注册；核心代码位于 `src/`：

- `runtime.py`：共享配置和凭据协调器。
- `provider.py`：模型适配、流式响应、重试和来源路由。
- `oauth.py`、`login.py`：OAuth 协议、登录会话和任务清理。
- `web_api.py`：WebUI 接口；`usage.py`、`effort.py`：额度和会话推理强度。
- `credential_store.py`、`local_codex.py`、`provider_registry.py`、`provider_routing.py`：凭据、账号来源和路由规则。

`src` 是插件内部包，使用相对导入，由 AstrBot 加载，无需单独安装。
`pages/` 保留 WebUI 静态资源；插件元数据和配置描述保留在根目录。

使用本地 AstrBot 的解释器执行 `tests/run_tests.py`。它会测试当前插件仓库而非
已部署的插件副本，并使用临时 Codex 目录，避免读取或刷新真实账号凭据。

## License / 许可证

AGPL-3.0。

## 发布流程

推送 `main` 仅更新代码并运行测试，不发布 Release。准备发布时，将
`metadata.yaml`、项目版本和更新日志保持一致，创建并推送对应的 `vX.Y.Z` 标签。
发布流程会校验标签与插件版本一致后打包发布；仅创建本地标签不会触发发布。
