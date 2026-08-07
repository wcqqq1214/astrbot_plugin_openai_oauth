# astrbot_plugin_openai_oauth

An [AstrBot](https://astrbot.app) provider plugin: log in with your ChatGPT
account (Plus / Pro subscription) and use its quota as a model provider —
no API key needed.

It registers an `openai_codex` provider in the WebUI model configuration. AI
calls go through OpenAI's Codex backend (`chatgpt.com/backend-api/codex`) with
an OAuth token obtained from a device-code login, so billing draws on your
**subscription**, not prepaid API credits.

> ⚠️ **Terms of Service caution.** This uses the consumer ChatGPT backend by
> authenticating like the official Codex CLI, not the paid OpenAI API. It is
> meant for **personal, self-hosted use only** (single user, non-commercial).
> OpenAI can change the flow or revoke it at any time; the plugin may stop
> working without notice. Anthropic already shut down the equivalent for Claude
> (Feb 2026), and Google did the same for Gemini.

## Usage

1. Install the plugin from the AstrBot plugin market (or clone it into
   `data/plugins/`).
2. In the WebUI model configuration, add a provider of type
   **OpenAI 订阅 (ChatGPT 登录)**.
3. In its `key` field, put the credential JSON produced by the plugin's
   login flow:

   ```json
   {
     "access_token": "sk-ant-oat01-...",
     "refresh_token": "...",
     "expires": 1780000000,
     "account_id": "user-..."
   }
   ```

4. Pick a model (e.g. `gpt-5.4-mini`) and enable the provider.

## Status

- [x] Plugin scaffold + provider registration verified end-to-end (WebUI
      visibility confirmed).
- [ ] Provider logic: endpoint wiring, dynamic model list, token refresh.
- [ ] Device-code login flow (WebUI login button).
- [ ] Release.

## Architecture

- `main.py` — registers the `openai_codex` provider adapter and the plugin
  Star.
- `oauth.py` — (planned) the Codex OAuth device-code flow.
- `smoke_test.py` — verifies that a plugin can register a provider and that
  the WebUI metadata builder sees it.

The protocol follows the implementations in
[opencode](https://github.com/sst/opencode),
[openclaw](https://github.com/openclaw/openclaw) and
[hermes-agent](https://github.com/NousResearch/hermes-agent).

## License

AGPL-3.0-or-later.
