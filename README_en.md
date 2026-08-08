# astrbot_plugin_openai_oauth

[简体中文](README.md)

An [AstrBot](https://astrbot.app) provider plugin: log in with your ChatGPT
account (Plus / Pro subscription) and use its quota as a model provider —
no API key needed.

It registers an `OpenAI Subscribe` provider in the WebUI model configuration. AI
calls go through OpenAI's Codex backend (`chatgpt.com/backend-api/codex`) with
an OAuth token obtained from a device-code login, so billing draws on your
**subscription**, not prepaid API credits.
## Usage

1. Install the plugin from the AstrBot plugin market (or clone it into
   `data/plugins/`).
2. In the WebUI model configuration, add a provider of type
   **OpenAI Subscribe**.
3. Log in with your ChatGPT account. On the WebUI plugin detail page, click
   [open the login page](/api/v1/plugins/extensions/astrbot_plugin_openai_oauth/login)
   to go straight there — the link adapts to your host automatically, no
   plugin change needed. When reading this README on GitHub or elsewhere the
   relative link is not usable, so open this address manually:

   ```text
   http://<host>/api/v1/plugins/extensions/astrbot_plugin_openai_oauth/login
   ```

   Replace `<host>` with the address you use to reach the WebUI (localhost,
   LAN IP, domain or port all work). Click **开始登录**, copy the shown link
   (open it in a new tab), enter the device code and approve. On success the
   credentials are written into the provider's `key` field automatically — no
   copy/paste needed. Only if that auto-save fails do you copy the shown
   credential JSON into the `key` field manually.

   > Device-code login must be enabled in your ChatGPT security settings
   > (“Enable device code authentication for Codex”); the page reports it if
   > not.

4. Pick a model (e.g. `gpt-5.4-mini`) and enable the provider.

## Architecture

- `main.py` — registers the `OpenAI Subscribe` provider adapter, the plugin Star,
  the device-login Web API (`device/start`, `device/poll`, `save_creds`), and the
  standalone login page (`/login`; the link-login entry, auto-saves credentials
  on success).
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
