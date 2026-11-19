# Development

## Project layout

`main.py` holds the AstrBot entry point, lifecycle hooks, and command registration. The implementation lives in `src/`:

- `runtime.py`: shared configuration and credential coordinator setup.
- `provider.py`: AstrBot provider adapter, retry handling, and account routing.
- `codex_request.py`, `codex_stream.py`, `transport_pool.py`: request shaping, Responses stream parsing, and per-account HTTP transport pooling.
- `oauth.py`, `login.py`: OAuth constants/requests, device-login sessions, and task cleanup.
- `web_api.py`: authenticated WebUI endpoints.
- `usage.py`, `effort.py`, `messages.py`: allowance queries, per-session reasoning overrides, and localized chat replies.
- `image_generation.py`, `image_input.py`, `astrbot_image_bridge.py`: GPT Image generation, input image resizing, and optional AstrBot image hooks.
- `credential_store.py`, `credential_seal.py`, `local_codex.py`, `provider_registry.py`, `provider_routing.py`: credential coordination, Fernet sealing, local Codex sync, account registry/migration, and routing budgets.
- `source_editor.py`, `model_editor.py`: AstrBot source-write guard and model-account selector hooks.

WebUI assets live under `pages/providers/` (translations in `strings.js`). See [the routing & API guide](provider-routing-api.md) for endpoint and dispatch details, and [screenshot notes](../images/README.md) for README capture setup.

## Local checks

The plugin's `uv` environment contains development dependencies only; AstrBot provides runtime libraries (`httpx`, the OpenAI SDK, `cryptography`, and Pillow) at runtime, so `requirements.txt` and `pyproject.toml` keep runtime dependencies empty.

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run python tests/run_unit_tests.py
uv run mypy
node tests/view_test.mjs
```

- `tests/run_unit_tests.py` runs without an AstrBot checkout (blocks `astrbot` imports, isolates temporary credential paths) and executes `tests/credential_store_test.py` plus `tests/unit/`.
- `uv run mypy` checks the five framework-free core modules listed in `pyproject.toml` with `check_untyped_defs = true` and `follow_imports = "skip"`.
- `node tests/view_test.mjs` runs Plugin View frontend regressions.

Run the full integration suite with a local AstrBot checkout's virtualenv:

```sh
/path/to/AstrBot/.venv/bin/python tests/run_tests.py
```

By default, this looks for `../AstrBot`; set `ASTRBOT_ROOT=/path/to/AstrBot` otherwise. Tests use isolated fixtures rather than real user accounts or an installed plugin copy. Follow [AGENTS.md](../AGENTS.md) for repo conventions.

## AstrBot compatibility guard

Before registering metadata or WebUI routes, startup validates `CONFIG_METADATA_2` provider fields and the async `ProviderConfigService.upsert_provider_source(service, source_id, config)` signature (`src/source_editor.py`). Image bridge hooks (`src/astrbot_image_bridge.py`) are optional and degrade safely.

- **On critical failure**: startup aborts, account operations return HTTP 503 `incompatible_astrbot`, and a fail-closed blocker replaces `upsert_provider_source` for that config instance (blocking only subscription writes if the signature is still recognizable, or all writes on that config instance otherwise). A subsequent reload on a compatible AstrBot version restores the normal guard; if `ProviderConfigService` cannot be imported or patched, startup still fails and logs that protection is unavailable.
- **At runtime write boundaries**: if startup failed, queued registry mutations roll back in-memory changes, and credential persistence and token refreshes abort before modifying the source or dispatching.

## CI and releases

### Continuous integration

- PRs and pushes to `main` run lint, unit tests, mypy, Plugin View tests, version consistency checks, and the integration suite against the declared minimum and newest verified AstrBot releases (`.github/workflows/test.yml`; update the newest version there when a newer AstrBot release passes).
- A weekly schedule tests AstrBot `latest` and runs `codex-release` (also runnable manually) to detect drift against the latest stable `openai/codex` release. Drift or fetch errors fail the job to alert maintainers without altering constants; verify protocol compatibility, offline model fallbacks, and the image model before bumping the built-in version.
- Dependabot checks pinned GitHub Actions and `uv` dev dependencies weekly.

### Publishing a release

Pushing to `main` runs tests without publishing. To cut a release:

1. Bump the version in `metadata.yaml`, `pyproject.toml`, `main.py`, and both README badges, then run `uv lock`.
2. Add a `## [vX.Y.Z]` section to `CHANGELOG.md` and keep `.astrbot-plugin/i18n/` aligned with `metadata.yaml` if descriptions changed.
3. Verify `python3 .github/scripts/release_check.py versions`, local checks, and CI on the target commit.
4. Create and push the `vX.Y.Z` tag (local tags do not trigger releases).

The release workflow validates the tag and `CHANGELOG.md` entry, packages runtime files per `.gitattributes`, and publishes the GitHub release using that changelog section.
