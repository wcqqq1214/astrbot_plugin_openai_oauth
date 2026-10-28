# Development

## Layout

`main.py` contains the AstrBot entry point, lifecycle hooks, and command registration.
The implementation lives in the internal `src/` package, loaded by AstrBot through
relative imports:

- `runtime.py`: shared configuration and credential coordination.
- `provider.py`: the AstrBot provider: credentials, retries, and source routing.
- `codex_request.py`, `codex_stream.py`, and `transport_pool.py`: Codex request
  shaping, Responses stream parsing, and per-account HTTP transports.
- `oauth.py` and `login.py`: OAuth protocol, login sessions, and task cleanup.
- `web_api.py`: WebUI endpoints.
- `usage.py` and `effort.py`: allowance queries and conversation reasoning settings.
- `credential_store.py`, `credential_seal.py`, `local_codex.py`,
  `provider_registry.py`, and `provider_routing.py`: credentials, encryption at
  rest, account sources, and routing rules.

WebUI assets live in `pages/providers/`; translations are in `strings.js`. Plugin metadata and configuration descriptions
stay at the repository root. See [routing API](provider-routing-api.md) for dispatch
rules and [screenshot notes](../images/README.md) for image provenance.

## Checks

The plugin's uv environment contains only its own development dependencies.
AstrBot and its framework dependencies are provided by the host process.

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
node tests/view_test.mjs
```

Run `tests/run_tests.py` with the local AstrBot checkout's virtualenv Python:

```sh
/path/to/AstrBot/.venv/bin/python tests/run_tests.py
```

The tests expect the AstrBot checkout next to this repository (`../AstrBot`).
Set `ASTRBOT_ROOT=/path/to/AstrBot` to use a checkout elsewhere.

The runner tests this checkout rather than the deployed plugin copy. Tests use
isolated credentials to avoid reading or refreshing real accounts. Follow
[AGENTS.md](../AGENTS.md) for repository conventions and local setup.

## Releases

CI runs the integration suite against the declared minimum AstrBot release and the
newest verified one, and a weekly run tests the latest AstrBot release. When a new
AstrBot release passes, update the newest version in `.github/workflows/test.yml`.

Pushing `main` runs tests without publishing a release. To release:

1. Update the version in `metadata.yaml`, `pyproject.toml`, the `main.py` registration,
   and both README badges. Run `uv lock` and add the release notes to `CHANGELOG.md`.
   `python3 .github/scripts/release_check.py versions` confirms every reference
   agrees; CI and the release workflow run the same check.
2. Keep the plugin descriptions in `.astrbot-plugin/i18n/` aligned with `metadata.yaml`.
3. Run the checks above and the integration suite, then confirm CI passes on the
   exact commit to release.
4. Create and push the matching `vX.Y.Z` tag.

The release workflow checks that the tag matches the plugin version, then packages
and publishes it. A local-only tag does not trigger a release.
