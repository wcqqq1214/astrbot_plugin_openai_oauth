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
3. Log in with your ChatGPT account using the plugin's device-code page:

   ```text
   http://<astrbot-host>/api/plugins/extensions/astrbot_plugin_openai_oauth/login
   ```

   Click **开始登录**, open the shown link, enter the device code, and
   approve. When the login succeeds the page shows the credential JSON —
   copy it into the provider's `key` field:

   ```json
   {
     "access_token": "sk-ant-oat01-...",
     "refresh_token": "...",
     "expires": 1780000000,
     "account_id": "user-..."
   }
   ```

   > Device-code login must be enabled in your ChatGPT security settings
   > (“Enable device code authentication for Codex”); the page reports it if
   > not.

4. Pick a model (e.g. `gpt-5.4-mini`) and enable the provider.

## Status

- [x] Plugin scaffold + provider registration verified end-to-end (WebUI
      visibility confirmed).
- [x] Provider logic: endpoint wiring, dynamic model list, token refresh
      (each refresh is persisted back into the provider config, so a
      restart does not require re-login).
- [x] Device-code login flow (login page + polling backend; copy the
      resulting credential JSON into the provider `key` field).
- [x] Live verification against the real ChatGPT backend (device login, model
      catalog, and the Responses request shape — account-id JWT claim and the
      backend's stream-only requirement).
- [ ] Release.

## Architecture

- `main.py` — registers the `openai_codex` provider adapter, the plugin Star,
  and the device-login Web API (`device/start`, `device/poll`, `login` page).
- `oauth.py` — Codex OAuth protocol constants, credential helpers, token
  refresh, and the device-code login protocol (user-code request, polling,
  authorization-code exchange, JWT account-id extraction).
- `smoke_test.py` — verifies that a plugin can register a provider and that
  the WebUI metadata builder sees it.
- `wiring_test.py` — instantiates the provider with fake credentials and
  verifies endpoint wiring, key handling and refresh short-circuits
  (no network).
- `login_test.py` — exercises the device-login protocol and the web handlers
  with a mocked network (no network).

The protocol follows the implementations in
[opencode](https://github.com/sst/opencode),
[openclaw](https://github.com/openclaw/openclaw) and
[hermes-agent](https://github.com/NousResearch/hermes-agent).

## License

AGPL-3.0-or-later.
