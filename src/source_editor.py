"""Protect plugin-owned account data at AstrBot's source editing boundary."""

from __future__ import annotations

from contextlib import AsyncExitStack
from copy import deepcopy
from functools import wraps

from .provider_registry import ACCOUNTS_KEY, ROUTING_KEY

_ORIGINAL = "_openai_subscribe_original"


def install(coordinator):
    """Install one scoped guard and return an identity-safe removal callback.

    AstrBot submits the entire source snapshot, including invisible fields.
    Preserve current private records while accepting editable source settings.
    The account locks also protect token refreshes already in flight.
    """
    from astrbot.dashboard.services.config_service import ProviderConfigService

    current = ProviderConfigService.upsert_provider_source
    original = getattr(current, _ORIGINAL, current)

    @wraps(original)
    async def guarded(service, source_id, config):
        registry = coordinator.providers
        if service.config is not coordinator._conf():
            return await original(service, source_id, config)
        async with registry.lock, AsyncExitStack() as locks:
            gateway = registry.gateway()
            fixed_id = coordinator._default_source_id
            provider_type = coordinator._provider_type
            current = next(
                (
                    s
                    for s in service.config.get("provider_sources", [])
                    if s.get("id") == source_id
                ),
                {},
            )
            is_subscription = (
                source_id == fixed_id
                or config.get("id") == fixed_id
                or config.get("type") == provider_type
                or current.get("type") == provider_type
                or (
                    not current
                    and not config.get("type")
                    and source_id in {account["id"] for account in registry.owned()}
                )
            )
            if not is_subscription:
                return await original(service, source_id, config)
            if gateway is None or source_id != fixed_id or gateway["id"] != fixed_id:
                raise ValueError(
                    "This subscription source is outdated. Reload the source list "
                    "and manage accounts in the OpenAI Subscribe plugin page."
                )
            if str(config.get("id") or source_id).strip() != fixed_id:
                raise ValueError(
                    "The subscription source ID must remain OpenAI Subscribe."
                )
            if config.get("type", provider_type) != provider_type:
                raise ValueError("The OpenAI Subscribe source type cannot be changed.")
            for account in registry.sources():
                await locks.enter_async_context(coordinator._source_lock(account["id"]))
            gateway = registry.gateway()
            updated = deepcopy(config)
            updated.update(id=fixed_id, type=provider_type)
            for key in ("oauth_gateway", ACCOUNTS_KEY, ROUTING_KEY):
                updated[key] = deepcopy(gateway[key])
            updated["key"] = ""
            return await original(service, source_id, updated)

    setattr(guarded, _ORIGINAL, original)
    ProviderConfigService.upsert_provider_source = guarded

    def remove():
        if ProviderConfigService.upsert_provider_source is guarded:
            ProviderConfigService.upsert_provider_source = original

    return remove
