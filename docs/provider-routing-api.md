# Provider controls and routing API

Frontend handoff for the Plugin View. All paths below are relative to the
existing authenticated plugin API base. Use the same authenticated POST helper
as the current `providers/list` / `providers/update` calls. Never call them with
OAuth credentials. Responses use `Cache-Control: no-store`.

Registered paths are `/astrbot_plugin_openai_oauth/providers/list`,
`/astrbot_plugin_openai_oauth/providers/update`, and the existing account routes.
The dashboard's Plugin View client handles the surrounding extension proxy.

## Single AstrBot source and account selection

AstrBot contains one source with ID/type `OpenAI Subscribe` and `oauth_gateway: true`.
Its `oauth_accounts` array holds the independent account records. `oauth_routing`
holds `default_account_id` and a `models` map from model ID to preferred account ID.
These fields stay inside the source in `data/cmd_config.json`: AstrBot removes
unknown top-level config keys on startup. The gateway's `key` remains empty;
credentials are resolved from the selected account immediately before dispatch.

Migration preserves model IDs, rewrites their `provider_source_id` to the gateway,
and stores their former account in the preference map. Existing profile selections
therefore remain valid. Other providers are untouched. Repeating migration is a
no-op; configuration-save failure rolls back the proposed migration.

During first-time consolidation, a model's direct `provider_source_id` identifies
its original source. Migration copies inherited `timeout` and `custom_extra_body`
from that source, preserving explicit model overrides.

Already consolidated gateways have no immutable record of each model's original
source. Current account bindings can change and also include newly created models,
so they are never used to recover inference settings. These upgrades preserve saved
model and gateway settings, including absent keys, defaults and empty objects.
Missing values require a verified original configuration before restoration.
Any `oauth_routing.inference_settings_migrated` marker left by an earlier version
is retained for compatibility but does not authorize recovery. Previously saved
values are not automatically reverted because they may reflect later user edits.

`providers/list` returns `{ "providers": [...], "routing": {...} }`. The historical
`providers` and `source_id` API names now refer to accounts, not separate AstrBot
sources. Neither list nor routing responses contain credentials. Routing shape:

```json
{
  "default_account_id": "OpenAI Subscribe",
  "models": [{"id": "my-model", "account_id": null}]
}
```

`POST routing/update` changes the default with `{"account_id": "account-id"}`.
To pin one model, send `{"model_id": "my-model", "account_id": "account-id"}`;
`account_id: null` for a model means follow the default. A null default is rejected.
Success returns `{ "status": "success", "routing": {...} }`. Invalid IDs, unknown
fields and incorrect types return HTTP 400 without changing the configuration.
The same authenticated, same-origin plugin bridge is required for this endpoint.

Account selection is read on every request, including by already loaded provider
instances. Selection changes do not enable accounts or alter their fixed/auto
policy. The new selection takes effect only after persistence succeeds. Account
removal is blocked while it is the default or explicitly selected by a current
model; choose replacements in the plugin page first. Local Codex cannot be removed.
New model IDs without a preference follow the default. Model IDs and account IDs
remain stable internal identifiers and are not used as extra source labels.

Plugin initialization also reloads existing subscription model instances through
AstrBot's provider manager. Purging plugin modules alone does not replace model
instances retained by AstrBot, so their old credential readers must not survive
the storage migration. Initial startup leaves model loading to AstrBot as usual.

The plugin guards AstrBot's `ProviderConfigService.upsert_provider_source` for its
own gateway. The generic editor submits complete snapshots even for invisible
fields; the guard preserves the current account records and routing while saving
editable settings. It serializes with account edits and in-flight token refreshes.
Other sources pass through unchanged. The guard is replaced without stacking on
reload and removed when the plugin terminates.
The gateway ID is fixed to `OpenAI Subscribe`; attempts to rename it or change
its adapter type are rejected before saving. Stale editors for migrated account
sources and attempts to add additional subscription sources are rejected too.
Migration repairs model references to gateways renamed by earlier versions.

## Enable / disable

`POST providers/list` keeps its `{ "providers": [...] }` envelope. Each provider
now includes `enabled: boolean`. `POST account/status` includes the same field.
It is independent of `status` (ready, cooling, not_logged_in, reauth_required,
refreshing, degraded, invalid). Render the switch from `enabled`, not `status`.

`POST providers/update` accepts a partial update:

```json
{"source_id": "OpenAI Subscribe", "enabled": false}
```

`name` may also be supplied, alone or together with `enabled`. The ID is required;
at least one editable field is required. `enabled` must be an actual JSON boolean;
null, numbers, strings and unknown fields return HTTP 400. Names retain the
existing 1–80 non-whitespace character requirement.

Success (HTTP 200):

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

The provider object also includes existing account metadata when available.
Use the returned object as authoritative. Disable the switch while saving; on
failure retain the previous state and display the existing error response.
After an unknown network outcome, refetch the list. Sending the same desired
value twice is safe; this is not a toggle operation.

- Local Codex may be disabled but remains first and cannot be deleted.
- Disabling preserves credentials, model bindings, login/usage access and cooldown.
- In-flight attempts finish; new attempts (including retries) check enabled again.
- Re-enabling does not clear cooldown or repair authentication.
- All providers may be disabled. The backend never enables one implicitly.
- Missing legacy `enable` values migrate to true; explicit false is preserved.
- Persistence failure rolls back the update; dispatch sees the previous policy
  while the save is pending. No provider-manager restart is needed for the switch.
