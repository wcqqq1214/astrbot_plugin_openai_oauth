"""Source-scoped OAuth credential coordination for the OpenAI provider."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

_CREDENTIAL_SCHEMA_VERSION = 1


class CredentialError(RuntimeError):
    """Base error for safe, user-actionable credential failures."""


class CredentialSourceError(CredentialError):
    """The configured provider source cannot safely be used."""


class CredentialSchemaError(CredentialError):
    """The persisted credential record has an unsupported schema."""


class CredentialsNotConfiguredError(CredentialError):
    """The provider source has no usable access token."""


class ReauthenticationRequiredError(CredentialError):
    """The stored credentials cannot be refreshed safely."""


class CredentialPersistenceError(CredentialError):
    """A refreshed credential could not be confirmed in persistent config."""


class CredentialCooldownError(CredentialError):
    """The subscription source is temporarily cooling down."""

    def __init__(
        self,
        cooldown_until: int | None,
        reason: str | None = None,
    ) -> None:
        self.cooldown_until = cooldown_until
        self.reason = reason or "usage_limit_reached"
        super().__init__("The OpenAI subscription is temporarily unavailable.")


@dataclass(frozen=True, slots=True)
class CredentialSnapshot:
    """An immutable source-scoped view of OAuth credentials."""

    source_id: str
    access_token: str
    refresh_token: str
    expires: int | None
    account_id: str
    cooldown_until: int | None
    cooldown_reason: str | None

    def is_access_token_expired(self, now: float | None = None) -> bool:
        return self.expires is not None and self.expires <= (now or time.time())

    def is_cooling_down(self, now: float | None = None) -> bool:
        return self.cooldown_until is not None and self.cooldown_until > (
            now or time.time()
        )


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    """A non-sensitive account status for commands and the Plugin Page."""

    state: str
    cooldown_until: int | None = None
    cooldown_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.state}
        if self.cooldown_until is not None:
            result["cooldown_until"] = self.cooldown_until
        if self.cooldown_reason:
            result["cooldown_reason"] = self.cooldown_reason
        return result


RefreshCredentials = Callable[[dict[str, Any], str | None], Awaitable[dict[str, Any]]]
UsageFetcher = Callable[[CredentialSnapshot], Awaitable[dict[str, Any]]]
DefaultSourceFactory = Callable[[], dict[str, Any]]


def _as_string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_timestamp(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _looks_like_access_token(value: str) -> bool:
    return value.startswith("sk-") or value.count(".") >= 2


def parse_credentials(raw: Any) -> dict[str, Any]:
    """Read a legacy or schema-v1 credential record without mutating it."""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""

    if isinstance(raw, dict):
        parsed = dict(raw)
    elif isinstance(raw, str) and raw.strip():
        value = raw.strip()
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            if _looks_like_access_token(value):
                return {"access_token": value}
            raise CredentialSchemaError("The stored OpenAI credential is invalid.")
        if not isinstance(decoded, dict):
            raise CredentialSchemaError("The stored OpenAI credential is invalid.")
        parsed = dict(decoded)
    else:
        return {}

    schema_version = parsed.get("schema_version")
    if schema_version is not None and schema_version != _CREDENTIAL_SCHEMA_VERSION:
        raise CredentialSchemaError(
            "The stored OpenAI credential schema is unsupported."
        )
    return parsed


def normalize_credentials(creds: dict[str, Any]) -> dict[str, Any]:
    """Produce the current durable credential schema from legacy input."""
    schema_version = creds.get("schema_version")
    if schema_version is not None and schema_version != _CREDENTIAL_SCHEMA_VERSION:
        raise CredentialSchemaError(
            "The stored OpenAI credential schema is unsupported."
        )

    normalized: dict[str, Any] = {
        "schema_version": _CREDENTIAL_SCHEMA_VERSION,
        "access_token": _as_string(creds.get("access_token")),
        "refresh_token": _as_string(creds.get("refresh_token")),
        "account_id": _as_string(creds.get("account_id")),
    }
    expires = _as_timestamp(creds.get("expires"))
    if expires is not None:
        normalized["expires"] = expires
    cooldown_until = _as_timestamp(creds.get("cooldown_until"))
    if cooldown_until is not None:
        normalized["cooldown_until"] = cooldown_until
    cooldown_reason = _as_string(creds.get("cooldown_reason"))
    if cooldown_reason:
        normalized["cooldown_reason"] = cooldown_reason
    return normalized


def dump_credentials(creds: dict[str, Any]) -> str:
    """Serialize the canonical durable credential record."""
    return json.dumps(normalize_credentials(creds), ensure_ascii=False)


def find_source(
    conf: dict[str, Any],
    source_id: str,
    provider_type: str,
) -> dict[str, Any] | None:
    """Find one provider source by its exact ID and expected type."""
    sources = conf.get("provider_sources", [])
    if not isinstance(sources, list):
        raise CredentialSourceError("The provider source configuration is invalid.")
    matches: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict) or source.get("id") != source_id:
            continue
        if source.get("type") != provider_type:
            raise CredentialSourceError(
                "The configured provider source has a different type."
            )
        matches.append(source)
    if len(matches) > 1:
        raise CredentialSourceError("The configured provider source ID is ambiguous.")
    return matches[0] if matches else None


def credentials_match(left: CredentialSnapshot, right: CredentialSnapshot) -> bool:
    """Compare fields that establish whether two records are the same login."""
    return (
        left.access_token == right.access_token
        and left.refresh_token == right.refresh_token
        and left.account_id == right.account_id
        and left.expires == right.expires
        and left.cooldown_until == right.cooldown_until
        and left.cooldown_reason == right.cooldown_reason
    )


class CredentialCoordinator:
    """Coordinate source-scoped OAuth refresh, persistence, and health state."""

    def __init__(
        self,
        config_manager: Any,
        *,
        provider_type: str,
        default_source_id: str,
        default_source_factory: DefaultSourceFactory,
        refresh_credentials: RefreshCredentials,
        refresh_skew_seconds: int = 120,
        usage_cache_ttl_seconds: int = 30,
    ) -> None:
        self._config_manager = config_manager
        self._provider_type = provider_type
        self._default_source_id = default_source_id
        self._default_source_factory = default_source_factory
        self._refresh_credentials = refresh_credentials
        self._refresh_skew_seconds = refresh_skew_seconds
        self._usage_cache_ttl_seconds = usage_cache_ttl_seconds
        self._source_locks: dict[str, asyncio.Lock] = {}
        self._usage_locks: dict[str, asyncio.Lock] = {}
        self._states: dict[str, CredentialStatus] = {}
        self._usage_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def config_manager(self) -> Any:
        """Return the configuration manager this coordinator belongs to."""
        return self._config_manager

    def update_refresh_credentials(
        self, refresh_credentials: RefreshCredentials
    ) -> None:
        """Refresh the callback after a plugin module hot reload."""
        self._refresh_credentials = refresh_credentials

    def close(self) -> None:
        """Discard short-lived runtime state without touching stored credentials."""
        self._source_locks.clear()
        self._usage_locks.clear()
        self._states.clear()
        self._usage_cache.clear()

    def _conf(self) -> Any:
        if self._config_manager is None:
            raise CredentialSourceError(
                "The AstrBot configuration manager is unavailable."
            )
        conf = getattr(self._config_manager, "default_conf", None)
        if conf is None:
            raise CredentialSourceError(
                "The AstrBot configuration manager is unavailable."
            )
        return conf

    def _source_lock(self, source_id: str) -> asyncio.Lock:
        return self._source_locks.setdefault(source_id, asyncio.Lock())

    def _usage_lock(self, source_id: str) -> asyncio.Lock:
        return self._usage_locks.setdefault(source_id, asyncio.Lock())

    def _source(self, source_id: str, *, create: bool = False) -> dict[str, Any]:
        conf = self._conf()
        source = find_source(conf, source_id, self._provider_type)
        if source is not None:
            return source
        if not create or source_id != self._default_source_id:
            raise CredentialSourceError(
                "The configured OpenAI provider source was not found."
            )
        source = self._default_source_factory()
        if source.get("id") != source_id or source.get("type") != self._provider_type:
            raise CredentialSourceError(
                "The default OpenAI provider source is invalid."
            )
        sources = conf.setdefault("provider_sources", [])
        if not isinstance(sources, list):
            raise CredentialSourceError("The provider source configuration is invalid.")
        sources.append(source)
        return source

    def _snapshot_from_source(
        self,
        source_id: str,
        source: dict[str, Any],
    ) -> CredentialSnapshot:
        creds = parse_credentials(source.get("key"))
        return CredentialSnapshot(
            source_id=source_id,
            access_token=_as_string(creds.get("access_token")),
            refresh_token=_as_string(creds.get("refresh_token")),
            expires=_as_timestamp(creds.get("expires")),
            account_id=_as_string(creds.get("account_id")),
            cooldown_until=_as_timestamp(creds.get("cooldown_until")),
            cooldown_reason=_as_string(creds.get("cooldown_reason")) or None,
        )

    def _read_snapshot(self, source_id: str) -> CredentialSnapshot:
        return self._snapshot_from_source(source_id, self._source(source_id))

    def source_settings(self, source_id: str | None = None) -> dict[str, str]:
        """Return only non-secret source settings required by control-plane calls."""
        source = self._source(source_id or self._default_source_id)
        return {
            "proxy": _as_string(source.get("proxy")),
            "originator": _as_string(source.get("originator")),
            "user_agent": _as_string(source.get("user_agent")),
        }

    def _needs_refresh(
        self,
        snapshot: CredentialSnapshot,
        *,
        force_refresh: bool,
    ) -> bool:
        if not snapshot.refresh_token:
            return False
        if force_refresh:
            return True
        if snapshot.expires is None:
            return True
        return snapshot.expires <= time.time() + self._refresh_skew_seconds

    async def _persist(
        self,
        source_id: str,
        source: dict[str, Any],
        creds: dict[str, Any],
    ) -> CredentialSnapshot:
        source["key"] = dump_credentials(creds)
        committed = await self._conf().save_config_async()
        persisted = self._read_snapshot(source_id)
        expected = self._snapshot_from_source(
            source_id, {"key": dump_credentials(creds)}
        )
        if committed is False and not credentials_match(persisted, expected):
            raise CredentialPersistenceError(
                "The refreshed OpenAI credential could not be saved safely."
            )
        if not credentials_match(persisted, expected):
            raise CredentialPersistenceError(
                "The refreshed OpenAI credential could not be confirmed after saving."
            )
        return persisted

    async def replace_credentials(
        self,
        source_id: str | None,
        creds: dict[str, Any],
    ) -> CredentialSnapshot:
        """Atomically persist credentials from a completed device login."""
        resolved_source_id = source_id or self._default_source_id
        async with self._source_lock(resolved_source_id):
            source = self._source(resolved_source_id, create=True)
            stored = normalize_credentials(creds)
            stored.pop("cooldown_until", None)
            stored.pop("cooldown_reason", None)
            snapshot = await self._persist(resolved_source_id, source, stored)
            self._states[resolved_source_id] = CredentialStatus("ready")
            self._usage_cache.pop(resolved_source_id, None)
            return snapshot

    async def get_snapshot(
        self,
        source_id: str | None = None,
        *,
        force_refresh: bool = False,
        check_cooldown: bool = True,
    ) -> CredentialSnapshot:
        """Return a current source snapshot, refreshing it once when needed."""
        resolved_source_id = source_id or self._default_source_id
        snapshot = self._read_snapshot(resolved_source_id)
        if not snapshot.access_token:
            self._states[resolved_source_id] = CredentialStatus("not_logged_in")
            raise CredentialsNotConfiguredError(
                "OpenAI credentials are not configured."
            )
        if check_cooldown and snapshot.is_cooling_down():
            status = CredentialStatus(
                "cooling",
                snapshot.cooldown_until,
                snapshot.cooldown_reason,
            )
            self._states[resolved_source_id] = status
            raise CredentialCooldownError(
                snapshot.cooldown_until,
                snapshot.cooldown_reason,
            )
        if not self._needs_refresh(snapshot, force_refresh=force_refresh):
            self._states[resolved_source_id] = CredentialStatus("ready")
            return snapshot

        async with self._source_lock(resolved_source_id):
            snapshot = self._read_snapshot(resolved_source_id)
            if check_cooldown and snapshot.is_cooling_down():
                status = CredentialStatus(
                    "cooling",
                    snapshot.cooldown_until,
                    snapshot.cooldown_reason,
                )
                self._states[resolved_source_id] = status
                raise CredentialCooldownError(
                    snapshot.cooldown_until,
                    snapshot.cooldown_reason,
                )
            if not self._needs_refresh(snapshot, force_refresh=force_refresh):
                self._states[resolved_source_id] = CredentialStatus("ready")
                return snapshot
            if not snapshot.refresh_token:
                if snapshot.is_access_token_expired() or force_refresh:
                    self._states[resolved_source_id] = CredentialStatus(
                        "reauth_required"
                    )
                    raise ReauthenticationRequiredError(
                        "OpenAI credentials require reauthorization."
                    )
                self._states[resolved_source_id] = CredentialStatus("ready")
                return snapshot

            source = self._source(resolved_source_id)
            self._states[resolved_source_id] = CredentialStatus("refreshing")
            try:
                refreshed = await self._refresh_credentials(
                    {
                        "access_token": snapshot.access_token,
                        "refresh_token": snapshot.refresh_token,
                        "expires": snapshot.expires,
                        "account_id": snapshot.account_id,
                    },
                    _as_string(source.get("proxy")) or None,
                )
            except Exception as exc:
                if not snapshot.is_access_token_expired():
                    self._states[resolved_source_id] = CredentialStatus("degraded")
                    return snapshot
                self._states[resolved_source_id] = CredentialStatus("reauth_required")
                raise ReauthenticationRequiredError(
                    "OpenAI credentials require reauthorization."
                ) from exc

            latest = self._read_snapshot(resolved_source_id)
            if (
                latest.access_token != snapshot.access_token
                or latest.refresh_token != snapshot.refresh_token
            ):
                self._states[resolved_source_id] = CredentialStatus("ready")
                return latest

            persisted = await self._persist(resolved_source_id, source, refreshed)
            self._states[resolved_source_id] = CredentialStatus("ready")
            self._usage_cache.pop(resolved_source_id, None)
            return persisted

    async def mark_cooling(
        self,
        source_id: str | None,
        cooldown_until: int | None,
        *,
        reason: str = "usage_limit_reached",
        expected_access_token: str | None = None,
    ) -> CredentialSnapshot:
        """Persist a subscription cooldown without overwriting a newer login."""
        resolved_source_id = source_id or self._default_source_id
        async with self._source_lock(resolved_source_id):
            source = self._source(resolved_source_id)
            current = self._snapshot_from_source(resolved_source_id, source)
            if expected_access_token and current.access_token != expected_access_token:
                return current
            creds = parse_credentials(source.get("key"))
            if cooldown_until is not None:
                creds["cooldown_until"] = cooldown_until
            else:
                creds.pop("cooldown_until", None)
            creds["cooldown_reason"] = reason
            persisted = await self._persist(resolved_source_id, source, creds)
            self._states[resolved_source_id] = CredentialStatus(
                "cooling",
                persisted.cooldown_until,
                persisted.cooldown_reason,
            )
            return persisted

    async def get_usage(
        self,
        source_id: str | None,
        fetch_usage: UsageFetcher,
    ) -> dict[str, Any]:
        """Fetch usage with source-scoped single-flight and a short cache."""
        resolved_source_id = source_id or self._default_source_id
        now = time.monotonic()
        cached = self._usage_cache.get(resolved_source_id)
        if cached is not None and cached[0] > now:
            return dict(cached[1])

        async with self._usage_lock(resolved_source_id):
            now = time.monotonic()
            cached = self._usage_cache.get(resolved_source_id)
            if cached is not None and cached[0] > now:
                return dict(cached[1])
            snapshot = await self.get_snapshot(
                resolved_source_id,
                check_cooldown=False,
            )
            usage = await fetch_usage(snapshot)
            self._usage_cache[resolved_source_id] = (
                time.monotonic() + self._usage_cache_ttl_seconds,
                dict(usage),
            )
            return dict(usage)

    def status(self, source_id: str | None = None) -> CredentialStatus:
        """Return a safe state without requesting or exposing credentials."""
        resolved_source_id = source_id or self._default_source_id
        try:
            snapshot = self._read_snapshot(resolved_source_id)
        except CredentialSchemaError:
            return CredentialStatus("invalid")
        except CredentialSourceError:
            return CredentialStatus("not_logged_in")
        if not snapshot.access_token:
            return CredentialStatus("not_logged_in")
        if snapshot.is_cooling_down():
            return CredentialStatus(
                "cooling",
                snapshot.cooldown_until,
                snapshot.cooldown_reason,
            )
        return self._states.get(resolved_source_id, CredentialStatus("ready"))
