# Changelog

## [Unreleased]

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
