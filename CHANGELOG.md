# Changelog

## [1.0.0] - 2026-08-08

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
