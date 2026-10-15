# README screenshots

The provider screenshots were captured on 2026-10-16. The overview was refreshed
from main commit `87d0fa6dfb67dd5dfe08233897eb3d03d861e9d2`; the settings dialog
was captured from `1d173430f47c45e2e37745104bded81a4e059aa2`.

- `providers-overview-zh.png` / `providers-overview-en.png`: two independent
  allowance panels expanded, with source settings and enable controls visible.
- `provider-settings-zh.png` / `provider-settings-en.png`: the device-account
  settings dialog with Automatic fallback selected but not saved.

These are browser captures of the unchanged production HTML, CSS, JavaScript,
and icons in `pages/providers/`. A temporary local bridge fixture supplied
sample accounts: Plus (`codex@example.com`) with five-hour and weekly windows,
and Pro (`backup@example.com`) with a weekly window only. Allowance values are
examples. No real credentials, sign-in sessions, or model requests were used.
The README captions identify these values as examples.

Capture settings: headless Chrome, a 1024 × 800 CSS-pixel viewport, 2× device
scale, light theme, and `zh-CN` / `en-US` locales. The overview is cropped to
`.account-center`; the settings capture is cropped to `#settings-dialog`.
When refreshing these images, render the production page with a local fixture
and update both locales. Do not include real account details or device codes.

The existing device-authorization and reasoning-effort screenshots remain
reference images for those separate setup steps. Their appearance can vary
with the installed AstrBot and ChatGPT interface versions.
