# Provider controls and routing API

Frontend handoff for the Plugin View. All paths below are relative to the
existing authenticated plugin API base. Use the same authenticated POST helper
as the current `providers/list` / `providers/update` calls. Never call them with
OAuth credentials. Responses use `Cache-Control: no-store`.

Registered paths are `/astrbot_plugin_openai_oauth/providers/list`,
`/astrbot_plugin_openai_oauth/providers/update`, and the existing account routes.
The dashboard's Plugin View client handles the surrounding extension proxy.

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
settings. Stored keys are `enable` and `oauth_routing_mode` in AstrBot's source
configuration; the frontend should use the API names above.

| Mode | Dispatch |
| --- | --- |
| `fixed` | Use only the model's bound source. Disabled/unavailable sources fail clearly. |
| `auto` | Try the bound source first, then other sources in `providers/list` order (local first, remaining sources in saved order). |

The candidate order is sampled at request start. Enable and health are checked
again immediately before every HTTP inference attempt. There is no global active
account, round-robin, sticky session or nested fallback. A successful fallback
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
does not inherit the preferred source's custom headers. Existing model headers
are retained on the preferred source except authentication/identity headers,
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
- Existing rename-only clients continue to work. No new dependencies, frontend
  edits, live configuration changes or plugin reload are needed for this handoff.

Verification uses `tests/provider_routing_test.py` with real SDK parsing and fake
HTTP transports, plus the existing integration regression suite. No real account
inference or login is required by the tests.
