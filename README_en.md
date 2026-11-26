<h1 align="center">OpenAI Subscription Sign-in</h1>

<p align="center">
  <a href="https://github.com/wcqqq1214/astrbot_plugin_openai_oauth/releases/tag/v2.5.1"><img src="https://img.shields.io/badge/version-2.5.1-4b8bbe?style=flat-square" alt="Version 2.5.1"></a>
  <a href="https://github.com/AstrBotDevs/AstrBot"><img src="https://img.shields.io/badge/AstrBot-%E2%89%A54.27.1-4b8bbe?style=flat-square" alt="AstrBot ≥ 4.27.1"></a>
  <img src="https://img.shields.io/badge/Python-%E2%89%A53.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python ≥ 3.12">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square" alt="License: AGPL-3.0"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/wcqqq1214/astrbot_plugin_openai_oauth/main/logo.webp" alt="OpenAI Subscribe" width="240">
</p>

<p align="center">
  <a href="README.md">简体中文</a>
</p>

Chat in AstrBot with your ChatGPT account, no separate API key needed. Usage draws from your subscription's Codex allowance rather than an OpenAI API balance. Requires **AstrBot 4.27.1+** and a ChatGPT account with Codex access.

## Sign in, then choose a model

### Option 1: Use an existing local Codex login

If Codex CLI and AstrBot run on the same machine, the plugin picks up your local Codex login automatically. Select **OpenAI Subscribe** in AstrBot's model settings and add a model; whenever you switch accounts in Codex locally, the next request follows along.

