# Provider controls and routing API

Reference for the single-source config layout, WebUI API endpoints, enable/disable behavior, and automatic fallback routing in `astrbot_plugin_openai_oauth`.

All endpoints are mounted under `/astrbot_plugin_openai_oauth/` using AstrBot's authenticated, same-origin dashboard bridge (API-key sessions are rejected). They never accept or return raw OAuth credentials, and all responses set `Cache-Control: no-store`.

Endpoints:

- `POST /astrbot_plugin_openai_oauth/providers/list`
- `POST /astrbot_plugin_openai_oauth/providers/update`
- `POST /astrbot_plugin_openai_oauth/providers/delete`
- `POST /astrbot_plugin_openai_oauth/routing/update`
- `POST /astrbot_plugin_openai_oauth/account/status`
- `POST /astrbot_plugin_openai_oauth/account/usage`
- `POST /astrbot_plugin_openai_oauth/device/start`
- `POST /astrbot_plugin_openai_oauth/device/poll`
- `POST /astrbot_plugin_openai_oauth/device/cancel`

## Single AstrBot source and account selection

### Storage and sealing

AstrBot stores a single provider source whose ID and type are both `OpenAI Subscribe`, marked with `oauth_gateway: true`. Account state lives inside that source in `data/cmd_config.json` (since AstrBot strips unknown top-level keys on startup):

- `oauth_accounts`: independent account records (`Local Codex` and `device_oauth` accounts).
- `oauth_routing`: holds `default_account_id` and a legacy `models` map (`model_id -> account_id`).
- Gateway `key` stays empty; per-request credentials resolve from the chosen account immediately before dispatch.

Subscription models also expose `oauth_account_id` in AstrBot's model editor (`""` follows default; an account ID pins the model). When present, `oauth_account_id` overrides `oauth_routing.models`; the routing API reads both and keeps `oauth_account_id` synchronized on writes. Both the model-editor selector and default-account action are hidden when fewer than two accounts exist.

Each device account's `key` is sealed at rest as an `enc:v1:` Fernet token using `credential.key` in the plugin data directory (or `OPENAI_OAUTH_CREDENTIAL_KEY_FILE`). Plaintext credentials from older versions are sealed once at startup.

### Migration and source guard

On first consolidation, legacy `OpenAI Subscribe` sources merge into the gateway: model IDs stay intact, `provider_source_id` rewrites to `OpenAI Subscribe`, former account IDs become preferences, and inherited `timeout` / `custom_extra_body` values are copied onto models unless already overridden. Migration is idempotent and rolls back on save failure. Once consolidated, later upgrades leave saved model and gateway settings untouched (current bindings are mutable and do not trigger inference-setting backfills; any legacy `oauth_routing.inference_settings_migrated` marker is ignored).

Plugin initialization or reload also reloads existing subscription model instances via AstrBot's provider manager so stale credential readers do not survive migration.

The plugin guards `ProviderConfigService.upsert_provider_source` for `OpenAI Subscribe`:

- Preserves `oauth_gateway`, `oauth_accounts`, `oauth_routing`, and empty `key` across full-snapshot Dashboard saves while accepting editable fields (e.g. `proxy`), serialized against account edits and in-flight token refreshes.
- Rejects renaming `OpenAI Subscribe`, changing its adapter type, saving stale pre-migration tabs, or adding extra subscription sources. Migration repairs references to gateways renamed by earlier versions.
- Replaces cleanly without stacking on reload and unhooks on unload; non-subscription sources pass through untouched.

### Routing API

`POST providers/list` returns `{ "providers": [...], "routing": {...} }` (keeping historical `providers` / `source_id` names for accounts):

```json
{
  "default_account_id": "OpenAI Subscribe",
  "models": [{"id": "my-model", "account_id": null}]
}
```

`POST routing/update`:

- Set default: `{"account_id": "<account-id>"}` (`null` is rejected).
- Pin model: `{"model_id": "<model-id>", "account_id": "<account-id>"}`.
- Follow default: `{"model_id": "<model-id>", "account_id": null}`.

Success returns HTTP 200 `{ "status": "success", "routing": {...} }`. Invalid payloads return HTTP 400 without changing config. Error responses always use `{ "status": "error", "message": "<code>" }` (translated by `pages/providers/strings.js`).

Selection changes take effect immediately on persistence without reloading AstrBot and are read dynamically on every request, without enabling disabled accounts or changing routing modes. An account cannot be deleted while set as default or bound to a model (`Local Codex` can never be deleted).

## Enable / disable

Account objects returned by `providers/list`, `providers/update`, and `account/status` include `enabled: boolean`, independent of health `status` (`ready`, `cooling`, `not_logged_in`, `reauth_required`, `refreshing`, `degraded`, `invalid`).

