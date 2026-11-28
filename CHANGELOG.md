# Changelog

## [Unreleased]

### 新增

- 支持使用本轮聊天的订阅账号编辑同一条消息中的一张参考图。ChatUI 也可直接继续编辑同一会话中机器人最近发的图片，中间的文字回复会被跳过，本条消息的附件优先。只询问图片内容时仍以文字回答。

### 修复

- ChatUI 在机器人回复期间收到的新参考图会单独处理。机器人发出图片后，即使还在输出文字，用户也可以直接追问改图。附件失效时提示重新上传，本轮编辑失败后不会再调用文生图。

### Added

- Edit one reference image with the subscription account serving the chat turn. In ChatUI, follow up to edit the most recent image the assistant sent in the same chat, even after intervening text replies. A new attachment takes priority. Questions about the image still receive a text answer.

### Fixed

- In ChatUI, a reference image sent while the assistant is responding gets its own turn. Once the image appears, users can request an edit while the caption is still streaming. An expired attachment prompts for a new upload, and a failed edit blocks text-to-image generation for that turn.

## [v2.7.0] - 2026-11-28

### 新增

- ChatUI 在运行记录中显示 Codex 原生网络搜索的查询词，并在回复正文的引用位置显示可点击的来源卡片。
- Bot 回复在引用处标注编号，同一网址复用同一编号。根据平台能力，读者可通过正文链接、来源按钮或文末的网址访问原文。

### 修复

- 保留原文中的有效链接，合并 ChatUI 来源卡片旁指向同一网址的重复链接，并保留上游流式回复的输出行为。
- 在支持逐请求用量统计的 AstrBot 版本中，分别记录每次上游 Codex 对话请求的用量，并在交付最终回复前完成结算。

### Added

- ChatUI now shows native Codex web search queries in the run history and places clickable source cards at the cited passages.
- Bot replies number citations and reuse the same number for repeated URLs. Readers can open sources through inline links, source buttons, or a list of URLs, depending on the platform.

### Fixed

- Preserve links in the answer, collapse duplicate links next to ChatUI cards for the same URL, and preserve upstream streaming behavior.
- On AstrBot versions with per-request accounting, record usage for each upstream Codex chat request and settle it before delivering the final response.

## [v2.6.1] - 2026-11-27

### 修复

- 插件全局改用公开的 `astrbot.api.logger`，使 AstrBot 将日志路由到插件专属 logger 并遵循所配置的日志级别。

### Fixed

- Use the public `astrbot.api.logger` throughout the plugin so AstrBot routes messages to the plugin's own logger and respects its configured log level.

## [v2.6.0] - 2026-11-27

### 新增

- 支持在插件账号页面开启 Codex 原生网络搜索（默认关闭）。流式与非流式对话均会在回复中附带去重后的来源列表。
- 在 `/usage` 与账号页面展示 Codex 对话响应返回的账号额度窗口。各窗口独立过期，被动读取额度不会将账号置入冷却状态。

### 变更

- 聊天命令、搜索来源标题与 Provider 报错可跟随 AstrBot 系统语言。仍支持显式指定语言；自动模式下旧版宿主环境回退为简体中文。
- 优先使用 AstrBot Dashboard 主题配色，并将插件归入服务商适配器（provider adapter）分类。

### 修复

- 函数工具默认使用非严格（non-strict）schema，同时保留显式 strict 设置与原生工具。
- 忽略格式异常的搜索引用 URL，避免坏链接中断回复。
- 在部分额度更新时保留已确认的额度限制，并在额度被拒后共享并发的额度查询；额度请求现会携带所选账号配置的 originator。

### Added

- Enable native Codex web search from the plugin's account page. Search is off by default. Answers include a deduplicated list of sources in both streaming and non-streaming chats.
- Show account quota windows reported by Codex chat responses in `/usage` and the account page. Each window expires independently. A passive reading never puts an account into cooldown.

### Changed

- Chat commands, search source headings and provider errors can follow AstrBot's system language. Explicit language settings remain available, and older hosts fall back to Simplified Chinese in automatic mode.
- Use AstrBot's dashboard theme colors when available and list the plugin in the provider adapter category.

### Fixed

