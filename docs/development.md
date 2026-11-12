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
AstrBot and its framework dependencies (httpx, the OpenAI SDK, cryptography and
Pillow) are provided by the host process. Runtime dependencies remain empty in
both `requirements.txt` and `pyproject.toml`; mypy and Ruff are development tools.

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run python tests/run_unit_tests.py
uv run mypy
node tests/view_test.mjs
```

The fast runner needs no AstrBot checkout: it imports the internal `src` package
directly, blocks AstrBot imports, and uses temporary credential paths. It covers
credential coordination, local-file rotation, registry persistence, routing budgets,
transport lifetimes, and the version reminder. The existing credential regressions
run in both layers. mypy checks the five framework-free core modules with
`check_untyped_defs`; framework imports are skipped, and this is not whole-plugin
strict typing.

Run the complete integration suite with the local AstrBot checkout's virtualenv Python:

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

[Dependabot](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/auto-update-actions) checks pinned GitHub Actions and uv development dependencies weekly.
The separate `codex-release` CI job runs weekly and on manual workflow dispatch.
It compares the built-in version with the latest stable `openai/codex` release,
adds a workflow summary, and fails on version drift so maintainers can see it in
workflow notifications (subject to their GitHub notification settings). It never
changes version or model constants. Review protocol compatibility, the offline
model fallback and image model, then update only after verification. Fetch or
metadata failures also fail the job rather than silently reporting up-to-date.

Pushing `main` runs tests without publishing a release. To release:

1. Update the version in `metadata.yaml`, `pyproject.toml`, the `main.py` registration,
   and both README badges. Run `uv lock` and add the release notes to `CHANGELOG.md`.
   `python3 .github/scripts/release_check.py versions` confirms every reference
   agrees; CI and the release workflow run the same check.
2. Keep the plugin descriptions in `.astrbot-plugin/i18n/` aligned with `metadata.yaml`.
3. Run the checks above and the integration suite, then confirm CI passes on the
   exact commit to release.
4. Create and push the matching `vX.Y.Z` tag.

The release workflow checks that the tag matches the plugin version and that
`CHANGELOG.md` has a section for it, then packages the runtime files (see
`.gitattributes`) and publishes them with that section as the release notes. A local-only tag does not trigger a release.
