"""Manage OAuth accounts behind one AstrBot source and migrate legacy configs."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import AsyncExitStack
from copy import deepcopy
from typing import Any

from .credential_store import (
    CredentialPersistenceError,
    CredentialSchemaError,
    CredentialSourceError,
    ProviderDisabledError,
    account_sources,
    dump_credentials,
    is_sealed,
    normalize_credentials,
    parse_credentials,
    subscription_gateway,
)

LOCAL = "local_codex"
DEVICE = "device_oauth"
ACCOUNTS_KEY = "oauth_accounts"
ROUTING_KEY = "oauth_routing"
UNSET = object()


class ProviderRegistry:
    """Keep provider identities stable while changing their display metadata."""

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator
        self.lock = asyncio.Lock()
        self.on_change: Any = None
        self._pending_previous: dict[str, dict[str, Any]] = {}
        self._pending_routing: dict[str, Any] | None = None

    def policy_source(self, source_id: str) -> dict[str, Any]:
        """Keep dispatch on the committed policy while persistence is pending."""
        source = self.coordinator.source(source_id)
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
        conf = self.coordinator.config()
        sources = account_sources(conf, self.coordinator.provider_type)
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
                if s.get("type") == self.coordinator.provider_type
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
            raise CredentialSourceError(
                "Provider name must contain 1–80 characters.", code="invalid_name"
            )
        return value.strip()

    async def _save(self, previous: list[dict[str, Any]]) -> None:
        conf = self.coordinator.config()
        proposed = deepcopy(self.sources())
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
            current = self.sources()
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

    def gateway(self) -> dict[str, Any] | None:
        return subscription_gateway(
            self.coordinator.config(), self.coordinator.provider_type
        )

    def routing(self) -> dict[str, Any]:
        if self._pending_routing is not None:
            return self._pending_routing
        return (self.gateway() or {}).get(ROUTING_KEY, {})

    def resolve_model(self, model_id: str | None, legacy_source: str) -> str:
        routing = self.routing()
        return (
            routing.get("models", {}).get(model_id)
            or routing.get("default_account_id")
            or legacy_source
        )

    def routing_view(self) -> dict[str, Any]:
        c = self.coordinator
        bindings = self.routing().get("models", {})
        account_ids = (
            {c.default_source_id}
            if self.gateway() is not None
            else {s["id"] for s in self.owned()}
        )
        return {
            "default_account_id": self.routing().get(
                "default_account_id", c.default_source_id
            ),
            "models": [
                {"id": m["id"], "account_id": bindings.get(m["id"])}
                for m in c.config().get("provider", [])
                if m.get("provider_source_id") in account_ids | {c.default_source_id}
                or (
                    not m.get("provider_source_id") and m.get("type") == c.provider_type
                )
            ],
        }

    async def _commit_configuration(
        self, updates: dict[str, Any], *, target: dict[str, Any] | None = None
    ) -> None:
        """Persist migration/routing in one AstrBot configuration snapshot."""
        conf = self.coordinator.config()
        container = conf if target is None else target
        changes = {k: v for k, v in updates.items() if container.get(k, UNSET) != v}
        previous = {
            k: deepcopy(container[k]) if k in container else UNSET for k in changes
        }
        proposed = deepcopy(changes)
        container.update(changes)
        try:
            if (
                changes
                and await conf.save_config_async() is False
                and await conf.save_config_async() is False
            ):
                raise CredentialPersistenceError(
                    "Provider configuration was not saved."
                )
        except BaseException as exc:
            for key, value in previous.items():
                if container.get(key) != proposed[key]:
                    continue
                if value is UNSET:
                    container.pop(key, None)
                else:
                    container[key] = value
            if not isinstance(exc, Exception):
                raise
            raise CredentialPersistenceError(
                "Could not save provider configuration."
            ) from exc
        finally:
            if self.on_change is not None:
                self.on_change(conf.get("provider_sources", []))

    async def update_routing(
        self, account_id: str | None, *, model_id: str | None = None
    ) -> None:
        async with self.lock:
            gateway = self.gateway()
            if gateway is None:
                raise CredentialSourceError(
                    "Account migration has not completed.", code="migration_pending"
                )
            if account_id is not None:
                self.coordinator.source(account_id)
            routing = deepcopy(self.routing())
            if model_id is None:
                if account_id is None:
                    raise CredentialSourceError(
                        "A default account is required.", code="invalid_request"
                    )
                routing["default_account_id"] = account_id
            else:
                if model_id not in {m["id"] for m in self.routing_view()["models"]}:
                    raise CredentialSourceError(
                        "The subscription model was not found.", code="model_not_found"
                    )
                if account_id is None:
                    routing["models"].pop(model_id, None)
                else:
                    routing["models"][model_id] = account_id
            self._pending_routing = deepcopy(self.routing())
            try:
                await self._commit_configuration({ROUTING_KEY: routing}, target=gateway)
            finally:
                self._pending_routing = None

    async def migrate(self) -> None:
        """Consolidate accounts behind one source while preserving model preferences."""
        async with self.lock:
            conf = self.coordinator.config()
            sources = conf.setdefault("provider_sources", [])
            self.sources()
            if not isinstance(sources, list) or any(
                not isinstance(s, dict) or not isinstance(s.get("id"), str)
                for s in sources
            ):
                raise CredentialSourceError("Invalid provider source configuration.")
            gateways = [
                s
                for s in sources
                if s.get("type") == self.coordinator.provider_type
                and s.get("oauth_gateway") is True
            ]
            if len(gateways) > 1:
                raise CredentialSourceError(
                    "Multiple subscription gateways are configured."
                )
            if gateways and (
                not gateways[0].get(ACCOUNTS_KEY)
                or not isinstance(gateways[0].get(ROUTING_KEY), dict)
            ):
                raise CredentialSourceError("Invalid subscription account storage.")
            ids = [s["id"] for s in sources]
            if len(ids) != len(set(ids)):
                raise CredentialSourceError("Provider source IDs must be unique.")
            if any(
                s["id"] == self.coordinator.default_source_id
                and s.get("type") != self.coordinator.provider_type
                for s in sources
            ):
                raise CredentialSourceError(
                    "The subscription source ID is already in use."
                )
            planned = deepcopy((self.gateway() or {}).get(ACCOUNTS_KEY, []))
            for source in sources:
                if (
                    source.get("type") != self.coordinator.provider_type
                    or source.get("oauth_gateway") is True
                ):
                    continue
                if any(s["id"] == source["id"] for s in planned):
                    raise CredentialSourceError(
                        "Account ID conflicts with a provider source."
                    )
                planned.append(deepcopy(source))
            c = self.coordinator
            for source in list(planned):
                if source.get("type") != c.provider_type or "credential_mode" in source:
                    continue
                local_wins = (
                    source["id"] == c.default_source_id
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
                s.get("type") == c.provider_type and s.get("credential_mode") == LOCAL
                for s in planned
            ):
                source = c.default_source_factory()
                if any(s["id"] == source["id"] for s in planned):
                    source["id"] = self.new_id()
                source.update(name="Local Codex", credential_mode=LOCAL, key="")
                planned.append(source)
            for source in planned:
                if source.get("type") == c.provider_type:
                    source.setdefault("enable", True)
                    source.setdefault("oauth_routing_mode", "fixed")
            routing = deepcopy(self.routing())
            routing.setdefault(
                "default_account_id",
                next(
                    (s["id"] for s in planned if s["id"] == c.default_source_id),
                    planned[0]["id"],
                ),
            )
            bindings = routing.setdefault("models", {})
            if not isinstance(bindings, dict) or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in bindings.items()
            ):
                raise CredentialSourceError("Invalid model account bindings.")
            models = deepcopy(conf.get("provider", []))
            account_ids = {s["id"] for s in planned}
            legacy_sources = {
                s["id"]: s
                for s in sources
                if s.get("type") == c.provider_type and not s.get("oauth_gateway")
            }
            gateway_ids = {source["id"] for source in gateways}
            for model in models:
                sid = model.get("provider_source_id")
                if sid in legacy_sources or (
                    not sid and model.get("type") == c.provider_type
                ):
                    # Preserve inherited inference settings before changing the source.
                    # Model overrides win, matching AstrBot's shallow config merge.
                    legacy = legacy_sources.get(sid, {})
                    for key in ("timeout", "custom_extra_body"):
                        if key not in model and key in legacy:
                            model[key] = deepcopy(legacy[key])
                    bindings.setdefault(model["id"], sid or c.default_source_id)
                    model["provider_source_id"] = c.default_source_id
                elif sid in gateway_ids:
                    # Current account bindings are mutable, not migration provenance.
                    # Already consolidated models keep their saved inference settings.
                    # Repair references saved before gateway renaming was blocked.
                    model["provider_source_id"] = c.default_source_id
            if routing["default_account_id"] not in account_ids:
                raise CredentialSourceError("The default account was not found.")
            gateway = next(
                (
                    deepcopy(s)
                    for s in sources
                    if s.get("oauth_gateway") is True
                    and s.get("type") == c.provider_type
                ),
                c.default_source_factory(),
            )
            gateway.update(
                id=c.default_source_id,
                key="",
                oauth_gateway=True,
            )
            gateway.pop("name", None)
            gateway[ACCOUNTS_KEY] = planned
            gateway[ROUTING_KEY] = routing
            retained = []
            inserted = False
            for source in sources:
                if source.get("type") == c.provider_type:
                    if not inserted:
                        retained.append(gateway)
                        inserted = True
                else:
                    retained.append(deepcopy(source))
            if not inserted:
                retained.append(gateway)
            await self._commit_configuration(
                {
                    "provider_sources": retained,
                    "provider": models,
                }
            )

    async def seal_stored_credentials(self) -> int:
        """Encrypt plaintext device-login credentials saved by earlier versions.

        Returns the number of records sealed. Unreadable records stay as they
        are so that their status remains visible.
        """
        sealer = self.coordinator.sealer
        if sealer is None:
            return 0
        async with self.lock, AsyncExitStack() as locks:
            sources = self.sources()
            pending = [
                source
                for source in sources
                if source.get("type") == self.coordinator.provider_type
                and source.get("credential_mode", DEVICE) == DEVICE
                and source.get("key")
                and not is_sealed(source["key"])
            ]
            if not pending:
                return 0
            for source in pending:
                await locks.enter_async_context(
                    self.coordinator.source_lock(source["id"])
                )
            previous = deepcopy(sources)
            sealed = 0
            for source in pending:
                try:
                    creds = parse_credentials(source["key"])
                except CredentialSchemaError:
                    continue
                if not creds:
                    continue
                source["key"] = dump_credentials(creds, sealer)
                sealed += 1
            if sealed:
                await self._save(previous)
            return sealed

    async def save_login(
        self, source_id: str, name: str, creds: dict[str, Any], *, creating: bool
    ) -> None:
        """Commit a new login only after authorization; never revive deleted IDs."""
        async with self.lock, self.coordinator.source_lock(source_id):
            sources = self.sources()
            previous = deepcopy(sources)
            if creating:
                if any(s["id"] == source_id for s in sources):
                    raise CredentialSourceError(
                        "Provider ID already exists.", code="provider_exists"
                    )
                source = self.coordinator.default_source_factory()
                source.update(
                    id=source_id,
                    name=self.name(name),
                    credential_mode=DEVICE,
                    oauth_routing_mode="fixed",
                )
            else:
                source = self.coordinator.source(source_id)
                if source.get("credential_mode", DEVICE) != DEVICE:
                    raise CredentialSourceError(
                        "Sign in to local Codex on the host.",
                        code="local_login_required",
                    )
            stored = normalize_credentials(creds)
            stored.pop("cooldown_until", None)
            stored.pop("cooldown_reason", None)
            source["key"] = dump_credentials(stored, self.coordinator.sealer)
            if creating:
                sources.append(source)
            await self._save(previous)
            self.coordinator.forget(source_id)

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
            raise CredentialSourceError(
                "enabled must be a boolean.", code="invalid_request"
            )
        if routing_mode is not UNSET and routing_mode not in ("fixed", "auto"):
            raise CredentialSourceError(
                "routing_mode must be fixed or auto.", code="invalid_request"
            )
        if not delete and name is UNSET and enabled is UNSET and routing_mode is UNSET:
            raise CredentialSourceError(
                "Provide name, enabled or routing_mode to update.",
                code="invalid_request",
            )
        async with self.lock, self.coordinator.source_lock(source_id):
            source = self.coordinator.source(source_id)
            sources = self.sources()
            previous = deepcopy(sources)
            previous_routing = deepcopy(self.routing())
            gateway = self.gateway()
            if delete:
                if source.get("credential_mode") == LOCAL:
                    raise CredentialSourceError(
                        "The local Codex provider cannot be deleted.",
                        code="local_provider_locked",
                    )
                routing = self.routing()
                active_models = {m["id"] for m in self.routing_view()["models"]}
                if routing.get("default_account_id") == source_id or any(
                    account == source_id and model in active_models
                    for model, account in routing.get("models", {}).items()
                ):
                    raise CredentialSourceError(
                        "Select another default account and update model account bindings first.",
                        code="account_in_use",
                    )
                # Model definitions are global in AstrBot; profiles select their IDs.
                if any(
                    p.get("provider_source_id") == source_id
                    and (
                        self.gateway() is None
                        or source_id != self.coordinator.default_source_id
                    )
                    or (
                        source_id == self.coordinator.default_source_id
                        and p.get("type") == self.coordinator.provider_type
                        and not p.get("provider_source_id")
                    )
                    for p in self.coordinator.config().get("provider", [])
                ):
                    raise CredentialSourceError(
                        "Remove this provider's model bindings in AstrBot first.",
                        code="account_has_models",
                    )
                sources.remove(source)
                if gateway is not None:
                    gateway[ROUTING_KEY] = {
                        **previous_routing,
                        "models": {
                            model: account
                            for model, account in previous_routing.get(
                                "models", {}
                            ).items()
                            if account != source_id
                        },
                    }
            else:
                if name is not UNSET:
                    source["name"] = name
                if enabled is not UNSET:
                    source["enable"] = enabled
                if routing_mode is not UNSET:
                    source["oauth_routing_mode"] = routing_mode
            proposed_routing = deepcopy(self.routing())
            try:
                await self._save(previous)
            except BaseException:
                if gateway is not None and gateway.get(ROUTING_KEY) == proposed_routing:
                    gateway[ROUTING_KEY] = previous_routing
                raise
            if delete:
                self.coordinator.forget(source_id)
