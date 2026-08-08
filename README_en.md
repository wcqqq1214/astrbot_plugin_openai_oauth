<h1 align="center">OpenAI 订阅登录</h1>

<p align="center">
  <img src="logo.png" alt="OpenAI Subscribe" width="240">
</p>

<p align="center">
  <a href="README.md">简体中文</a>
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
   https://<host>/api/v1/plugins/extensions/astrbot_plugin_openai_oauth/login
   ```

   Replace `<host>` with the LAN address or domain you use to reach the WebUI
   (including its port when needed). Device login requires HTTPS by default,
   including access from the same machine. When using a TLS reverse proxy,
   configure AstrBot/ASGI's trusted proxy handling so the request scheme is set
   correctly; the plugin does not trust a client-supplied `X-Forwarded-Proto`
   header itself.

   For an isolated local development environment only, you may explicitly
   enable `allow_insecure_local_http` in the plugin configuration and then use
   `http://localhost:<port>/...` or `http://127.0.0.1:<port>/...`. Even with the
   option enabled, both the connection peer and Host must be loopback. Never
   enable it behind a reverse proxy or on a remotely reachable deployment: a
   local proxy can make a remote browser look like a loopback connection, and
   plaintext HTTP cannot protect the WebUI session or OAuth flow.

   Click **开始登录**, copy the shown OpenAI link (open it in a new tab), enter
   the device code and approve. The server then writes the credentials into
   the provider's `key` field automatically. The browser never receives or
   displays the access or refresh token. If the server cannot save the result,
   the page asks you to retry or check the configuration.

   > Device-code login must be enabled in your ChatGPT security settings
   > (“Enable device code authentication for Codex”); the page reports it if
   > not.

4. Pick a model (e.g. `gpt-5.4-mini`) and enable the provider.

### Optional reasoning-effort setting

In the WebUI model configuration, edit the specific model under
`OpenAI Subscribe`, find `custom_extra_body`, and add a new entry in the
visual editor:

- Key: `reasoning_effort`
- Value type: `string`
- Value: `max` or `ultra`

If you edit the underlying JSON directly, the equivalent configuration is:

```json
{
  "reasoning_effort": "max"
}
```

The plugin converts this to the Codex Responses API shape
`{"reasoning": {"effort": "max"}}`. Depending on the model, use
`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or `ultra`.
`max` and `ultra` are not supported by every model or backend; the plugin does
not pre-validate these values, so the backend remains the final authority.

For a Codex model that supports them, replace the example value with `max` or
`ultra`. Here `ultra` is only forwarded as `reasoning.effort`; this plugin does
not additionally enable the Codex Multi-agent beta. If the backend requires
extra Multi-agent parameters, that extension is not implemented here.
`max_tokens` controls the output length limit; it is separate from reasoning
effort.

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
- The login page and `device/start` / `device/poll` live under AstrBot's
  `/api/v1/plugins/extensions/`. They accept WebUI user sessions, not general
  API keys. Device sessions are user-bound, bounded and cleaned up after
  completion or expiry. OAuth credentials are exchanged and saved only on the
  server and are never returned to the browser. Stored credentials
  (access_token / refresh_token) live in the provider's `key` field, persisted
  as plaintext in the AstrBot config (`data/cmd_config.json`); restrict read
  access to that file and its backups.
- This is a personal-use tool: it runs models on your own ChatGPT subscription
  quota (Codex OAuth) and offers no free-API path. Please make sure your usage
  complies with OpenAI's terms of service.

## License

AGPL-3.0.
