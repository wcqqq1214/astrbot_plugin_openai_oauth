# AGENTS.md

## Commit conventions

- Write all commit messages in **English**.
- Do **not** append a `Co-Authored-By` trailer or any other attribution line.
- Use conventional commit prefixes, e.g. `feat:`, `fix:`, `chore:`, `docs:`.

## Development notes

- Use English for all comments and logs.
- Use `httpx` or `aiohttp` for network requests (do not use `requests`).
- Persist data under the AstrBot `data` directory, not the plugin directory.
- Run `ruff format .` and `ruff check .` before committing.
- Add third-party dependencies to `requirements.txt`.

## Development environment

The plugin has its own uv-managed virtualenv (`.venv`, Python 3.12.13) that
holds **only the plugin's own dependencies**. AstrBot — and all of AstrBot's
framework dependencies — is *not* installed here; the plugin gets it from the
AstrBot process at runtime. This plugin currently adds no runtime
dependencies of its own (`httpx` and the `openai` SDK come from AstrBot).

- `uv sync` — install or refresh the plugin's dependencies.
- `uv run ruff check .` / `uv run ruff format .` — lint and format.

Anything that needs to `import astrbot` (e.g. integration checks) must run
against the local AstrBot checkout's venv instead, so it uses the same
interpreter and astrbot code as the deployed AstrBot:

```
/Users/wcqqq1214/Project/AstrBot/.venv/bin/python your_script.py
```

Keep the `requirements.txt` in sync with the `dependencies` list in
`pyproject.toml` (same constraints).

## Protocol references

The Codex OAuth flow and the `chatgpt.com/backend-api/codex` endpoint shape
follow the implementations in opencode (`sst/opencode`), openclaw
(`openclaw/openclaw`) and hermes-agent (`NousResearch/hermes-agent`). The
device-code flow is the one to embed in a WebUI; the token is a JWT (possibly
with an `sk-ant-oat01-` prefix glued to the header). See `main.py` for the
constants.
