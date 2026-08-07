# astrbot_plugin_openai_oauth

[简体中文](README.md)

An [AstrBot](https://astrbot.app) provider plugin: log in with your ChatGPT
account (Plus / Pro subscription) and use its quota as a model provider —
no API key needed.

It registers an `OpenAI Subscribe` provider in the WebUI model configuration. AI
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
   **OpenAI Subscribe**.
3. Log in with your ChatGPT account. After the plugin is installed the WebUI
   exposes a login entry:
   - the **插件 WebUI** group in the sidebar → this plugin; or
   - the **打开 WebUI** button on the plugin card under **已安装插件**.
   Click **开始登录**, copy the shown link (open it in a new tab), enter the
   device code and approve. On success the credentials are written into the
   provider's `key` field automatically — no copy/paste needed.

   > If your AstrBot version does not support plugin pages, the standalone
   > login page still works:
   >
   > ```text
   > http://<astrbot-host>/api/plugins/extensions/astrbot_plugin_openai_oauth/login
   > ```
   >
   > It runs the same flow and auto-saves the credentials; only if that fails
   > do you copy the shown credential JSON into the `key` field manually.

   > Device-code login must be enabled in your ChatGPT security settings
   > (“Enable device code authentication for Codex”); the page reports it if
   > not.

4. Pick a model (e.g. `gpt-5.4-mini`) and enable the provider.

## Architecture

- `main.py` — registers the `OpenAI Subscribe` provider adapter, the plugin Star,
  and the device-login Web API (`device/start`, `device/poll`, `save_creds`,
  `login` page).
- `pages/login/index.html` — the in-WebUI plugin login page (rendered through
  AstrBot's plugin-page system; writes the credentials back on success).
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

AGPL-3.0.
