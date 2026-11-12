"""Protect plugin-owned account data at AstrBot's source editing boundary."""

from __future__ import annotations

from contextlib import AsyncExitStack
from copy import deepcopy
from functools import wraps
from inspect import iscoroutinefunction, signature

from .credential_store import CredentialError, account_sources
from .provider_registry import ACCOUNTS_KEY, ROUTING_KEY

_ORIGINAL = "_openai_subscribe_original"
_MISSING = object()
_HOOK = "ProviderConfigService.upsert_provider_source"


class HookCompatibilityError(CredentialError):
    """A critical AstrBot integration cannot safely protect account configuration."""

    code = "incompatible_astrbot"


def check_hook():
    """Resolve and validate the save hook before replacing it."""
    try:
        from astrbot.dashboard.services.config_service import ProviderConfigService
    except ImportError:
        raise HookCompatibilityError(f"Unavailable critical hook: {_HOOK}") from None
    current = getattr(ProviderConfigService, "upsert_provider_source", None)
    original = getattr(current, _ORIGINAL, current)
    try:
        if not callable(current) or not iscoroutinefunction(original):
            raise TypeError
        source_id, config = object(), object()
        bound = signature(original).bind(None, source_id, config)
        if (
            bound.arguments.get("source_id") is not source_id
            or bound.arguments.get("config") is not config
        ):
            raise TypeError
    except (TypeError, ValueError):
        raise HookCompatibilityError(f"Incompatible critical hook: {_HOOK}") from None
    return ProviderConfigService, original


def _is_subscription(conf, provider_type, fixed_id, source_id, config):
    current = next(
        (
            source
            for source in conf.get("provider_sources", [])
            if source.get("id") == source_id
        ),
        {},
    )
    return (
        source_id == fixed_id
        or config.get("id") == fixed_id
        or config.get("type") == provider_type
        or current.get("type") == provider_type
        or (
            not current
            and not config.get("type")
            and source_id
            in {source["id"] for source in account_sources(conf, provider_type)}
        )
    )


def block_writes(conf, provider_type, fixed_id, error):
    """Keep a failed startup from leaving subscription writes unprotected."""
    from astrbot.dashboard.services.config_service import ProviderConfigService

    current = getattr(ProviderConfigService, "upsert_provider_source", _MISSING)
    original = getattr(current, _ORIGINAL, current)
    try:
        check_hook()
    except HookCompatibilityError:
        scoped = False
    else:
        scoped = True

    message = str(error)

    async def blocked(service, *args, **kwargs):
        if service.config is conf:
            if scoped:
                bound = signature(original).bind(service, *args, **kwargs)
                source_id = bound.arguments["source_id"]
                config = bound.arguments["config"]
                if not _is_subscription(
                    conf, provider_type, fixed_id, source_id, config
                ):
                    return await original(service, *args, **kwargs)
            raise HookCompatibilityError(message)
        if not callable(original):
            raise HookCompatibilityError(message)
        return await original(service, *args, **kwargs)

    setattr(blocked, _ORIGINAL, original)
    ProviderConfigService.upsert_provider_source = blocked

    def remove():
        if ProviderConfigService.upsert_provider_source is blocked:
            if original is _MISSING:
                delattr(ProviderConfigService, "upsert_provider_source")
            else:
                ProviderConfigService.upsert_provider_source = original

    return remove


def install(coordinator, *, check_available=None):
    """Install one scoped guard and return an identity-safe removal callback.

    AstrBot submits the entire source snapshot, including invisible fields.
    Preserve current private records while accepting editable source settings.
    The account locks also protect token refreshes already in flight.
    """
    ProviderConfigService, original = check_hook()

    @wraps(original)
    async def guarded(service, source_id, config, *args, **kwargs):
        registry = coordinator.providers
        if service.config is not coordinator.config():
            return await original(service, source_id, config, *args, **kwargs)
        async with registry.lock, AsyncExitStack() as locks:
            gateway = registry.gateway()
            fixed_id = coordinator.default_source_id
            provider_type = coordinator.provider_type
            if not _is_subscription(
                service.config, provider_type, fixed_id, source_id, config
            ):
                return await original(service, source_id, config, *args, **kwargs)
            if check_available is not None:
                check_available()
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
                await locks.enter_async_context(coordinator.source_lock(account["id"]))
            if check_available is not None:
                check_available()
            gateway = registry.gateway()
            updated = deepcopy(config)
            updated.update(id=fixed_id, type=provider_type)
            for key in ("oauth_gateway", ACCOUNTS_KEY, ROUTING_KEY):
                updated[key] = deepcopy(gateway[key])
            updated["key"] = ""
            return await original(service, source_id, updated, *args, **kwargs)

    setattr(guarded, _ORIGINAL, original)
    ProviderConfigService.upsert_provider_source = guarded

    def remove():
        if ProviderConfigService.upsert_provider_source is guarded:
            ProviderConfigService.upsert_provider_source = original

    return remove
