# Changelog

## [Unreleased]

### Added

- Send a stable `prompt_cache_key` and Codex's session headers per AstrBot session so long conversations reuse the backend's cached prompt, saving allowance and first-token latency.

### Changed

- Identify as a current Codex CLI version (User-Agent, `version` header and catalog query), following a newer local Codex when present, so the backend serves its newest models. The old placeholder User-Agent saved in existing sources upgrades automatically; custom values are kept.

### Fixed

- Join streamed reasoning fragments without inserting a line break between every fragment.
- Treat only explicit authentication failures from the allowance endpoint as expired credentials; a plain HTTP 403 no longer asks you to sign in again.
- Refresh the token once and retry when the allowance endpoint rejects a token before its own expiry.
- List one ID per model from the live catalog, skip hidden models and follow Codex's picker order.
- Automatic fallback no longer cancels a request whose model is still thinking after 120 seconds; the startup deadline now ends once a stream opens, and a later fallback source gets a fresh window.
- Shape requests for the stateless Codex backend: drop stored item IDs and statuses from replayed history, skip reasoning items that cannot be replayed, shorten oversized tool call IDs, and leave out sampling, output-limit and unsupported service-tier parameters the backend rejects.

## [v2.2.0] - 2026-10-18

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

### Fixed

- Retry explicit Codex streaming overload and temporary service errors before any
  response is emitted, using exponential backoff and a shared request-attempt limit.
- Prevent response replay after output and discard partial tool-call state on retry,
  while preserving credential recovery and subscription quota cooldown handling.
- Add SDK SSE regression coverage for retries, exhaustion, cancellation, and output safety.

## [v1.3.1] - 2026-09-28

### Fixed

- Preserve source OAuth credentials when the WebUI fetches the model catalog,
  preventing an unintended fallback to an outdated model list without GPT-6.
- Add regression coverage for repeated model discovery with shared source configuration.

## [v1.3.0] - 2026-08-28

### Added

- Administrator-only `/effort` controls for per-session Codex reasoning effort.

### Fixed

- Apply the session reasoning-effort override to the provider selected in WebChat.

## [v1.2.0] - 2026-08-18

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

### Added

- Cloud and Docker-compatible device login through AstrBot's native Plugin Page.
- Administrator private-chat fallback for starting device login.

### Changed

- Documented authorized `HTTP_PROXY` and `HTTPS_PROXY` requirements for cloud deployments.
- Clarified unsupported-region diagnostics and proxy precedence for device login.

## [v1.0.0] - 2026-08-08

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
