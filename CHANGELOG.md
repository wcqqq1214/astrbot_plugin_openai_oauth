# Changelog

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