- A source switch is independent of AstrBot's model-level enable setting. It does
  not enable a disabled model or rewrite its binding.

## Opt-in automatic fallback

Every account object returned by `providers/list`, `providers/update`, and
`account/status` now includes `routing_mode: "fixed" | "auto"`. The setting belongs
to the **preferred source** and applies to models bound to that source. Selecting
a row in the UI remains a management action; it does not select the inference
provider. Changing another candidate's routing mode does not recursively route.

Use the same partial-update endpoint, either alone or with the enable/name fields:

```json
{"source_id": "OpenAI Subscribe", "routing_mode": "auto"}
```

```json
{"source_id": "OpenAI Subscribe", "enabled": true, "routing_mode": "fixed"}
```

Only `fixed` and `auto` are accepted; null, booleans and all other values return
HTTP 400 without changing any field. The success envelope is unchanged. Existing
and newly created providers default to `fixed`; migration preserves explicit
settings. Stored keys are `enable` and `oauth_routing_mode` in each account record; the frontend should use the API names above.

| Mode | Dispatch |
| --- | --- |
| `fixed` | Use only the model's bound source. Disabled/unavailable sources fail clearly. |
| `auto` | Try the bound source first, then other sources in `providers/list` order (local first, remaining sources in saved order). |

The candidate order is sampled at request start. Enable and health are checked
again immediately before every HTTP inference attempt. The default account applies only to models without an explicit preference. There
is no round-robin, sticky session or nested fallback. A successful fallback
does not change the preferred source: a later request retries that preference
when it is eligible again. The next tool-loop invocation is a new request.

### Failure behavior

| Condition | Backend action |
| --- | --- |
| Disabled, no login, reauthorization needed, invalid credentials, quota cooling | Skip in auto mode; explicit failure in fixed mode. |
| Same account already attempted | Skip its duplicate entry for this request. Use account ID, or token identity when no account ID exists. |
| Subscription quota exhausted | Mark cooldown, then try another account. Cooldown is shared across sources with that account, even if one is disabled. |
| Authentication rejected | Refresh once, then try again within the remaining budget. On rejection/failure, mark reauthorization required and try another account. |
| Network / temporary service failure | Bounded same-source retries, then another account. |
| Ordinary rate limit | Try another account; do not mark subscription quota exhausted. |
| Invalid request, unsupported model, other unclassified error | Fail; do not silently change the model or rotate accounts. |
| Any output already emitted, including reasoning/tool output | Never replay. The public stream emits a final `role="err"` response so AstrBot's streaming fallback cannot repeat the request. |
| Cancellation | Propagate cancellation and close transports; no fallback. |

The request body/model remains the same across accounts. Each chosen source uses
its own credentials, account header, proxy, originator and user agent; fallback
does not inherit the preferred source's custom headers. Explicit model headers
are retained on the preferred account; inherited headers are re-read from the
chosen account so switching does not reuse the previous account’s headers. The
shared source headers apply to all accounts, except authentication/identity headers,
which are constructed from the current credential snapshot.

Auto mode shares `request_max_retries` across **all inference HTTP attempts**
(AstrBot default: 5). Each temporary-retry batch uses at most 2 attempts; credential
refresh does not reset the shared budget. Credential and quota control-plane
calls are outside that attempt counter but inside a shared 120-second startup
deadline. Once output starts the startup deadline is removed, and the normal
transport timeout applies. Fixed mode retains its existing retry policy.

When auto mode exhausts candidates, `RoutingExhaustedError` reports source IDs and
safe reason codes (`disabled`, `cooling`, `reauth_required`, `not_logged_in`,
`invalid_credentials`, `duplicate_account`, `temporary`, `rate_limit`, `attempt_limit`). It also
distinguishes `attempt_limit` / `startup_timeout` from general `unavailable`.
These are inference errors, not a new WebUI endpoint. Raw tokens and upstream
error bodies are not included in this aggregate error.

The plugin does not edit AstrBot's separately configured model fallback list.
That outer list may still run after a pre-output plugin failure; its own budgets
are managed by AstrBot. `/usage` continues to show the model's bound source, not a
globally remembered last account. Current local Codex cooldown and reauthorization
markers remain runtime state; device-source cooldown is persisted with credentials.

## Frontend handoff checklist

- Render an enable switch from `enabled` and a separate fixed/auto choice from
  `routing_mode`. Display `status` separately, including when disabled.
- For automatic fallback, show the preference-first ordering above; no reorder
  endpoint or per-request active-provider badge is exposed in this iteration.
- Keep settings editable while disabled; reauthorization must not enable a source.
- Serialize writes for one provider, apply the returned provider object, and
  refetch after ambiguous network failures. Do not send an entire stale account
  object back; only send the fields the user changed.
- Existing rename-only clients continue to work. No new dependencies are needed. Reload the updated plugin once to run migration;
  subsequent account selection changes do not require a reload.

Verification uses `tests/provider_routing_test.py` with real SDK parsing and fake
HTTP transports, plus the existing integration regression suite. No real account
inference or login is required by the tests.
