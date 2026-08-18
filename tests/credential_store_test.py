"""Regression tests for source-scoped OAuth credential coordination."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

store = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.credential_store"
)

FAILED: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        FAILED.append(message)


class _FakeConfig(dict):
    def __init__(self, *args, commit: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.commit = commit
        self.saved = 0

    async def save_config_async(self) -> bool:
        self.saved += 1
        return self.commit


class _FakeConfigManager:
    def __init__(self, conf: _FakeConfig) -> None:
        self.default_conf = conf


def _source(key: dict | str) -> dict:
    return {
        "id": "OpenAI Subscribe",
        "type": "OpenAI Subscribe",
        "key": key if isinstance(key, str) else json.dumps(key),
        "proxy": "http://proxy.example:8080",
        "originator": "codex_cli_rs",
        "user_agent": "test-agent",
    }


def _coordinator(
    conf: _FakeConfig,
    refresh,
) -> object:
    return store.CredentialCoordinator(
        _FakeConfigManager(conf),
        provider_type="OpenAI Subscribe",
        default_source_id="OpenAI Subscribe",
        default_source_factory=lambda: _source(""),
        refresh_credentials=refresh,
        refresh_skew_seconds=120,
    )


def test_legacy_and_schema_parsing() -> None:
    print("=== Legacy and schema parsing ===")
    legacy = {
        "access_token": "sk-ant-oat01.legacy.token",
        "refresh_token": "refresh-legacy",
        "expires": 9999999999,
        "account_id": "user-legacy",
    }
    parsed = store.parse_credentials(json.dumps(legacy))
    check(parsed == legacy, "legacy JSON is readable without migration")
    stored = json.loads(store.dump_credentials(legacy))
    check(stored["schema_version"] == 1, "writes use schema version 1")
    check(
        store.parse_credentials("sk-ant-oat01.raw.token")["access_token"]
        == "sk-ant-oat01.raw.token",
        "raw access tokens remain readable",
    )
    try:
        store.parse_credentials('{"schema_version": 2, "access_token": "token"}')
    except store.CredentialSchemaError:
        check(True, "future schemas fail closed")
    else:
        check(False, "future schemas must fail closed")


def test_exact_source_matching() -> None:
    print("\n=== Exact source matching ===")
    conf = {
        "provider_sources": [
            {"id": "OpenAI Subscribe", "type": "deepseek", "key": ""},
            _source(""),
        ]
    }
    try:
        store.find_source(conf, "OpenAI Subscribe", "OpenAI Subscribe")
    except store.CredentialSourceError:
        check(True, "a conflicting exact source ID is rejected")
    else:
        check(False, "a conflicting exact source ID must be rejected")

    duplicate = _source("")
    conf = {"provider_sources": [_source(""), duplicate]}
    try:
        store.find_source(conf, "OpenAI Subscribe", "OpenAI Subscribe")
    except store.CredentialSourceError:
        check(True, "duplicate source IDs fail closed")
    else:
        check(False, "duplicate source IDs must fail closed")

    second = _source("")
    second["id"] = "other-openai-source"
    conf = {"provider_sources": [second, _source("")]}
    found = store.find_source(conf, "OpenAI Subscribe", "OpenAI Subscribe")
    check(found is conf["provider_sources"][1], "matching uses the exact source ID")


def test_single_flight_refresh() -> None:
    print("\n=== Source-scoped single-flight refresh ===")
    old = {
        "access_token": "sk-ant-oat01.old.token",
        "refresh_token": "refresh-old",
        "expires": 1,
        "account_id": "user-one",
    }
    conf = _FakeConfig({"provider_sources": [_source(old)]})
    calls = 0

    async def refresh(creds: dict, proxy: str | None) -> dict:
        nonlocal calls
        calls += 1
        check(proxy == "http://proxy.example:8080", "refresh uses source proxy")
        await asyncio.sleep(0)
        return {
            **creds,
            "access_token": "sk-ant-oat01.fresh.token",
            "refresh_token": "refresh-fresh",
            "expires": 9999999999,
        }

    async def run() -> tuple:
        coordinator = _coordinator(conf, refresh)
        return await asyncio.gather(
            coordinator.get_snapshot(),
            coordinator.get_snapshot(),
        )

    first, second = asyncio.run(run())
    check(calls == 1, "two concurrent consumers trigger one refresh")
    check(
        first.access_token == second.access_token == "sk-ant-oat01.fresh.token",
        "both consumers receive the persisted refreshed token",
    )
    durable = json.loads(conf["provider_sources"][0]["key"])
    check(durable["refresh_token"] == "refresh-fresh", "rotated refresh token is saved")
    check(durable["schema_version"] == 1, "refresh lazily migrates legacy credentials")
    check(conf.saved == 1, "the refreshed record is saved once")


def test_login_wins_over_in_flight_refresh() -> None:
    print("\n=== Login wins over an in-flight refresh ===")
    old = {
        "access_token": "sk-ant-oat01.old.token",
        "refresh_token": "refresh-old",
        "expires": 1,
        "account_id": "user-old",
    }
    conf = _FakeConfig({"provider_sources": [_source(old)]})

    async def run() -> object:
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def refresh(creds: dict, proxy: str | None) -> dict:
            refresh_started.set()
            await release_refresh.wait()
            return {
                **creds,
                "access_token": "sk-ant-oat01.refreshed.token",
                "refresh_token": "refresh-refreshed",
                "expires": 9999999999,
            }

        coordinator = _coordinator(conf, refresh)
        refreshing = asyncio.create_task(coordinator.get_snapshot())
        await refresh_started.wait()
        replacing = asyncio.create_task(
            coordinator.replace_credentials(
                "OpenAI Subscribe",
                {
                    "access_token": "sk-ant-oat01.new-login.token",
                    "refresh_token": "refresh-new-login",
                    "expires": 9999999999,
                    "account_id": "user-new",
                },
            )
        )
        release_refresh.set()
        await asyncio.gather(refreshing, replacing)
        return await coordinator.get_snapshot()

    final = asyncio.run(run())
    check(
        final.access_token == "sk-ant-oat01.new-login.token",
        "a completed login is not overwritten by an older refresh",
    )


def test_cooldown_and_reauth_states() -> None:
    print("\n=== Cooldown and reauthorization states ===")
    conf = _FakeConfig(
        {
            "provider_sources": [
                _source(
                    {
                        "access_token": "sk-ant-oat01.current.token",
                        "refresh_token": "refresh-current",
                        "expires": 9999999999,
                        "account_id": "user-one",
                    }
                )
            ]
        }
    )

    async def refresh(creds: dict, proxy: str | None) -> dict:
        return creds

    async def run() -> object:
        coordinator = _coordinator(conf, refresh)
        await coordinator.mark_cooling("OpenAI Subscribe", 9999999999)
        status = coordinator.status()
        try:
            await coordinator.get_snapshot()
        except store.CredentialCooldownError as exc:
            return status, exc
        raise AssertionError("expected cooldown")

    status, error = asyncio.run(run())
    check(status.state == "cooling", "status exposes cooldown without secrets")
    check(error.cooldown_until == 9999999999, "cooldown exposes its reset time")


if __name__ == "__main__":
    test_legacy_and_schema_parsing()
    test_exact_source_matching()
    test_single_flight_refresh()
    test_login_wins_over_in_flight_refresh()
    test_cooldown_and_reauth_states()
    print()
    if FAILED:
        print(f"=== Credential coordination failed: {len(FAILED)} assertion(s) ===")
        for failure in FAILED:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("=== Credential coordination passed ===")
