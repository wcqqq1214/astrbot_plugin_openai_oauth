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

from . import oauth, source_editor
from .credential_seal import FernetCredentialSealer
from .credential_store import CredentialError
from .local_codex import LocalCodexStore
from .local_codex import LocalCredentialCoordinator as CredentialCoordinator
from .oauth import (
    CODEX_BASE,
    DEFAULT_ORIGINATOR,
)

_REFRESH_SKEW_SECONDS = 120
_PROVIDER_TYPE = "OpenAI Subscribe"
_PLUGIN_NAME = "astrbot_plugin_openai_oauth"
# Optional override, e.g. to keep the key on a separate secret mount.
_CREDENTIAL_KEY_ENV = "OPENAI_OAUTH_CREDENTIAL_KEY_FILE"
_COORDINATOR_ATTR = "_astrbot_openai_oauth_credential_coordinator"

# Bound by the entry point; all consumers resolve credentials through this module.
_config_mgr: Any = None
_credential_coordinator: CredentialCoordinator | None = None
_local_codex_store: LocalCodexStore | None = None
_remove_source_guard: Any = None
_credential_sealer: FernetCredentialSealer | None = None


def _credential_key_path() -> Path:
    configured = os.environ.get(_CREDENTIAL_KEY_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path(get_astrbot_plugin_data_path()) / _PLUGIN_NAME / "credential.key"


def _build_default_source_config() -> dict[str, Any]:
    return {
        "provider": "openai",
        "type": _PROVIDER_TYPE,
        "provider_type": "chat_completion",
        "key": "",
        "api_base": CODEX_BASE,
        "proxy": "",
        "originator": DEFAULT_ORIGINATOR,
        # Empty follows the Codex version this plugin and local Codex name.
        "user_agent": "",
        "id": _PROVIDER_TYPE,
        "enable": True,
    }


def _default_provider_template() -> dict[str, Any]:
    source = _build_default_source_config()
    return {
        key: source[key]
        for key in (
            "provider",
            "provider_type",
            "key",
            "model",
            "proxy",
            "originator",
            "user_agent",
        )
        if key in source
    } | {"model": "gpt-5.4-mini"}


def _get_credential_coordinator() -> CredentialCoordinator:
    global _credential_coordinator
    cfg_mgr = _config_mgr
    if cfg_mgr is None:
        raise CredentialError("The AstrBot configuration manager is unavailable.")

    existing = getattr(cfg_mgr, _COORDINATOR_ATTR, None)
    if isinstance(existing, CredentialCoordinator):
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

    coordinator = CredentialCoordinator(
        cfg_mgr,
        provider_type=_PROVIDER_TYPE,
        default_source_id=_PROVIDER_TYPE,
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


def _is_logged_in() -> bool:
    """Return whether the default source has a credential record."""
    try:
        status = _get_credential_coordinator().status()
    except CredentialError:
        return False
    return status.state not in {"not_logged_in", "invalid"}


def configure(context: Context, config: AstrBotConfig) -> None:
    """Bind shared credentials to the current AstrBot configuration manager."""
    global _config_mgr, _local_codex_store, _remove_source_guard, _credential_sealer
    # Account records belong to the plugin view, not the generic source editor.
    fields = CONFIG_METADATA_2["provider_group"]["metadata"]["provider"]["items"]
    for key, field_type in (
        ("oauth_gateway", "bool"),
        ("oauth_accounts", "list"),
        ("oauth_routing", "object"),
    ):
        fields[key] = {"type": field_type, "invisible": True}
    _config_mgr = context.astrbot_config_mgr
    _credential_sealer = FernetCredentialSealer(_credential_key_path())
    _local_codex_store = LocalCodexStore(str(config.get("codex_auth_path", "") or ""))
    oauth.set_codex_home(_local_codex_store.path.parent)
    coordinator = _get_credential_coordinator()
    _remove_source_guard = source_editor.install(coordinator)
    coordinator.legacy_follow_local = config.get("follow_local_codex", True)
    manager = getattr(context, "provider_manager", None)
    if manager is not None:

        def sync_sources(sources: list[dict[str, Any]]) -> None:
            manager.provider_sources_config = sources
            manager.providers_config = coordinator._conf().get("provider", [])

        coordinator.providers.on_change = sync_sources


async def initialize(context: Context) -> None:
    """Migrate storage and replace model instances retained across plugin reloads."""
    from .provider import ProviderOpenAICodex

    coordinator = _get_credential_coordinator()
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
        for model in list(coordinator._conf().get("provider", [])):
            if model["id"] not in instances or not (
                model.get("provider_source_id") == coordinator._default_source_id
                or model.get("type") == _PROVIDER_TYPE
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


def terminate() -> None:
    """Remove the dashboard guard when this plugin is unloaded."""
    global _remove_source_guard
    if _remove_source_guard is not None:
        _remove_source_guard()
        _remove_source_guard = None
