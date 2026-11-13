"""Expose subscription account bindings in AstrBot's model editor."""

from copy import deepcopy
from functools import wraps
from inspect import signature

FIELD = "oauth_account_id"
_ORIGINAL = "_openai_subscribe_model_original"


def install(coordinator):
    from astrbot.dashboard.services.config_service import ProviderConfigService

    originals = {}
    wrappers = {}

    def owned(model):
        return model.get("provider_source_id") == coordinator.default_source_id

    def decorate(model):
        if owned(model):
            model.setdefault(
                FIELD,
                coordinator.providers.routing().get("models", {}).get(model["id"], ""),
            )

    original_schema = getattr(
        ProviderConfigService.get_provider_schema,
        _ORIGINAL,
        ProviderConfigService.get_provider_schema,
    )

    def schema(service):
        result = original_schema(service)
        if service.config is not coordinator.config():
            return result
        result = deepcopy(result)
        accounts = coordinator.providers.owned()
        result["config_schema"]["provider"]["items"][FIELD] = {
            "type": "string",
            "description": "模型账号 / Model account",
            "hint": "留空跟随默认账号 / Leave empty to follow the default account.",
            "options": [""] + [a["id"] for a in accounts],
            "labels": ["跟随默认账号 / Follow default"]
            + [a.get("name") or a["id"] for a in accounts],
            "invisible": len(accounts) < 2,
            "condition": {"provider_source_id": coordinator.default_source_id},
        }
        for model in result["providers"]:
            decorate(model)
        return result

    wrappers["get_provider_schema"] = schema
    originals["get_provider_schema"] = original_schema

    for name in ("create_provider", "update_provider"):
        original = getattr(ProviderConfigService, name)
        original = getattr(original, _ORIGINAL, original)
        originals[name] = original

        def wrap(original, name):
            @wraps(original)
            async def save(service, *args, **kwargs):
                if service.config is not coordinator.config():
                    return await original(service, *args, **kwargs)
                bound = signature(original).bind(service, *args, **kwargs)
                config = bound.arguments["config"]
                source_id = bound.arguments.get("source_id")
                current = next(
                    (
                        m
                        for m in coordinator.config().get("provider", [])
                        if m.get("id") == bound.arguments.get("provider_id")
                    ),
                    {},
                )
                if not (
                    owned(config)
                    or owned(current)
                    or source_id == coordinator.default_source_id
                ):
                    return await original(service, *args, **kwargs)
                async with coordinator.providers.lock:
                    if coordinator.check_write is not None:
                        coordinator.check_write()
                    account = config.get(FIELD)
                    if account is not None and not isinstance(account, str):
                        raise ValueError("Invalid subscription account ID.")
                    if account:
                        coordinator.source(account)
                    return await original(service, *args, **kwargs)

            return save

        wrappers[name] = wrap(original, name)

    for name, wrapper in wrappers.items():
        setattr(wrapper, _ORIGINAL, originals[name])
        setattr(ProviderConfigService, name, wrapper)

    def remove():
        for name, wrapper in wrappers.items():
            if getattr(ProviderConfigService, name) is wrapper:
                setattr(ProviderConfigService, name, originals[name])

    return remove