- Default function tools to non-strict schemas while preserving explicit strict settings and native tools.
- Ignore malformed search citation URLs so a bad link cannot interrupt the answer.
- Preserve confirmed quota restrictions across partial updates and share concurrent quota lookups after a quota rejection. Usage requests now carry the selected account's configured originator.

## [v2.5.1] - 2026-11-21

### 修复

- 将内置 Codex 客户端版本提升至 0.171.0，使符合条件的订阅用户在服务器与 Docker 部署中也能获取 GPT-6.2 Astra 和 Sol。
- 在后台检查 npm 上的最新稳定版 Codex 客户端版本，当其高于内置版本与本地目录缓存版本时自动采用。
- 补充 Docker 部署下的设备码登录说明与本地 Codex 凭据挂载文档。

### Fixed

- Raise the built-in Codex client version to 0.171.0 so eligible subscribers can fetch GPT-6.2 Astra and Sol in server and Docker deployments.
- Check npm for the latest stable Codex client version in the background and use it when it is newer than the built-in version and the local catalog version.
- Document device-code login and local Codex credential mounting for Docker deployments.

## [v2.5.0] - 2026-11-14

### 新增

- 在插件账号列表中直接显示默认账号徽标（含仅配置单个账号的情况）。
- 支持在每个模型的原生 OpenAI Subscribe 编辑器中选择指定账号或跟随默认账号；保留已有模型绑定，并在仅有一个可用账号时隐藏选择器。

### 变更

- 多账号配置下将默认账号选择移入账号设置齿轮菜单，移除原先独立的账号选择区域，并优化账号设置布局与操作反馈。

### 修复

- 从 OAuth 刷新失败中自动恢复，不再将临时网络故障或上游异常误判为登录过期。
- 启动前校验关键 AstrBot 集成钩子，当接口契约不兼容时阻止写入订阅配置；可选的图片钩子安全降级。
- 将临时凭据刷新错误作为生图失败上报，并在重试与生图失败日志中记录上游状态码。

### Added

- Show a default-account badge directly in the plugin account list, including when only one account is configured.
- Select an account or follow the default from each model's native OpenAI Subscribe editor. Preserve existing model bindings and hide the selector when only one account is available.

### Changed

- Move default-account selection into the account settings gear menu for multi-account setups, replacing the separate account-selection section. Refine the account settings layout and feedback.

### Fixed

- Recover from OAuth refresh failures without treating temporary network or upstream failures as an expired login.
- Validate critical AstrBot integration hooks before startup and block subscription configuration writes when those contracts are incompatible. Optional image hooks degrade safely.
- Report transient credential refresh errors as image-generation failures and include upstream status in retry and image-failure logs.

## [v2.4.0] - 2026-11-11

### 新增

- 支持通过 Codex 使用与当前聊天相同的 ChatGPT OAuth 账号和订阅额度生成图片。可在对话中直接描述画面，或使用 `/draw` 跳过追问直接出图；画面方向与构图可在提示词中描述，由 Codex 选择像素尺寸，插件按原样发送返回的 PNG。
- 为 Codex 自动缩放超尺寸的聊天输入图片，同时保留原始附件与 AstrBot 共享历史记录。长边默认限制为 2048 像素，请求原始细节时限制为 6000 像素。

### 变更

- 从「新增 Provider」列表中移除 OpenAI Subscribe（插件会自动创建该来源）。升级或重载插件时清理旧版手动添加模板，同时保留现有来源与已配置模型。

### 修复

- 区分订阅额度耗尽与普通请求速率限制（包括 Codex 在 `error.type` 中上报额度错误的情况）；生图固定使用处理当前聊天的账号。
- 适配 AstrBot 迁移后的主 Agent 构建器与图片钩子位置，同时保持对最低支持版本 AstrBot 4.27.1 的兼容。

### Added

- Generate images through Codex with the same ChatGPT OAuth account and subscription used for the chat. Describe the image in chat, or use `/draw` to skip follow-up questions. Describe orientation and composition in the prompt. Codex chooses the pixel dimensions, and the plugin sends the returned PNG as-is.
- Resize oversized chat image inputs for Codex while preserving the original attachments and AstrBot's shared history. The longest edge is limited to 2048 pixels by default or 6000 pixels when original detail is requested.

### Changed

