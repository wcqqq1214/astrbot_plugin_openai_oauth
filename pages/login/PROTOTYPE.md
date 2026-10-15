# Plugin View account-center prototype

This is a disposable UI exploration, not the deployed login page. It asks which
layout best communicates the active credential source, login health, quota, and
backup login. All numbers, account states and device authorization are simulated.
It never reads credentials, calls login APIs, or stores state.

Run from the plugin repository:

```sh
python3 pages/login/serve_prototype.py
```

Open `http://127.0.0.1:8769/prototype.html?variant=B`.
The server binds only to loopback and serves only the login asset directory.
The existing `index.html`, `app.js`, and `style.css` remain the production entry.
The prototype is adjacent to that entry so it can be reviewed without changing
an authenticated dashboard or running a real authorization flow.

## Layouts

- **A / split overview**: source and login status on the left, two quota windows on
  the right, a separate backup login row below. Alternative exploration.
- **B / compact list**: a dense account row with inline quota bars, followed by the
  backup row. **Selected by the user; default layout.** Useful in a small panel.
- **C / quota first**: a large five-hour ring with the weekly quota underneath,
  then backup login. Best if users mostly check remaining quota.

Use the floating arrows or left/right keys to switch. The selector demonstrates
ready, low quota, cooldown, signed out, backup active, quota error, and no windows.
`?state=cooling` and `?theme=dark` can be shared with `?variant=B` or `C`.
Authorization is an in-memory dialog with an unmistakable `DEMO-ONLY` code.
The page's expandable state section exposes the relevant mock state.

## Handoff for Opus 5.5

Start from `prototype.html`, `prototype.css`, and `prototype.js` in this directory.
Refine layout B, selected by the user. Preserve its compact account and quota rows.
These are plain HTML/CSS/JavaScript with no framework or third-party assets.
The host bar is contextual scaffolding: remove it when embedding the chosen
layout in the actual AstrBot Plugin View. Do not ship the scenario switcher,
mock data, fake refresh, or simulated authorization handlers.

The production integration points already live in `app.js`:

| UI data/action    | Existing bridge route / field                                                                              |
| ----------------- | ---------------------------------------------------------------------------------------------------------- |
| Account status    | `account/status`: `status`, `credential_source`, cooldown fields                                           |
| Active source     | `credential_source`: `local_codex` or `plugin`                                                             |
| Quota windows     | `account/usage`: `usage.windows[]` with `used_percent`, `label_seconds`, `reset_at`, `reset_after_seconds` |
| Login             | `device/start`, `device/poll`, `device/cancel`                                                             |
| UI language/theme | `AstrBotPluginPage.ready()` and dashboard theme context                                                    |

Keep the existing device-session ownership, retry, cancellation and copy logic.
Render remaining quota as `clamp(100 - used_percent, 0, 100)`. Missing/invalid
values must show unavailable, never 100% or zero. Preserve arbitrary windows;
the prototype's 5-hour/week pair is an example, not an API guarantee.

The current backend does **not** expose whether an unused backup account exists,
account email, subscription plan, or the configured follow mode in its status
response. The prototype's saved/unsaved backup badge is simulated. Either add a
safe boolean/status field for backup availability or omit that badge in the real
UI. Do not infer backup availability or the follow preference from the active
source alone. No UI needs raw tokens, account IDs, or filesystem paths.

Keep login health separate from quota lookup errors. A failed quota request must
not label a logged-in user as signed out. A quota limit must not silently select
another account. Saving a backup login must explain that local Codex retains
priority when enabled. Switching credentials while quota loads must discard the
previous account's stale result. Preserve Chinese/English support and theme
integration when implementing the real page.

## Plan-aware quota presentation (selected revision)

The default fixture is `state=pro`: a confirmed Pro plan with no five-hour limit,
a single weekly progress bar and a quiet policy note. There is no invented 100%
or infinity gauge. `state=weekly_only` demonstrates an absent five-hour window
without a known plan/policy; it must not claim that this means unlimited usage.
`state=weekly_cooling` demonstrates weekly exhaustion independently of login.
All three layouts support a weekly-only response. The other scenarios remain.

Production must render actual `usage.windows[]`, never assume two entries or
infer a window's duration from its array index. No window, a failed request,
and an explicitly inapplicable limit are distinct states. A policy note needs
confirmed plan and applicable policy information; current status APIs do not
provide that evidence. Until available, show only returned windows and neutral
missing-data text. Do not hardcode every Pro plan as permanently unlimited.

As verified on 2026-10-15, [OpenAI's current usage guidance](https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex)
states that Pro 100, Pro 200 and Pro 500 currently have no five-hour limit in Work
and Codex. They still have an included allowance. This is a time-sensitive policy,
not proof that an arbitrary missing API field means there is no limit.

## Production implementation

Layout B is now implemented in `index.html`, `style.css`, and `app.js` and deployed
to local AstrBot. The prototype assets remain an isolated design reference.
Production uses safe `account/status` metadata (`backup_status`,
`follow_local_codex`, opaque `account_revision`), and `account/usage` now returns
`account` plus normalized `plan_type`. Responses from an account that changed
while quota was loading are discarded and retried once. The page displays the
actual returned durations, including Pro weekly-only primary windows. Its policy
note describes the observed response rather than promising unlimited usage.
