<h1 align="center">OpenAI 订阅登录</h1>

<p align="center">
  <a href="https://github.com/wcqqq1214/astrbot_plugin_openai_oauth/releases/tag/v1.1.0"><img src="https://img.shields.io/badge/version-1.1.0-4b8bbe?style=flat-square" alt="Version 1.1.0"></a>
  <a href="https://github.com/AstrBotDevs/AstrBot"><img src="https://img.shields.io/badge/AstrBot-%E2%89%A54.27.1-4b8bbe?style=flat-square" alt="AstrBot ≥ 4.27.1"></a>
  <img src="https://img.shields.io/badge/Python-%E2%89%A53.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python ≥ 3.12">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square" alt="License: AGPL-3.0"></a>
</p>

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
2. Log in with your ChatGPT account. On the WebUI plugin detail page, open the
   native AstrBot **Plugin Page** named `login` and click **Start login**. Copy
   the OpenAI verification URL shown there, enter the device code, and approve.
   The page calls the plugin through the Dashboard bridge; do not open a raw
   `/api/v1/plugins/extensions/...` URL. The iframe never reads the Dashboard
   JWT, cookies, or OAuth tokens. After login succeeds, the server automatically
   adds a provider of type **OpenAI Subscribe** in the WebUI model configuration
   and writes the credentials into the provider's `key` field.

   The page shows a redacted account state (not signed in, ready, refreshing,
   reauthorization required, quota cooling, or temporarily degraded). You can
   explicitly select **Check quota** and can **Cancel login** while a device code
   is pending. Loading the page only reads local status; it does not query quota
   automatically. One provider source represents one ChatGPT account. When that
   subscription reaches quota, the plugin reports its cooling state and known
   reset time instead of automatically rotating to another account.

   If the WebUI is unavailable, send `/openai_login` in an administrator's
   **private/direct chat**. The ADMIN-only command promptly sends the OpenAI
   verification URL and one-time device code, then polls, exchanges, and saves
   credentials on the AstrBot server. Tokens are never sent to chat, and group
   chats do not start the flow.

   HTTPS, a VPN, or an SSH tunnel is strongly recommended for the entire public
   Dashboard because plain HTTP exposes the Dashboard session. HTTPS is not a
   plugin-level requirement for this device-code flow: once AstrBot has
   authenticated the Dashboard user, a public-IP HTTP Plugin Page can call
   `device/start` and `device/poll`; the page shows a prominent risk warning.
   Prefer securing the whole Dashboard rather than relying on plain HTTP.

   > Device-code login must be enabled in your ChatGPT security settings
   > (“Enable device code authentication for Codex”); the page reports it if
   > not.

   ![Enable Codex device-code authorization in ChatGPT settings](docs/images/enable-device-code-auth-codex.png)

   *Figure: Turn on **Enable device code authorization for Codex** under ChatGPT's **Security and login** settings.*

3. Pick a model and enable the provider.

### Optional reasoning-effort setting

In the WebUI model configuration, edit the specific model under
`OpenAI Subscribe`, find `custom_extra_body`, and add a new entry in the
visual editor:

- Key: `reasoning_effort`
- Value type: `string`
- Value: `low`, `medium`, `high`, `xhigh`, or `max`

Visual editor examples:

![Adding the reasoning_effort key](docs/images/reasoning-effort-add-key.png)

*Figure 1: Add the `reasoning_effort` key and set its value type to `string`.*

![Entering the reasoning_effort value](docs/images/reasoning-effort-set-value.png)

*Figure 2: Enter an API parameter value, such as `max`.*

If you edit the underlying JSON directly, the equivalent configuration is:

```json
{
  "reasoning_effort": "max"
}
```

The plugin converts this to the Codex Responses API shape
`{"reasoning": {"effort": "max"}}`. For the GPT-5.6 family
(`gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol`), the following levels have
been verified to return successfully:

| WebUI label | API `reasoning_effort` value |
| --- | --- |
| Light | `low` |
| Medium | `medium` |
| High | `high` |
| Extra High | `xhigh` |
| Max | `max` |

Enter the value from the right column as the API parameter; do not enter the
WebUI label directly.

## Network and credential flow

- The plugin only talks to OpenAI-owned hosts: `auth.openai.com` (OAuth
  device login, token refresh) and `chatgpt.com` (`backend-api/codex` for
  inference and the model catalog, `backend-api/wham/usage` for quota). The
  access token appears only in requests to these two hosts and is never sent
  anywhere else.
- `proxy` is empty by default (direct connection); configure it only when your
  network cannot reach OpenAI directly. Device login, token refresh, model
  discovery, quota requests, and inference then use that proxy. For cloud or
  Docker deployments that use an authorized outbound proxy, you must set both
  standard `HTTP_PROXY` and `HTTPS_PROXY` environment variables on the
  **AstrBot container** and leave the plugin's own `proxy` setting empty; a
  non-empty plugin proxy takes precedence over the environment variables.
  OpenAI endpoints use HTTPS, so `HTTP_PROXY` alone does not proxy those
  requests. This plugin does not provide proxy nodes, subscriptions, routing
  rules, or traffic-shaping tutorials. `originator` defaults to `codex_cli_rs`,
  matching the official Codex CLI (Cloudflare allows first-party clients by this
  header); it is configurable so it can follow whatever value OpenAI accepts
  next, without a plugin release.
- A login response with `unsupported_country_region_territory` is OpenAI's
  determination of deployment-egress availability, not a plugin error. Use a
  deployment network that meets OpenAI service-availability and account
  requirements; the plugin does not and cannot bypass such restrictions.
- The native Plugin Page calls `device/start`, `device/poll`, `device/cancel`,
  `account/status`, and `account/usage` through AstrBot's authenticated
  Dashboard bridge. These APIs accept WebUI user sessions, not general API keys.
  Device sessions are user-bound, bounded, and cleaned up after cancellation,
  completion, or expiry. OAuth credentials are exchanged and saved only on the
  server and are never returned to the browser; status responses do not expose
  access tokens, refresh tokens, or complete account IDs. The ADMIN-only private
  `/openai_login` fallback uses the same server-side flow. Stored credentials
  (access_token / refresh_token) live in the provider's `key` field, persisted
  as plaintext in the AstrBot config (`data/cmd_config.json`); restrict read
  access to that file and its backups.
- This is a native, single-account OpenAI OAuth integration. It does not
  download, start, or manage CLIProxyAPI; it does not expose a local
  OpenAI-compatible gateway or automatically rotate accounts.
- This is a personal-use tool: it runs models on your own ChatGPT subscription
  quota (Codex OAuth) and offers no free-API path. Please make sure your usage
  complies with OpenAI's terms of service.

## License

AGPL-3.0.