`POST providers/update` accepts partial updates (`source_id` plus at least one of `name`, `enabled`, `routing_mode`):

```json
{"source_id": "OpenAI Subscribe", "enabled": false}
```

`enabled` must be a JSON boolean (`null`, numbers, strings, and unknown keys return HTTP 400); `name` requires 1–80 non-whitespace characters. HTTP 200 response:

```json
{
  "status": "success",
  "provider": {
    "id": "OpenAI Subscribe",
    "name": "Local Codex",
    "enabled": false,
    "routing_mode": "fixed",
    "credential_mode": "local_codex",
    "credential_source": "local_codex",
    "status": "ready"
  }
}
```

Key rules:

- Disabling keeps credentials, bindings, settings/reauth access, and cooldowns intact (`Local Codex` stays first and cannot be deleted; re-enabling does not clear cooldowns or reauth state).
- In-flight attempts finish; new attempts (including retries) re-check `enabled`.
- All accounts may be disabled (none are implicitly re-enabled), and legacy records missing `enable` default to `true`.
- Persistence failures roll back (dispatch stays on the committed policy while saving), changes apply immediately without restarting the provider manager, and duplicate `enabled` writes are idempotent.
- Independent of AstrBot's per-model enable switch.

## Opt-in automatic fallback

Each account exposes `routing_mode: "fixed" | "auto"` (persisted internally as `oauth_routing_mode`, defaulting to `"fixed"`). The mode belongs to the model's preferred account and does not chain recursively across candidates. Update it via `POST providers/update` (`{"source_id": "...", "routing_mode": "auto"}`).

| Mode | Dispatch |
| --- | --- |
| `fixed` | Uses only the bound account (or default if unbound); fails explicitly if unavailable. |
| `auto` | Tries the bound account first, then remaining enabled, available accounts in `providers/list` order (`Local Codex` first, then saved order). |

Candidate order is resolved at request start, and `enabled` + health are re-checked before every HTTP attempt. There is no round-robin, sticky session, or nested fallback: the next request (including the next tool-loop turn) starts with the preferred account again.

### Failure handling

| Condition | Backend behavior |
| --- | --- |
| Disabled, logged out, reauth required, invalid credentials, or cooling | Skipped in `auto` mode; fails immediately in `fixed` mode. |
| Duplicate account in this request | Skipped (matched by `account_id`, or token identity if absent). |
| Subscription quota exhausted | Marks shared cooldown on that account, then tries next account. |
| Auth rejected (401) | Refreshes once within budget; on second failure/rejection, marks `reauth_required` and tries next account. |
| Network / temporary upstream error | Bounded same-account retries, then tries next account. |
| Ordinary rate limit (non-quota 429) | Tries next account without marking quota cooldown. |
| Invalid request, unsupported model, unclassified error | Fails immediately; never changes model or rotates accounts. |
| Any output already emitted (including reasoning/tool output) | Never replays; emits final `role="err"` item so AstrBot's outer fallback will not re-run. |
| Cancelled | Propagates cancellation with no fallback. |

### Transport, headers, and budgets

Fallback keeps the same model and body while isolating per-account credentials, `chatgpt-account-id`, `proxy`, `originator`, `User-Agent`, and pooled HTTP transports (replaced when account or proxy changes so cookies never cross accounts). Preferred-account custom headers do not carry into fallback accounts: inherited headers re-read for the chosen account, gateway headers apply across accounts, and auth/identity headers come from the active snapshot.

In `auto` mode, `request_max_retries` (AstrBot default `5`) caps **all inference HTTP attempts** across the request (max 2 attempts per temporary-retry batch; token refreshes do not reset it). Control-plane calls sit outside that counter under a 120s startup deadline, which clears once a response stream opens (allowing long reasoning before the first delta); if a stream fails pre-output, the next candidate gets a fresh 120s window. `fixed` mode keeps its normal per-source retry policy.

When `auto` mode exhausts candidates, `RoutingExhaustedError` reports source IDs and safe reason codes (`disabled`, `cooling`, `reauth_required`, `not_logged_in`, `invalid_credentials`, `duplicate_account`, `temporary`, `rate_limit`, `attempt_limit`), separating `attempt_limit` / `startup_timeout` from `unavailable` without leaking tokens or upstream bodies.

AstrBot's separate model fallback list is untouched and may still run after a pre-output failure. `/usage` always queries the model's bound account. `Local Codex` cooldown/reauth flags stay in memory; device-account cooldowns persist with credentials.

## Client & testing notes

- Lock controls while saving, treat the returned `provider` object as authoritative, and refetch `providers/list` after an ambiguous network failure.
- Verified offline by `tests/provider_routing_test.py` (real OpenAI SDK parsing against fake HTTP transports) inside `tests/run_tests.py`.
