# README screenshots

The provider screenshots were captured on 2026-10-16 from main commit
`1d173430f47c45e2e37745104bded81a4e059aa2`.

- `providers-overview-zh.png` / `providers-overview-en.png`: two independent
  allowance panels expanded, with source settings and enable controls visible.
- `provider-settings-zh.png` / `provider-settings-en.png`: the device-account
  settings dialog with Automatic fallback selected but not saved.

These are browser captures of the unchanged production HTML, CSS, JavaScript,
and icons in `pages/providers/`. A temporary local bridge fixture supplied
sample accounts (`codex@example.com` and `backup@example.com`) and allowance
values. No real credentials, sign-in sessions, or model requests were used.
The README captions identify these values as examples.

Capture settings: headless Chrome, a 1024 × 800 CSS-pixel viewport, 2× device
scale, light theme, and `zh-CN` / `en-US` locales. The overview is cropped to
`.account-center`; the settings capture is cropped to `#settings-dialog`.
When refreshing these images, render the production page with a local fixture
and update both locales. Do not include real account details or device codes.

The existing device-authorization and reasoning-effort screenshots remain
reference images for those separate setup steps. Their appearance can vary
with the installed AstrBot and ChatGPT interface versions.
