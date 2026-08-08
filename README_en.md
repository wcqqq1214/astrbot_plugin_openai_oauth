<h1 align="center">OpenAI 订阅登录</h1>

<p align="center">
  <img src="logo.png" alt="OpenAI Subscribe" width="240">
</p>

<p align="center">
  [简体中文](README.md)
</p>

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

## Network and credential flow

- The plugin only talks to OpenAI-owned hosts: `auth.openai.com` (OAuth
  device login, token refresh) and `chatgpt.com` (`backend-api/codex` for
  inference and the model catalog, `backend-api/wham/usage` for quota). The
  access token appears only in requests to these two hosts and is never sent
  anywhere else.
- `proxy` is empty by default (direct connection); configure it only when your
  network cannot reach OpenAI directly — requests are then forwarded through
  that proxy. `originator` defaults to `codex_cli_rs`, matching the official
  Codex CLI (Cloudflare allows first-party clients by this header); it is
  configurable so it can follow whatever value OpenAI accepts next, without a
  plugin release.
- The login page and `device/start` / `device/poll` / `save_creds` all live
  under AstrBot's `/api/v1/plugins/extensions/` and are protected by the WebUI
  session auth — unauthenticated access returns 401. Stored credentials
  (access_token / refresh_token) live in the provider's `key` field, persisted
  as plaintext in the AstrBot config (`data/cmd_config.json`).
- This is a personal-use tool: it runs models on your own ChatGPT subscription
  quota (Codex OAuth) and offers no free-API path. Please make sure your usage
  complies with OpenAI's terms of service.

## License

AGPL-3.0.
