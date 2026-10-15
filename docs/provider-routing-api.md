# Provider controls and routing API

Frontend handoff for the Plugin View. All paths below are relative to the
existing authenticated plugin API base. Use the same authenticated POST helper
as the current `providers/list` / `providers/update` calls. Never call them with
OAuth credentials. Responses use `Cache-Control: no-store`.

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