- Remove OpenAI Subscribe from the Add Provider list because the plugin creates its source automatically. Clear the old manual-add template when upgrading or reloading the plugin while preserving the existing source and models.

### Fixed

- Distinguish exhausted subscription allowance from ordinary request rate limits, including when Codex reports the allowance error in `error.type`. Image generation stays on the account that handled the chat.
- Support AstrBot's relocated main-agent builder and image hooks while retaining compatibility with the minimum supported version, AstrBot 4.27.1.

## [v2.3.0] - 2026-10-28

### 新增

- 按 AstrBot 会话发送稳定的 `prompt_cache_key` 与 Codex 会话请求头，使长对话能够复用后端缓存的提示词，节省订阅额度并降低首字延迟。
- 与 Codex 一致请求加密推理内容与推理摘要，并由流式输出的完成项构建最终回复，使推理跨轮次与工具调用延续，且并行工具调用参数与对应调用保持绑定。
- 新增 `chat_language` 设置，支持将 `/usage`、`/effort` 与 `/openai_login` 的回复设为中文、英文、俄文或日文。
- 支持通过 `/openai_login cancel` 取消等待授权的聊天登录；未指定名称的新增账号默认以其 ChatGPT 邮箱命名，而非统一命名为 ChatGPT。

### 变更

- 以当前 Codex CLI 版本标识身份（User-Agent、`version` 请求头及模型目录查询参数），并在检测到更新的本地 Codex 时自动跟随，以便后端返回最新模型；已有来源中保存的旧版占位 User-Agent 会自动升级，自定义值则予以保留。
- 在请求之间复用各账号的 HTTP 连接，不再为每条消息新建 TCP 与 TLS 连接；当账号或代理变更时自动替换传输连接。
- `/effort` 支持 `none` 与 `minimal`，并对照当前模型的目录条目校验档位；当模型不支持会话所设档位时回退至模型默认设置，避免因 HTTP 400 报错失败。
- 对未发生变更的本地 Codex `auth.json` 解析结果最多复用 1 秒，避免单次请求中重复读取文件；刷新凭据时仍会重新读取最新文件。
- WebUI API 改为返回稳定错误码，由 Plugin View 按 Dashboard 语言（中文、英文、俄文或日文）展示本地化提示，不再混用中英文服务端文本。
- 发布压缩包仅包含 AstrBot 加载所需的文件（不含测试、截图与开发文档）；README 图片与文档链接指向 GitHub，使其在 Dashboard 的 README 弹窗中也能正常渲染。
- GitHub Release 说明直接提取自对应版本的 CHANGELOG 章节，缺少对应章节时拒绝发布。

### 修复

- 将旧版凭据列表和字典与字符串记录一并迁移至加密存储。
- 聊天登录在完成授权并开始保存账号后，取消操作会提示正在保存，且插件卸载会等待保存完成，确保内存与磁盘配置一致。
- 拼接流式推理片段时不再在每个片段之间插入换行符。
- 仅将额度接口返回的明确认证失败视为凭据过期，普通 HTTP 403 不再提示重新登录。
- 当额度接口在令牌尚未过期前拒绝该令牌时，自动刷新一次令牌并重试。
- 从实时模型目录中为每个模型仅列出一个 ID，跳过隐藏模型并遵循 Codex 选择器的排序。
- 自动回退不再在 120 秒后取消仍在思考中的模型请求；启动超时截止时间在流式连接建立后即结束，后续回退来源会获得全新的超时窗口。
- 针对无状态 Codex 后端整形请求：移除重放历史中保存的条目 ID 与状态、跳过无法重放的推理条目、缩短超长的工具调用 ID，并剔除后端拒绝的采样参数、输出长度限制及不受支持的服务等级（service-tier）参数。

### 安全

- 使用保存在插件数据目录中的密钥加密 `cmd_config.json` 内的设备码登录凭据，使 AstrBot 的 Provider 来源 API、Dashboard 响应及共享配置中不再携带可用令牌。既有明文记录会在启动时一次性加密。备份时请一并保留密钥；降级至旧版本需重新登录。

### Added

