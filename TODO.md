# TODO / 改进方向

> 待办与潜在改进。已实现/已发布的功能见 CHANGELOG.md。

## 改进方案:内嵌 CLIProxyAPI,订阅账号 → 本地 API

**状态**:方案评估中,未实施。

### 背景与动机

当前插件是自研的 Codex OAuth 逆向,存在四个结构性局限:

1. **单账号**:只持有一个 ChatGPT 订阅的凭据,Plus 当日额度打到 `usage_limit_reached`(约 23h 重置)后当日即不可用。
2. **协议脆弱**:直接依赖 `chatgpt.com/backend-api/codex` 与设备码流程,上游协议一变就要改插件(已有先例:流式 400、账号 id 嵌套 claim 等 live 发现)。
3. **无运维能力**:没有配额感知、冷却、重试、failover、session affinity。
4. **单 provider**:只能跑 Codex/GPT,无法把 Gemini / Claude / Grok 订阅也接进 AstrBot。

[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)(Go, MIT, 47.5k star, 活跃)正是把这些做成了产品级:OAuth 登录多个订阅账号 → 对外暴露 OpenAI/Gemini/Claude 兼容的本地 API(默认 `http://127.0.0.1:8317`),内置多账号轮询、权重路由、配额感知、冷却/重试、failover、session affinity。

### 方案对比

| 方案 | 做法 | 优点 | 代价 |
|---|---|---|---|
| **A. 内嵌 CLIProxyAPI 子进程**(主推) | 插件首次启用时下载/管理 `cli-proxy-api` 二进制,替用户跑 `-codex-login` 等登录,provider 的 base_url 指向本地 8317 | 白拿全部多账号/配额/冷却能力;协议维护外包给成熟项目;顺带支持 Gemini/Claude/Grok | 多一个 Go 进程需管理生命周期;安装体积变大;登录入口从插件页改为 CLIProxyAPI 流程 |
| B. Go SDK 内嵌(`sdk/auth`) | 用 CLIProxyAPI 的 Go SDK 编译插件能力进进程,不起子进程 | 无独立进程,生命周期简单 | 需 Go toolchain + CGo/静态链接,AGPL 插件与 MIT SDK 合并许可证需确认;复杂度高 |
| C. 借鉴设计自研扩展 | 保持纯 Python,自研多账号 + 配额感知 + 冷却 | 无外部依赖,完全可控 | 重新实现别人已验证的轮询/冷却/affinity,工作量最大且最脆 |

### 推荐:方案 A 的落地步骤

1. **二进制管理**:插件内封装下载器(Releases 按平台取二进制)+ 版本校验 + 生命周期(`start`/`stop`,端口 8317 占用检测,`ocx` 式 shim 按需拉起)。
2. **登录打通**:复用 CLIProxyAPI 的 OAuth 子命令(`-codex-login`/`-antigravity-login`/`-claude-login`/`-xai-login`),或走其 Web 管理面板;凭证落 `~/.cli-proxy-api`,插件读同一 auth-dir。
3. **Provider 接入**:插件注册的 provider 的 base_url 指 `http://127.0.0.1:8317`(OpenAI 兼容 `/v1/chat/completions`、Codex 走 `/v1/responses`),key 用 CLIProxyAPI `config.yaml` 的 `api-keys`。
4. **配置透传**:在 AstrBot WebUI 暴露"添加账号/查看配额"入口,配额数据来自 CLIProxyAPI Management API。
5. **保留现有登录作为回退**:自研 device-code 流程先不删,CLIProxyAPI 接入验证通过后再评估退役。

### 待验证 / 风险

- **账号封禁风险放大**:多账号轮询会放大单账号 ToS 风险(CLIProxyAPI 官方也声明 Anthropic 等可能封号)。个人自用场景务必只接自有账号。
- **进程生命周期**:AstrBot 重启/崩溃时 CLIProxyAPI 子进程需跟随回收;`--reload` 热重载下避免重复拉起。
- **许可证**:CLIProxyAPI 为 MIT,子进程方案无代码合并、无冲突;方案 B(内嵌 SDK)需另查 AGPL 插件与 MIT SDK 合并的合规性。
- **live 验证**:登录 + 真实调用 + 多账号 failover 需对真实后端跑通后再并入 release。

### 参考

- CLIProxyAPI:https://github.com/router-for-me/CLIProxyAPI(README 含完整用法;默认端口 8317)
- 其 Go SDK 内嵌文档:`docs/sdk-usage.md` / `sdk/auth`(对应方案 B)