Not detected? See [Common questions](#common-questions) below or sign in with a device code instead.

### Option 2: Sign in with a device code (or add more accounts)

First, open ChatGPT **Settings → Security and login** and turn on **Enable device code authorization for Codex**:

<details>
<summary>Show where to find the switch</summary>

![Enable Codex device-code authorization](https://raw.githubusercontent.com/wcqqq1214/astrbot_plugin_openai_oauth/main/images/enable-device-code-auth-codex.webp)

</details>

1. On the plugin's detail page, open **Plugin Views → providers** and click **Add account → Get device code** (leave the name blank to use the account's ChatGPT email).
2. Copy the verification link into a browser, sign in to ChatGPT, and enter the code.
3. Once you see **Account saved**, add models under **OpenAI Subscribe** in AstrBot's model settings.

Each account is stored independently without overwriting existing logins. **Never share your device code; enter it only on OpenAI's official verification page.**

## Managing accounts and checking allowances

The plugin creates a single AstrBot provider source with the fixed ID `OpenAI Subscribe`. Simply choose it when adding models (it cannot be renamed and won't appear under **Add Provider**).

Manage all accounts in **Plugin Views → providers**:

- **Check allowances**: Click any account row to expand its usage windows (multiple rows can stay open, refreshing every 30 seconds while visible). Missing windows do not mean unlimited usage.
- **Edit or disable**: Click the gear icon to rename an account, change its routing mode, or reauthorize/remove device-code accounts. The right-side toggle controls whether new requests use that account; turning it off preserves credentials and lets active requests finish.
- **Default account & model bindings**: With multiple accounts configured, use an account's gear menu to **Set as default account** (takes effect immediately), or open **OpenAI Subscribe → configured model → Edit → Model account** in AstrBot to pin a model to a specific account or keep **Follow default** (new models follow the default; existing ones retain their bindings).

![Account allowance panels](https://raw.githubusercontent.com/wcqqq1214/astrbot_plugin_openai_oauth/main/images/providers-overview-en.webp)

*Account names and allowance values shown above are examples. The page follows AstrBot's language setting (Chinese, English, Russian, and Japanese).*

Before removing an account, switch the default account elsewhere and clear any model bindings pointing to it. Local Codex is managed on the host and cannot be deleted here.

### Automatic fallback across accounts

Open an account's gear menu, switch routing to **Automatic fallback**, and click **Save**:

| Mode | Behavior |
| --- | --- |
| Fixed account (default) | Uses only the bound account and returns an error if unavailable. |
| Automatic fallback | Tries the bound account first, then falls back through other enabled, available accounts in list order. |

Fallback switches accounts only (never the model) and triggers only on exhausted allowances, expired logins, or transient network failures; invalid request parameters still fail immediately. Once a reply starts streaming text or tool calls, that turn won't switch and restart, and the next request returns to trying the preferred account first.

<details>
<summary>Show the settings dialog</summary>

![Choose automatic fallback in account settings](https://raw.githubusercontent.com/wcqqq1214/astrbot_plugin_openai_oauth/main/images/provider-settings-en.webp)

*Automatic fallback is selected in this example; click Save to apply it.*

</details>

## GPT Image generation

Turn on `image_enabled` in the plugin settings, then describe an image in an OpenAI Subscribe chat, such as *"Draw a portrait poster of a cat holding an umbrella in the rain, with space at the top."* The model calls `codex_generate_image` to create and send the PNG. Specify orientation, aspect ratio, and composition in your prompt; sizing defaults to `auto` and Codex picks the resolution.

To skip follow-up questions from the model, use `/draw <prompt>` directly. It reuses whichever account handled the most recent successful OpenAI Subscribe chat in that conversation (after a plugin reload, send one normal chat message before using `/draw` again).

Leave `image_account` blank to follow whichever account answered the chat, or set a source ID to allow drawing only on turns handled by that source. Image generation never falls back across accounts.

## Native web search

Turn on **Native web search** under **Plugin Views → providers → Native web search** (off by default). When enabled, requests include Codex's native `web_search` tool (`external_web_access: true`) without requiring an extra API key or third-party search service, and it coexists with AstrBot function tools.

When the model searches the web and returns citations, the plugin appends a deduplicated list of source links to the end of the reply; replies without search citations are left unchanged.

## Commands and reasoning effort

`/openai_login` and `/effort` require administrator permissions. Command replies default to Chinese; set `chat_language` in plugin settings to switch to English, Russian, or Japanese.

| Command | What it does |
| --- | --- |
| `/usage` | Shows the allowance for the account bound to your current model (even if the last reply fell back to another account). |
| `/openai_login` | Starts a device-code sign-in in a private chat with the bot, named after its ChatGPT email. |
| `/openai_login cancel` | Cancels a pending device-code sign-in in the current private chat. |
| `/effort` | Displays the current conversation's reasoning effort and the levels supported by the model. |
| `/effort high` | Overrides this conversation's reasoning effort starting on the next request. |
| `/effort default` | Clears the conversation override and restores the model default. |

Reasoning effort is optional (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, depending on the model). To set a model default, enter a value under **Custom request body parameters → Reasoning Effort** in its settings and save; `/effort` affects only the current conversation.

<details>
<summary>Show where to set the model default</summary>

![Set Reasoning Effort](https://raw.githubusercontent.com/wcqqq1214/astrbot_plugin_openai_oauth/main/images/reasoning-effort-preset-en.webp)

</details>

## Common questions

**Local Codex login not detected?**
The plugin reads `$CODEX_HOME/auth.json`, or `~/.codex/auth.json` if unset. Set a full file path in `codex_auth_path` and reload the plugin to override it. AstrBot needs read access to the file and write access to its parent directory for automatic token refreshes. Browser-only or keychain-only logins without an `auth.json` file need device-code sign-in instead.

**Running AstrBot in Docker or on a remote server?**
Use the plugin's device-code login. The server does not need Node.js, npm or the Codex CLI. At startup and every six hours, the plugin checks npm for the stable Codex CLI version in the background. By default, model discovery and chat use the highest of the built-in version, the local Codex catalog version and the stable version retrieved from npm. If npm is unreachable, requests continue with the versions already available.

If the server already runs the Codex CLI, you can also reuse its login. For Docker, mount the entire Codex credentials directory and set `codex_auth_path` to the path of `auth.json` inside the container. The plugin needs the directory to replace that file atomically when refreshing credentials.

**Need a proxy?**
Set `proxy` on the **OpenAI Subscribe** source, or pass `HTTP_PROXY` and `HTTPS_PROXY` to the AstrBot process/container (per-account proxies migrated from older versions are preserved and take precedence). `unsupported_country_region_territory` means OpenAI is rejecting your exit IP region or account eligibility, which the plugin cannot bypass.

**Upgrading from an older version?**
Migration is automatic: older separate sources consolidate under **OpenAI Subscribe** while preserving your model IDs, account preferences, and logins.

## Security and disclaimer

- **Credentials and backups**: Local sign-in uses Codex's `auth.json`. Device-code credentials are stored encrypted in `data/cmd_config.json`, using the key in `data/plugin_data/astrbot_plugin_openai_oauth/credential.key` (override with `OPENAI_OAUTH_CREDENTIAL_KEY_FILE`). Keep that key with any backup you restore; losing it or downgrading to a version without encryption requires signing in again.
- **Dashboard access**: Use HTTPS, a VPN, or an SSH tunnel whenever exposing the AstrBot Dashboard to the internet.
- **Terms and stability**: Use your own account and follow OpenAI's Terms of Service. This is an unofficial integration using Codex client identifiers to reach ChatGPT backend endpoints outside public API compatibility guarantees; upstream changes may interrupt or limit access at any time.

## Development and license

See the [development guide](https://github.com/wcqqq1214/astrbot_plugin_openai_oauth/blob/main/docs/development.md) for testing and release workflows, and the [API guide](https://github.com/wcqqq1214/astrbot_plugin_openai_oauth/blob/main/docs/provider-routing-api.md) for routing rules and WebUI endpoints.

Licensed under [AGPL-3.0](LICENSE).