- Send a stable `prompt_cache_key` and Codex's session headers per AstrBot session so long conversations reuse the backend's cached prompt, saving allowance and first-token latency.
- Request encrypted reasoning and reasoning summaries like Codex, and build the final reply from the stream's completed output items, so reasoning carries across turns and tool calls and parallel tool call arguments stay with their call.
- A `chat_language` setting for /usage, /effort and /openai_login replies in Chinese, English, Russian or Japanese.
- `/openai_login cancel` stops a chat login that is waiting for authorization, and new accounts added without a name are named after their ChatGPT email instead of all being called ChatGPT.

### Changed

- Identify as a current Codex CLI version (User-Agent, `version` header and catalog query), following a newer local Codex when present, so the backend serves its newest models. The old placeholder User-Agent saved in existing sources upgrades automatically; custom values are kept.
- Reuse each account's HTTP connection between requests instead of opening a new TCP and TLS connection for every message; a transport is replaced when its account or proxy changes.
- `/effort` accepts `none` and `minimal` and checks the level against the current model's catalog entry; a session level the model does not support falls back to the model setting instead of failing with HTTP 400.
- Reuse a parse of an unchanged local Codex `auth.json` for up to a second instead of reading it several times per request; refreshing still reads the file fresh.
- The WebUI API reports errors as stable codes that the Plugin View shows in the dashboard's language (Chinese, English, Russian or Japanese), instead of mixing Chinese and English server text.
- Release archives contain only the files AstrBot loads (no tests, screenshots or development docs); README images and docs links point at GitHub so they also render in the dashboard's README dialog.
- GitHub release notes come from the version's CHANGELOG section, and a release without one is refused.

### Fixed

- Migrate legacy credential lists and dictionaries to encrypted storage alongside string records.
- Once a chat login starts saving an authorized account, cancellation reports that saving is in progress and plugin unload waits for it to finish, keeping in-memory and on-disk configuration consistent.
- Join streamed reasoning fragments without inserting a line break between every fragment.
- Treat only explicit authentication failures from the allowance endpoint as expired credentials; a plain HTTP 403 no longer asks you to sign in again.
- Refresh the token once and retry when the allowance endpoint rejects a token before its own expiry.
- List one ID per model from the live catalog, skip hidden models and follow Codex's picker order.
- Automatic fallback no longer cancels a request whose model is still thinking after 120 seconds; the startup deadline now ends once a stream opens, and a later fallback source gets a fresh window.
- Shape requests for the stateless Codex backend: drop stored item IDs and statuses from replayed history, skip reasoning items that cannot be replayed, shorten oversized tool call IDs, and leave out sampling, output-limit and unsupported service-tier parameters the backend rejects.

### Security

- Encrypt device-login credentials stored in `cmd_config.json` with a key kept in the plugin data directory, so AstrBot's provider source API, dashboard responses and shared configs no longer carry usable tokens. Existing plaintext records are encrypted once on startup. Keep the key with backups; downgrading to an older version requires signing in again.

## [v2.2.0] - 2026-10-18

### 新增

- 统一为单个 OpenAI Subscribe 来源，并在插件页面支持默认账号与按模型选择账号。

### 修复

- 插件更新后重新加载已有模型实例，确保已保存的模型可继续使用。
- 保存较早打开的来源编辑器快照时，保留当前账号列表、轮换后的凭据以及路由设置。
- 固定来源 ID，并拒绝过期的单账号来源保存请求。
- 当账号未单独配置代理时，使用共享来源代理刷新令牌。
- 首次迁移时保留继承的超时时间与请求参数，同时以显式模型设置优先。
- 对已合并但缺少可靠原始来源依据的模型跳过参数恢复，保护新建模型与已变更的账号绑定。

### Added

- One OpenAI Subscribe source with default and per-model account selection in the plugin page.

### Fixed

- Reload existing model instances after plugin updates so saved models remain usable.
- Preserve current accounts, rotated credentials, and routing when saving an older source editor snapshot.
- Keep the source ID fixed and reject outdated per-account source saves.
- Use the shared source proxy for token refresh when an account has no proxy override.
- Preserve inherited timeout and request parameters during first-time migration, with explicit model settings taking precedence.
- Skip parameter recovery for already consolidated models without reliable original-source evidence, protecting new models and changed account bindings.

## [v2.1.0] - 2026-10-16

### 新增

