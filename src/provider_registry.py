"""Manage independent OAuth provider sources and migrate legacy configurations."""

from __future__ import annotations

import asyncio
import secrets
from copy import deepcopy
from typing import Any

from .credential_store import (
    CredentialPersistenceError,
    CredentialSourceError,
    ProviderDisabledError,
    dump_credentials,
    normalize_credentials,
)

LOCAL = "local_codex"
DEVICE = "device_oauth"
UNSET = object()


class ProviderRegistry:
    """Keep provider identities stable while changing their display metadata."""

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator
        self.lock = asyncio.Lock()
        self.on_change: Any = None
        self._pending_previous: dict[str, dict[str, Any]] = {}

    def policy_source(self, source_id: str) -> dict[str, Any]:
        """Keep dispatch on the committed policy while persistence is pending."""
        source = self.coordinator._source(source_id)
        return self._pending_previous.get(source_id, source)

    def enabled(self, source_id: str) -> bool:
        return self.policy_source(source_id).get("enable", True) is True

    def ensure_enabled(self, source_id: str) -> None:
        if not self.enabled(source_id):
            raise ProviderDisabledError("This Provider is disabled for new requests.")

    def routing_mode(self, source_id: str) -> str:
        value = self.policy_source(source_id).get("oauth_routing_mode", "fixed")
        return "auto" if value == "auto" else "fixed"

    def candidates(self, source_id: str) -> list[str]:
        if self.routing_mode(source_id) == "fixed":
            return [source_id]
        return [source_id, *(s["id"] for s in self.owned() if s["id"] != source_id)]

    def sources(self) -> list[dict[str, Any]]:
        sources = self.coordinator._conf().get("provider_sources", [])
        if not isinstance(sources, list) or any(
            not isinstance(source, dict) or not isinstance(source.get("id"), str)
            for source in sources
        ):
            raise CredentialSourceError("Invalid provider source configuration.")
        ids = [source["id"] for source in sources]
        if len(ids) != len(set(ids)):
            raise CredentialSourceError("Provider source IDs must be unique.")
        return sources

    def owned(self) -> list[dict[str, Any]]:
        return sorted(
            (
                s
                for s in self.sources()
                if s.get("type") == self.coordinator._provider_type
            ),
            key=lambda s: s.get("credential_mode") != LOCAL,
        )

    def new_id(self) -> str:
        ids = {s["id"] for s in self.sources()}
        while (source_id := "openai-oauth-" + secrets.token_hex(8)) in ids:
            pass
        return source_id

    @staticmethod
    def name(value: Any) -> str:
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
            raise CredentialSourceError("Provider name must contain 1–80 characters.")
        return value.strip()

    async def _save(self, previous: list[dict[str, Any]]) -> None:
        conf = self.coordinator._conf()
        proposed = deepcopy(conf["provider_sources"])
        self._pending_previous = {s["id"]: s for s in previous}
        try:
            # A newer AstrBot snapshot can supersede this one; retry once.
            if (
                await conf.save_config_async() is False
                and await conf.save_config_async() is False
            ):
                raise CredentialPersistenceError(
                    "Provider configuration was not saved."
                )
        except BaseException as exc:
            before = {s["id"]: s for s in previous}
            after = {s["id"]: s for s in proposed}
            current = conf["provider_sources"]
            for source_id in before.keys() | after.keys():
                if before.get(source_id) == after.get(source_id):
                    continue
                existing = next((s for s in current if s["id"] == source_id), None)
                # Leave concurrent changes by AstrBot or another source untouched.
                if existing != after.get(source_id):
                    continue
                if existing is not None:
                    index = current.index(existing)
                    current.pop(index)
                else:
                    index = next(
                        (i for i, s in enumerate(previous) if s["id"] == source_id),
                        len(current),
                    )
                if source_id in before:
                    current.insert(index, before[source_id])
            if not isinstance(exc, Exception):
                raise
            raise CredentialPersistenceError(
                "Could not save provider configuration."
            ) from exc
        finally:
            self._pending_previous = {}
            if self.on_change is not None:
                self.on_change(conf["provider_sources"])

    async def migrate(self) -> None:
        """Split legacy mixed sources once, keeping existing model references."""
        async with self.lock:
            conf = self.coordinator._conf()
            sources = conf.setdefault("provider_sources", [])
            self.sources()
            previous = deepcopy(sources)
            planned = deepcopy(sources)
            c = self.coordinator
            for source in list(planned):
                if (
                    source.get("type") != c._provider_type
                    or "credential_mode" in source
                ):
                    continue
                local_wins = (
                    source["id"] == c._default_source_id
                    and c.legacy_follow_local
                    and c.local_store is not None
                    and (c.local_store.read() is not None or not source.get("key"))
                )
                if local_wins:
                    if source.get("key"):
                        saved = deepcopy(source)
                        saved.update(
                            id=self.new_id(), name="ChatGPT", credential_mode=DEVICE
                        )
                        planned.append(saved)
                    source.update(name="Local Codex", credential_mode=LOCAL, key="")
                else:
                    source.update(credential_mode=DEVICE)
                    source.setdefault("name", source["id"])
            if not any(
                s.get("type") == c._provider_type and s.get("credential_mode") == LOCAL
                for s in planned
            ):
                source = c._default_source_factory()
                if any(s["id"] == source["id"] for s in planned):
                    source["id"] = self.new_id()
                source.update(name="Local Codex", credential_mode=LOCAL, key="")
                planned.append(source)
            for source in planned:
                if source.get("type") == c._provider_type:
                    source.setdefault("enable", True)
                    source.setdefault("oauth_routing_mode", "fixed")
            if planned != sources:
                sources[:] = planned
                await self._save(previous)
            elif self.on_change is not None:
                self.on_change(sources)

    async def save_login(
        self, source_id: str, name: str, creds: dict[str, Any], *, creating: bool
    ) -> None:
        """Commit a new login only after authorization; never revive deleted IDs."""
        async with self.lock, self.coordinator._source_lock(source_id):
            sources = self.sources()
            previous = deepcopy(sources)
            if creating:
                if any(s["id"] == source_id for s in sources):
                    raise CredentialSourceError("Provider ID already exists.")
                source = self.coordinator._default_source_factory()
                source.update(
                    id=source_id,
                    name=self.name(name),
                    credential_mode=DEVICE,
                    oauth_routing_mode="fixed",
                )
            else:
                source = self.coordinator._source(source_id)
                if source.get("credential_mode", DEVICE) != DEVICE:
                    raise CredentialSourceError("Sign in to local Codex on the host.")
            stored = normalize_credentials(creds)
            stored.pop("cooldown_until", None)
            stored.pop("cooldown_reason", None)
            source["key"] = dump_credentials(stored)
            if creating:
                sources.append(source)
            await self._save(previous)
            self.coordinator._states.pop(source_id, None)
            self.coordinator._usage_cache.pop(source_id, None)

    async def edit(
        self,
        source_id: str,
        *,
        name: Any = UNSET,
        enabled: Any = UNSET,
        routing_mode: Any = UNSET,
        delete: bool = False,
    ) -> None:
        if name is not UNSET:
            name = self.name(name)
        if enabled is not UNSET and type(enabled) is not bool:
            raise CredentialSourceError("enabled must be a boolean.")
        if routing_mode is not UNSET and routing_mode not in ("fixed", "auto"):
            raise CredentialSourceError("routing_mode must be fixed or auto.")
        if not delete and name is UNSET and enabled is UNSET and routing_mode is UNSET:
            raise CredentialSourceError(
                "Provide name, enabled or routing_mode to update."
            )
        async with self.lock, self.coordinator._source_lock(source_id):
            source = self.coordinator._source(source_id)
            sources = self.sources()
            previous = deepcopy(sources)
            if delete:
                if source.get("credential_mode") == LOCAL:
                    raise CredentialSourceError(
                        "The local Codex provider cannot be deleted."
                    )
                # Model definitions are global in AstrBot; profiles select their IDs.
                if any(
                    p.get("provider_source_id") == source_id
                    or (
                        source_id == self.coordinator._default_source_id
                        and p.get("type") == self.coordinator._provider_type
                        and not p.get("provider_source_id")
                    )
                    for p in self.coordinator._conf().get("provider", [])
                ):
                    raise CredentialSourceError(
                        "Remove this provider's model bindings in AstrBot first."
                    )
                sources.remove(source)
            else:
                if name is not UNSET:
                    source["name"] = name
                if enabled is not UNSET:
                    source["enable"] = enabled
                if routing_mode is not UNSET:
                    source["oauth_routing_mode"] = routing_mode
            await self._save(previous)
            if delete:
                self.coordinator._states.pop(source_id, None)
                self.coordinator._usage_cache.pop(source_id, None)
