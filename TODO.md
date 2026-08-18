# TODO / 改进方向

> 待办与潜在改进。已实现/已发布的功能见 CHANGELOG.md。

## 改进方案 A：原生 OpenAI OAuth 稳定化

**状态**：实施中。

### 决策

继续维护纯 Python 的 `OpenAI Subscribe` provider，直接使用 ChatGPT / Codex
OAuth 与 `chatgpt.com/backend-api/codex`。借鉴成熟代理在账号状态、刷新协调、
冷却和可观察性上的设计，但不下载、运行、嵌入或依赖 CLIProxyAPI。

这项插件的目标是让个人自托管用户只需在 AstrBot 的 Plugin Page 中完成一次
ChatGPT 设备码登录，而不是要求再部署一个代理服务、二进制或本地端口。

### 已固定的范围

- 只支持 OpenAI / ChatGPT Codex OAuth。
- 一个 `OpenAI Subscribe` provider source 对应一个 ChatGPT 账号。
- 凭据继续保存在 AstrBot `data/cmd_config.json` 的 provider source `key` 字段；
  不额外建立 token 文件、进程或本地网关。
- 保留 AstrBot 原生 Plugin Page、`/openai_login` 私聊管理员兜底和 `/usage`。
- 所有 OAuth 控制面请求与推理请求直接发往 OpenAI 官方域名。

### 明确不做

- CLIProxyAPI 二进制下载、子进程、Docker sidecar、端口探测或生命周期管理。
- CLIProxyAPI Go SDK、Go toolchain、OpenAI-compatible 本地 API 网关。
- Gemini、Claude、Grok 或其他订阅 provider 的 OAuth。
- 多账号池、自动轮询、权重路由、额度 failover 或 session affinity。
- 后台配额轮询、数据库指标系统或浏览器保存 OAuth token。

### 实施重点

1. **source 级凭据协调**
   - 用 provider source `id` 精确定位凭据，拒绝重复或冲突 source ID。
   - 将 legacy JSON 惰性升级为版本化凭据记录。
   - 让同一 source 下的多个模型实例共享单飞 refresh lock，避免 refresh-token
     rotation 竞争。
   - 登录完成与 token refresh 共用同一写入路径；重新登录优先于旧 refresh 结果。

2. **请求级认证与错误策略**
   - 每次 Codex 请求使用不可变的凭据快照和局部 OpenAI client，不修改共享 client
     的 access token 或 account header。
   - token 失效时只在流尚未输出内容前尝试一次 refresh/replay；有任何 delta 后绝不
     重放，避免重复文本、工具调用或计费。
   - 将 `usage_limit_reached` 与普通 429 区分；前者进入 source 级冷却并停止无效
     重试。
   - 保留有界的网络/5xx 重试，避免把额度耗尽交给通用 rate-limit 重试层。

3. **登录与状态体验**
   - Plugin Page 使用 source 配置的 proxy，不接受浏览器传入的 OAuth proxy。
   - 提供取消设备登录、脱敏账号状态和用户显式触发的额度查询。
   - 只显示 `ready`、`refreshing`、`reauth_required`、`cooling`、`degraded` 等状态；
     不返回 access token、refresh token、完整 account ID 或上游原始响应。

4. **协议与发布验证**
   - 将 OAuth、models、usage 和错误分类集中在 `oauth.py`，用脱敏 fixture 式测试
     覆盖已知新旧 schema。
   - 持续运行 source 并发 refresh、登录覆盖 refresh、流式不重放、WebUI 鉴权与
     Plugin Page 静态边界测试。
   - CI 固定 AstrBot 兼容 revision，运行 Ruff 和无网络 AstrBot 集成回归；真实设备码
     登录与订阅额度行为仅在发布前使用自有账号人工验收。

### 已知边界

- OpenAI 的 Codex OAuth 与后端接口不是稳定公开 API；隔离协议逻辑和回归测试只能
  降低上游变化的修复成本，不能保证接口永不变化。
- 凭据仍是 AstrBot 配置中的明文。请限制 `data/cmd_config.json` 及其备份的读取权限。
- 刷新锁只协调一个 AstrBot 进程；多个独立进程共享同一配置文件不在支持范围内。
- 单账号达到订阅额度后不会自动切换账号；插件会显示冷却状态和可用的重置时间。