- 为 Provider 页面与插件元数据提供中文、英文、俄文和日文翻译，并跟随 AstrBot 语言设置。
- 支持独立展开多个额度面板，可同时查看多个账号的额度。

### 变更

- 将账号命名、路由设置、重新授权与移除整合至同一个设置弹窗。
- 简化设备码登录流程，提供复制按钮以及更清晰的进度和结果反馈。
- 在保持 AstrBot 入口不变的前提下将实现迁移至 `src/` 目录。
- 精简中英文 README，更新示例截图并新增开发指南。

### 修复

- 防止旧账号的额度查询（包括命中缓存数据的情况）对新替换的登录账号施加冷却。
- 恢复中断或过期的登录会话，并忽略过时的弹窗关闭事件。
- 切换语言时保留设置草稿与本地化默认名称。
- 保持窄屏下的状态标签可读性，并同步各语言的插件描述。
- 更新 README 工作流测试以匹配当前的 Plugin Views 入口。

### Added

- Chinese, English, Russian, and Japanese translations for the provider page and
  plugin metadata, following AstrBot's language setting.
- Independent allowance panels so multiple accounts can be viewed at once.

### Changed

- Combined account naming, routing, reauthorization, and removal in one settings dialog.
- Simplified device-code login with copy controls and clearer progress and results.
- Moved the implementation into `src/` while preserving the AstrBot entry point.
- Shortened both READMEs, refreshed example screenshots, and added a development guide.

### Fixed

- Prevent an old account's quota lookup from applying a cooldown to a replacement login,
  including when the lookup uses cached data.
- Recover interrupted or expired login sessions and ignore stale dialog close events.
- Preserve settings drafts and localized default names across language changes.
- Keep status tags readable on narrow screens and synchronize localized plugin descriptions.
- Update the README workflow test to match the current Plugin Views entry.

## [v2.0.0] - 2026-10-16

### 新增

- 统一 Provider 管理：支持本地 Codex 账号跟随、独立的设备码账号，以及旧版配置的自动迁移。
- 支持持久化启用开关与可选的跨可用账号自动回退，具备账号去重能力，且在开始输出后不再切换账号。

### 变更

- 优化账号列表行、行内设置、自适应主题图标及紧凑型额度窗口布局。
- 将插件页面名称从 `login` 改为 `providers`，并精简界面文案。
- 发布版本改为必须推送匹配的版本标签（Tag），直接推送到 `main` 分支不会触发发布。

### 修复

- 显式禁用 SDK 内置重试，使旧版 AstrBot 也能保持额度回退、冷却处理以及共享请求尝试次数限制。
- 在并发更新以及过期的列表或额度响应下保留账号标识与已保存设置。
- 对齐额度标签与重置时间显示，适配窄屏布局及仅返回周额度窗口的订阅计划。

### Added

- Unified Provider management with local Codex account following, independent
  device-code providers, and automatic migration of existing configurations.
- Persistent enable switches and opt-in automatic fallback across available
  providers, with account deduplication and no switching after output starts.

### Changed

- Refined provider rows, inline settings, theme-aware icons, and compact quota windows.
- Renamed the Plugin Page from `login` to `providers` and simplified its copy.
- Release publishing now requires pushing a matching version tag; pushes to `main`
  do not publish a release.

### Fixed

- Disable SDK retries explicitly so older AstrBot versions preserve quota fallback,
  cooldown handling and the shared request-attempt budget.
- Preserve provider identity and saved settings across concurrent updates and
  stale list or quota responses.
- Align quota labels and reset times, including narrow layouts and weekly-only plans.

## [v1.3.2] - 2026-10-05

### 修复

- 在尚未输出任何响应前，对明确的 Codex 流式过载和临时服务错误按指数退避与共享尝试次数上限自动重试。
- 防止开始输出后重复回放响应，并在重试时丢弃未完成的工具调用状态，同时保留凭据恢复与订阅额度冷却处理。
- 新增针对重试、重试耗尽、取消及输出安全的 SDK SSE 回归测试。

### Fixed

- Retry explicit Codex streaming overload and temporary service errors before any
  response is emitted, using exponential backoff and a shared request-attempt limit.
- Prevent response replay after output and discard partial tool-call state on retry,
  while preserving credential recovery and subscription quota cooldown handling.
