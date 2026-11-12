"""Shared configuration and credential coordinator for the plugin runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.api import AstrBotConfig
from astrbot.api.star import Context
from astrbot.core.config.default import CONFIG_METADATA_2
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from . import astrbot_image_bridge, messages, oauth, source_editor
from .credential_seal import FernetCredentialSealer
from .credential_store import CredentialError
from .local_codex import LocalCodexStore, LocalCredentialCoordinator
from .oauth import (
    CODEX_BASE,
    DEFAULT_ORIGINATOR,
)

_REFRESH_SKEW_SECONDS = 120
PROVIDER_TYPE = "OpenAI Subscribe"
_PLUGIN_NAME = "astrbot_plugin_openai_oauth"
# Optional override, e.g. to keep the key on a separate secret mount.
_CREDENTIAL_KEY_ENV = "OPENAI_OAUTH_CREDENTIAL_KEY_FILE"
_COORDINATOR_ATTR = "_astrbot_openai_oauth_credential_coordinator"

# Bound by the entry point; all consumers resolve credentials through this module.
_config_mgr: Any = None
_credential_coordinator: LocalCredentialCoordinator | None = None
_local_codex_store: LocalCodexStore | None = None
_remove_source_guard: Any = None
_remove_image_bridge: Any = None
_credential_sealer: FernetCredentialSealer | None = None
_startup_error: str | None = None


def _credential_key_path() -> Path:
    configured = os.environ.get(_CREDENTIAL_KEY_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path(get_astrbot_plugin_data_path()) / _PLUGIN_NAME / "credential.key"


def _build_default_source_config() -> dict[str, Any]:
    return {
        "provider": "openai",
        "type": PROVIDER_TYPE,
        "provider_type": "chat_completion",
        "key": "",
        "api_base": CODEX_BASE,
        "proxy": "",
        "originator": DEFAULT_ORIGINATOR,
        # Empty follows the Codex version this plugin and local Codex name.
        "user_agent": "",
        "id": PROVIDER_TYPE,
        "enable": True,
    }


def ensure_compatible() -> None:
    if _startup_error is not None:
        raise source_editor.HookCompatibilityError(_startup_error)


def get_coordinator() -> LocalCredentialCoordinator:
    ensure_compatible()
    return _resolve_coordinator()


def _resolve_coordinator() -> LocalCredentialCoordinator:
    global _credential_coordinator
    cfg_mgr = _config_mgr
    if cfg_mgr is None:
        raise CredentialError("The AstrBot configuration manager is unavailable.")

    existing = getattr(cfg_mgr, _COORDINATOR_ATTR, None)
    if isinstance(existing, LocalCredentialCoordinator):
        existing.update_refresh_credentials(oauth.refresh_access_token)
        existing.local_store = _local_codex_store
        existing.sealer = _credential_sealer
        _credential_coordinator = existing
        return existing
    if (
        _credential_coordinator is not None
        and _credential_coordinator.config_manager is cfg_mgr
    ):
        _credential_coordinator.update_refresh_credentials(oauth.refresh_access_token)
        _credential_coordinator.local_store = _local_codex_store
        _credential_coordinator.sealer = _credential_sealer
        return _credential_coordinator

    coordinator = LocalCredentialCoordinator(
        cfg_mgr,
        provider_type=PROVIDER_TYPE,
        default_source_id=PROVIDER_TYPE,
        default_source_factory=_build_default_source_config,
        refresh_credentials=oauth.refresh_access_token,
        refresh_skew_seconds=_REFRESH_SKEW_SECONDS,
        local_store=_local_codex_store,
    )
    coordinator.sealer = _credential_sealer
    try:
        setattr(cfg_mgr, _COORDINATOR_ATTR, coordinator)
    except (AttributeError, TypeError):
        pass
    _credential_coordinator = coordinator
    return coordinator


def _metadata_fields() -> dict:
    path = ("provider_group", "metadata", "provider", "items")
    value = CONFIG_METADATA_2
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise source_editor.HookCompatibilityError(
                "Incompatible critical metadata: CONFIG_METADATA_2.provider_group.metadata.provider.items"
            )
        value = value[key]
    if not isinstance(value, dict):
        raise source_editor.HookCompatibilityError(
            "Incompatible critical metadata: provider.items must be a mapping"
        )
    return value


def _block_startup(context, error) -> None:
    global _startup_error, _remove_source_guard
    _startup_error = str(error)
    try:
        _remove_source_guard = source_editor.block_writes(
            context.astrbot_config_mgr.default_conf, PROVIDER_TYPE, PROVIDER_TYPE, error
        )
    except Exception as exc:  # noqa: BLE001 - startup still fails when the host boundary is absent
        logger.error(
            "OpenAI Subscribe could not install the source-write blocker: %s",
            type(exc).__name__,
        )
    logger.error(
        "OpenAI Subscribe startup blocked; configuration protection unavailable: %s",
        error,
    )


def configure(context: Context, config: AstrBotConfig) -> None:
    """Check critical contracts before publishing account configuration hooks."""
    global _config_mgr, _local_codex_store, _credential_sealer
    global _remove_source_guard, _startup_error
    failures = []
    fields = None
    try:
        fields = _metadata_fields()
    except source_editor.HookCompatibilityError as exc:
        failures.append(str(exc))
    try:
        source_editor.check_hook()
    except source_editor.HookCompatibilityError as exc:
        failures.append(str(exc))
    if failures:
        error = source_editor.HookCompatibilityError(
            "; ".join(failures)
            + ". Provider source writes are blocked. Use a compatible AstrBot version and reload the plugin."
        )
        _block_startup(context, error)
        raise error

    definitions = {
        "oauth_gateway": {"type": "bool", "invisible": True},
        "oauth_accounts": {"type": "list", "invisible": True},
        "oauth_routing": {"type": "object", "invisible": True},
    }
    missing = object()
    previous = {key: fields.get(key, missing) for key in definitions}
    try:
        _config_mgr = context.astrbot_config_mgr
        _credential_sealer = FernetCredentialSealer(_credential_key_path())
        messages.set_language(config.get("chat_language", messages.DEFAULT_LANGUAGE))
        _local_codex_store = LocalCodexStore(
            str(config.get("codex_auth_path", "") or "")
        )
        oauth.set_codex_home(_local_codex_store.path.parent)
        coordinator = _resolve_coordinator()
        coordinator.check_write = ensure_compatible
        fields.update(definitions)
        _remove_source_guard = source_editor.install(
            coordinator, check_available=ensure_compatible
        )
        # Legacy migration only; explicit account modes replace this hidden setting.
        coordinator.legacy_follow_local = config.get("follow_local_codex", True)
        manager = getattr(context, "provider_manager", None)
        if manager is not None:

            def sync_sources(sources: list[dict[str, Any]]) -> None:
                manager.provider_sources_config = sources
                manager.providers_config = coordinator.config().get("provider", [])

            coordinator.providers.on_change = sync_sources
    except Exception as exc:  # noqa: BLE001 - never continue with an unprotected account source
        for key, value in previous.items():
            if value is missing:
                fields.pop(key, None)
            else:
                fields[key] = value
        error = source_editor.HookCompatibilityError(
            f"Critical configuration protection setup failed ({type(exc).__name__}). "
            "Provider source writes are blocked. Check AstrBot compatibility and reload the plugin."
        )
        _block_startup(context, error)
        raise error from None
    _startup_error = None
    logger.info(
        "OpenAI Subscribe critical hooks ready: provider metadata fields, ProviderConfigService.upsert_provider_source"
    )


async def initialize(context: Context) -> None:
    """Migrate storage and replace model instances retained across plugin reloads."""
    global _remove_image_bridge
    from .provider import ProviderOpenAICodex

    coordinator = get_coordinator()
    await coordinator.ensure_default_source()
    try:
        sealed = await coordinator.providers.seal_stored_credentials()
    except (CredentialError, OSError) as exc:
        # Plaintext records keep working; sealing is retried on the next start.
        logger.warning(
            "OpenAI Subscribe could not encrypt stored credentials: %s",
            type(exc).__name__,
        )
    else:
        if sealed:
            logger.info("OpenAI Subscribe encrypted %s stored credential(s).", sealed)
    manager = getattr(context, "provider_manager", None)
    if manager is None:
        return
    instances = getattr(manager, "inst_map", {})
    selected = getattr(manager, "curr_provider_inst", None)
    selected_id = next(
        (key for key, inst in instances.items() if inst is selected), None
    )
    try:
        for model in list(coordinator.config().get("provider", [])):
            if model["id"] not in instances or not (
                model.get("provider_source_id") == coordinator.default_source_id
                or model.get("type") == PROVIDER_TYPE
            ):
                continue
            await manager.reload(model)
            if model.get("enable", True) and not isinstance(
                instances.get(model["id"]), ProviderOpenAICodex
            ):
                raise RuntimeError("The subscription model could not be reloaded.")
    finally:
        if selected_id in instances:
            manager.curr_provider_inst = instances[selected_id]
    try:
        _remove_image_bridge = astrbot_image_bridge.install(PROVIDER_TYPE)
    except Exception as exc:  # noqa: BLE001 - optional image integration must not block chat
        if _remove_image_bridge is not None:
            _remove_image_bridge()
            _remove_image_bridge = None
        detail = (
            str(exc)
            if isinstance(exc, astrbot_image_bridge.ImageBridgeCompatibilityError)
            else type(exc).__name__
        )
        logger.warning("OpenAI Subscribe image bridge disabled: %s", detail)


def terminate() -> None:
    """Remove AstrBot integration hooks when the plugin is unloaded."""
    global _remove_source_guard, _remove_image_bridge
    if _remove_image_bridge is not None:
        _remove_image_bridge()
        _remove_image_bridge = None
    if _remove_source_guard is not None and _startup_error is None:
        _remove_source_guard()
        _remove_source_guard = None
