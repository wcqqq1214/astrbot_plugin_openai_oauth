"""Fixture-style protocol compatibility tests for OpenAI Codex control APIs."""

from __future__ import annotations

import asyncio
import importlib
import os
import sys

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

oauth = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.oauth")

FAILED: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        FAILED.append(message)


class _Response:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def test_models() -> None:
    print("=== Models protocol ===")
    client = _Client(
        _Response(
            200,
            {"data": [{"slug": "gpt-model-a"}, {"id": "gpt-model-b"}]},
        )
    )
    original = oauth.create_proxy_client
    oauth.create_proxy_client = lambda *_args, **_kwargs: client
    try:
        models = asyncio.run(
            oauth.fetch_models(
                "sk-ant-oat01-redacted.redacted.redacted",
                "user-redacted",
                "http://proxy.example:8080",
                "originator-test",
                "agent-test",
            )
        )
    finally:
        oauth.create_proxy_client = original
    url, kwargs = client.calls[0]
    check(models == ["gpt-model-a", "gpt-model-b"], "new model schema is normalized")
    check(url.endswith("/models?client_version=1.0.0"), "models endpoint is stable")
    check(
        kwargs["headers"]["originator"] == "originator-test", "originator is forwarded"
    )
    check(
        kwargs["headers"]["User-Agent"] == "agent-test",
        "source user agent is forwarded",
    )
    check(client.closed, "models client closes")


def test_usage_schemas() -> None:
    print("\n=== Usage protocol ===")
    current = {
        "rate_limit": {
            "allowed": True,
            "limit_reached": False,
            "primary_window": {
                "used_percent": 35,
                "limit_window_seconds": 18000,
                "reset_after_seconds": 1200,
                "reset_at": 1234567890,
            },
            "secondary_window": {
                "used_percent": 12,
                "limit_window_seconds": 604800,
                "reset_after_seconds": 95000,
                "reset_at": 1234567890,
            },
        }
    }
    legacy = {
        "rate_limits": {
            "codex": [
                {
                    "usage_in_seconds": 6300,
                    "limit_in_seconds": 18000,
                    "resets_in_seconds": 1200,
                }
            ]
        }
    }
    parsed_current = oauth._parse_usage_payload(current)
    parsed_legacy = oauth._parse_usage_payload(legacy)
    check(len(parsed_current["windows"]) == 2, "current usage schema has both windows")
    check(
        parsed_current["windows"][0]["used_percent"] == 35.0,
        "current usage preserves percentage",
    )
    check(len(parsed_legacy["windows"]) == 1, "legacy usage schema remains supported")
    check(
        parsed_legacy["windows"][0]["used_percent"] == 35.0,
        "legacy usage is converted to percentage",
    )


def test_error_classification() -> None:
    print("\n=== Upstream error classification ===")

    class _Error(RuntimeError):
        def __init__(self, status_code: int, body=None) -> None:
            self.status_code = status_code
            self.body = body

    check(
        oauth.classify_codex_error(_Error(401)) == "credential",
        "401 requires credential recovery",
    )
    check(
        oauth.classify_codex_error(
            _Error(429, {"error": {"code": "usage_limit_reached"}})
        )
        == "usage_limit",
        "subscription quota 429 is distinguished from ordinary rate limiting",
    )
    check(
        oauth.classify_codex_error(_Error(429)) == "rate_limit",
        "ordinary 429 remains ordinary rate limiting",
    )
    check(
        oauth.classify_codex_error(_Error(503)) == "temporary",
        "5xx is classified as temporary",
    )


if __name__ == "__main__":
    test_models()
    test_usage_schemas()
    test_error_classification()
    print()
    if FAILED:
        print(f"=== Protocol compatibility failed: {len(FAILED)} assertion(s) ===")
        for failure in FAILED:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("=== Protocol compatibility passed ===")