- Add SDK SSE regression coverage for retries, exhaustion, cancellation, and output safety.

## [v1.3.1] - 2026-09-28

### 修复

- WebUI 拉取模型目录时保留来源中的 OAuth 凭据，避免意外回退到缺少 GPT-6 的旧模型列表。
- 新增共享来源配置下重复模型发现的回归测试。

### Fixed

- Preserve source OAuth credentials when the WebUI fetches the model catalog,
  preventing an unintended fallback to an outdated model list without GPT-6.
- Add regression coverage for repeated model discovery with shared source configuration.

## [v1.3.0] - 2026-08-28

### 新增

- 新增仅限管理员使用的 `/effort` 命令，支持按会话控制 Codex 思考强度。

### 修复

- 将会话思考强度覆盖正确应用到 WebChat 中所选的 Provider。

### Added

- Administrator-only `/effort` controls for per-session Codex reasoning effort.

### Fixed

- Apply the session reasoning-effort override to the provider selected in WebChat.

## [v1.2.0] - 2026-08-18

### 新增

- 基于来源作用域的 OAuth 凭据协调机制，支持版本化凭据记录、单飞（single-flight）刷新、冷却状态及安全的插件页账号状态展示。
- 在原生插件页面中提供显式额度查询与取消控件。
- 新增离线协议、凭据并发、Provider 隔离与 Web 边界回归测试，以及 AstrBot 兼容性 CI 工作流。

### 变更

- 保持插件为原生单账号 OpenAI OAuth 集成，不下载、不运行也不依赖 CLIProxyAPI。
- Codex 请求改用请求级作用域的 OAuth 客户端，并对订阅额度耗尽错误禁用通用 429 重试。

### Added

- Source-scoped OAuth credential coordination with versioned credential records,
  single-flight refresh, cooldown state, and safe Plugin Page account status.
- Explicit quota lookup and cancellation controls in the native Plugin Page.
- Offline protocol, credential-concurrency, provider-isolation, and Web-boundary
  regression coverage with an AstrBot compatibility CI workflow.

### Changed

- Kept the plugin as a native, single-account OpenAI OAuth integration; it does
  not download, run, or depend on CLIProxyAPI.
- Made Codex requests use request-scoped OAuth clients and disabled generic 429
  retries for subscription quota failures.

## [v1.1.0] - 2026-08-09

### 新增

- 支持通过 AstrBot 原生插件页面在云端与 Docker 环境中进行设备码登录。
- 新增管理员私聊发起设备码登录的备用方式。

### 变更

- 补充云端部署下已授权 `HTTP_PROXY` 与 `HTTPS_PROXY` 的配置说明。
- 明确不受支持地区的诊断提示以及设备码登录的代理优先级。

### Added

- Cloud and Docker-compatible device login through AstrBot's native Plugin Page.
- Administrator private-chat fallback for starting device login.

### Changed

- Documented authorized `HTTP_PROXY` and `HTTPS_PROXY` requirements for cloud deployments.
- Clarified unsupported-region diagnostics and proxy precedence for device login.

## [v1.0.0] - 2026-08-08

### 新增

- 支持通过 Codex OAuth 设备码流程登录 ChatGPT 订阅账号。
- 支持在 AstrBot WebUI 中使用 OpenAI Subscribe 来源并自动发现模型。
- 支持通过 `custom_extra_body` 配置 Codex 思考强度。
- 支持在 WebChat 中统计其他输入、缓存输入与输出 Token 用量。
- 支持服务端凭据持久化保存与自动刷新。

### 修复

- 当 Codex 流式响应以空输出结束时仍保留 Token 用量统计。
- 在 AstrBot 插件热重载时正确刷新 Provider 类。
- 加固设备码登录边界检查与额度查询重试处理。

### Added

- ChatGPT subscription login through the Codex OAuth device flow.
- OpenAI Subscribe provider and model discovery in AstrBot WebUI.
- Configurable Codex reasoning effort through `custom_extra_body`.
- WebChat token statistics for input-other, cached input, and output tokens.
- Server-side credential persistence and refresh handling.

### Fixed

- Preserved token usage when Codex streaming responses finish with empty output.
- Refreshed the provider class correctly during AstrBot plugin hot reload.
- Hardened device-login boundaries and quota-query retry handling.
