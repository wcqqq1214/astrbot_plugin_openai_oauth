# Provider list preview

The offline preview uses the production `app.js` and `style.css`, with a mock
Plugin Views bridge from `prototype.js`. Its accounts, quotas and device codes
are examples only. It does not read local credentials or contact OpenAI.

Run `python pages/login/serve_prototype.py`, then open
<http://127.0.0.1:8769/prototype.html>.

- Local Codex is the first provider, followed by independent device-login providers.
- Select a row to inspect that provider's allowance and actions.
- Add provider simulates authorization after a short delay and adds a new row.
- Reauthorize updates the selected provider; rename keeps its ID.
- Production refuses deletion of Local Codex or a source still bound to models.
- Production migrates legacy mixed sources while retaining existing model bindings.
- Each row has an enable switch; the editor has a fixed / automatic fallback
  choice for models that prefer that provider. Updates take ~0.6 s so the
  saving state is visible. Open `prototype.html?fail=update` to preview a
  rejected save.

`index.html` loads the real AstrBot bridge. `prototype.html` uses the same markup
but loads the offline bridge. Keep their page structure aligned when editing.

Validation commands:

```sh
node tests/view_test.mjs
/Users/wcqqq1214/Project/AstrBot/.venv/bin/python tests/run_tests.py
```

The view regression covers weekly-only quota, unavailable usage, independent
provider selection, stale results after selection changes, login cancellation,
the enable switch and routing mode, serialized per-provider saves, stale list
responses during a save, failed or unclear saves, delayed recovery after selection
or deletion, account identity changes during saves, and confirmed routing notices.
The Python scripts cover migration, credential isolation, refresh, provider
lifecycle, device sessions and the authenticated WebUI boundary.
