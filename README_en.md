<h1 align="center">OpenAI Subscription Sign-in</h1>

<p align="center">
  <a href="https://github.com/wcqqq1214/astrbot_plugin_openai_oauth/releases/tag/v1.2.0"><img src="https://img.shields.io/badge/version-1.2.0-4b8bbe?style=flat-square" alt="Version 1.2.0"></a>
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

This plugin connects your ChatGPT account to AstrBot. After you sign in,
AstrBot gets an `OpenAI Subscribe` model source. Choose a model from that
source to use your ChatGPT/Codex quota—no separate OpenAI API key is needed.

In short: usage counts against the Codex quota available to your ChatGPT
account, not your prepaid OpenAI API balance.

## Before you start

- Use AstrBot `4.27.1` or later.
- You need a ChatGPT account that can use Codex.
- If your Dashboard is publicly reachable, use HTTPS, a VPN, or an SSH tunnel.
  Device-code sign-in also works over plain HTTP, but the Dashboard session can
  be intercepted, so it is not recommended.
- In ChatGPT, open **Settings → Security and login** and turn on
  **Enable device code authorization for Codex**.

![Enable Codex device-code authorization in ChatGPT settings](docs/images/enable-device-code-auth-codex.png)

*Figure: The switch is on ChatGPT's **Security and login** page. Its label in
the screenshot is **Enable device code authorization for Codex**.*

> Treat a device code like a password: enter it only on OpenAI's verification
> page, and never share it with anyone.

## Sign in in five steps

1. Install the plugin from the AstrBot plugin marketplace. For a manual
   installation, place the project in `data/plugins/`.
2. Open this plugin's detail page and enter its **Plugin Page** (the sign-in
   page). Click **Start login**.
3. The page shows an OpenAI verification URL and a device code. Open the URL,
   sign in to ChatGPT, enter the code, and approve the request.
4. Return to AstrBot and wait for the “Login succeeded” message. Credentials are
   stored only on the AstrBot server; they are not shown in the browser or chat.
5. Open AstrBot's model configuration. Create or choose a model that uses the
   `OpenAI Subscribe` source, enable it, and you are ready to go.

The sign-in page can also show account status and quota. You can select
**Cancel login** while a device code is still waiting for approval. After you
sign in, `/usage` in chat also shows your quota.

If the WebUI is unavailable, an administrator can send this in a **private
chat** with the bot:

```text
/openai_login
```

The bot replies with the verification URL and a one-time device code. Complete
the sign-in in that private chat; the flow will not start in group chats.

## Want to set the reasoning effort? (Optional)

You do not need to configure this for normal use—the model uses its default
behavior. Only follow these steps if you want to choose the reasoning effort
yourself:

1. Open model configuration and edit the model that uses `OpenAI Subscribe`.
2. Find **Custom request body parameters (`custom_extra_body`)**.
3. Enter `reasoning_effort` as the key, choose `string` as the value type, and
   click **+ Add**.
4. Enter the desired value in the new row, then click **Confirm** in the lower
   right corner to save.

![Adding the reasoning_effort key](docs/images/reasoning-effort-add-key.png)

*Figure 1: Enter `reasoning_effort`, choose `string` as its value type, then
click **+ Add**.*

![Entering the reasoning_effort value](docs/images/reasoning-effort-set-value.png)

*Figure 2: After adding the key, enter a value such as `max`, then click
**Confirm** in the lower right corner.*

Use one of these five lowercase values:

| Common WebUI label | Value to enter |
| --- | --- |
| Light | `low` |
| Medium | `medium` |
| High | `high` |
| Extra High | `xhigh` |
| Max | `max` |

Do not enter the label from the left column. The plugin converts the setting to
the format Codex expects. If you prefer editing JSON directly, use:

```json
{
  "reasoning_effort": "max"
}
```

### Set reasoning effort for only the current session

Administrators can use these commands in the current private or group-chat
session:

```text
/effort
/effort low
/effort medium
/effort high
/effort xhigh
/effort max
/effort default
```

`/effort` shows the current setting. A chosen value takes effect on the next
request. `/effort default` removes the session override and restores the model
default. It does not change other sessions or the model's global configuration.

## Network, quota, and security

- With the default direct connection, the plugin talks only to OpenAI's
  `auth.openai.com` and `chatgpt.com` hosts for sign-in, token refresh, model
  discovery, quota checks, and inference.
- Configure the plugin's `proxy` only when the network cannot reach OpenAI
  directly. For an authorized outbound proxy in Docker or on a cloud server,
  set both `HTTP_PROXY` and `HTTPS_PROXY` in the **AstrBot container** and leave
  the plugin's own `proxy` empty. A non-empty plugin `proxy` takes precedence.
- Credentials are never returned to the browser or sent to chat, but they are
  stored in plaintext in AstrBot's `data/cmd_config.json`. Limit read access to
  that file and its backups.
- One `OpenAI Subscribe` model source represents one ChatGPT account. When the
  quota is exhausted, the page shows the cooldown and reset time; the plugin
  does not rotate accounts automatically.
- If you see `unsupported_country_region_territory`, OpenAI does not accept the
  deployment egress network or account conditions. The plugin cannot bypass
  that restriction.

Use your own account and make sure your use complies with OpenAI's terms of
service.

## License

AGPL-3.0.
