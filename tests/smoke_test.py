"""Minimal smoke test: the plugin registers its provider through the real
`data.plugins.` namespace, and WebUI metadata (the provider registry that
config_service reads) can see it.

Run with the AstrBot checkout's virtualenv (see docs/development.md):
    /path/to/AstrBot/.venv/bin/python tests/run_tests.py smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Locate the AstrBot checkout (next to this repository unless ASTRBOT_ROOT is set).
REPO_ROOT = os.path.abspath(
    os.environ.get("ASTRBOT_ROOT")
    or os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)  # Make the `data` namespace package importable.

from astrbot.core.provider.register import (
    provider_cls_map,
    provider_registry,
)
from astrbot.dashboard.services.config_service import (
    provider_registry as cfg_registry,
)

FAILED = []

# Check this pre-import constant against the runtime after loading the plugin.
PROVIDER_TYPE = "OpenAI Subscribe"


def check(cond: bool, msg: str) -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {msg}")
    if not cond:
        FAILED.append(msg)


def check_entry_point(module) -> None:
    from astrbot.core.star.register.star_handler import star_handlers_registry
    from astrbot.core.star.star import star_map

    prefix = module.__package__
    registered = [name for name in star_map if name.startswith(prefix + ".")]
    check(registered == [module.__name__], "the plugin is registered only at main")
    check(
        star_map[module.__name__].star_cls_type is module.OpenAI_OAuth_Plugin,
        "AstrBot resolves the current entry-point class",
    )
    handlers = [
        item
        for item in star_handlers_registry
        if item.handler_module_path.startswith(prefix + ".")
    ]
    check(
        {item.handler_name for item in handlers} == {"usage", "effort", "openai_login"}
        and len(handlers) == 3
        and all(
            item.handler_module_path == module.__name__
            and item.handler is getattr(module.OpenAI_OAuth_Plugin, item.handler_name)
            for item in handlers
        ),
        "all commands belong to the current entry point without duplicates",
    )
    check(
        sys.modules[prefix].ProviderOpenAICodex is module.ProviderOpenAICodex
        and module.ProviderOpenAICodex
        is sys.modules[f"{prefix}.src.provider"].ProviderOpenAICodex,
        "package and main preserve the provider export",
    )


def main() -> int:
    print("=== 1. The provider is absent before the plugin loads ===")
    check(
        PROVIDER_TYPE not in provider_cls_map,
        "provider is not registered before loading",
    )

    print("\n=== 2. Import through the real namespace (as StarManager.load does) ===")
    # Exactly how star_manager.load() names `data.plugins.<root_dir_name>.main`.
    import importlib

    module = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
    runtime = importlib.import_module(f"{module.__package__}.src.runtime")
    check(module is not None, "data.plugins.astrbot_plugin_openai_oauth.main imports")
    check(
        PROVIDER_TYPE == runtime.PROVIDER_TYPE,
        f"test constant matches the runtime provider type ({runtime.PROVIDER_TYPE})",
    )

    print("\n=== 3. The provider is registered ===")
    check(PROVIDER_TYPE in provider_cls_map, "provider_cls_map contains the provider")
    meta = provider_cls_map.get(PROVIDER_TYPE)
    if meta is not None:
        check(bool(meta.desc), f"description is set: {meta.desc[:40]}...")
        check(
            meta.provider_display_name == "OpenAI Subscribe",
            f"provider_display_name: {meta.provider_display_name}",
        )
        check(meta.default_config_tmpl is not None, "default_config_tmpl exists")
        check(
            (meta.default_config_tmpl or {}).get("provider") == "openai",
            "config template has provider=openai (dashboard icon lookup)",
        )
        check(
            (meta.default_config_tmpl or {}).get("provider_type") == "chat_completion",
            "config template has provider_type=chat_completion (dashboard tab filter)",
        )
        check(
            "key" in (meta.default_config_tmpl or {}),
            "config template has a key field",
        )
        check(meta.cls_type is not None, "cls_type is bound")
    else:
        check(False, "provider_cls_map has no provider metadata")

    print("\n=== 4. WebUI metadata (config_service) sees the same registry ===")
    check(
        any(getattr(p, "type", None) == PROVIDER_TYPE for p in cfg_registry),
        "config_service provider_registry contains the provider",
    )
    check(
        cfg_registry is provider_registry,
        "config_service and the register module share one registry object",
    )

    print("\n=== 5. The plugin Star is registered ===")
    from astrbot.core.star.star import star_map

    registered = [k for k in star_map if "astrbot_plugin_openai_oauth" in k]
    check(bool(registered), f"star_map has the plugin: {registered}")
    check_entry_point(module)

    print(
        "\n=== 6. Hot reload: provider registration is idempotent and refreshes class ==="
    )
    # Exercise AstrBot's actual unbinding and nested-module cleanup before reload.
    from astrbot.core.star.star_manager import PluginManager

    first_cls = provider_cls_map[PROVIDER_TYPE].cls_type
    prefix = "data.plugins.astrbot_plugin_openai_oauth"
    metadata = star_map[module.__name__]
    metadata.root_dir_name = "astrbot_plugin_openai_oauth"
    metadata.reserved = False
    manager = object.__new__(PluginManager)
    asyncio.run(manager._unbind_plugin(metadata.name, module.__name__))
    check(
        not any(key == prefix or key.startswith(prefix + ".") for key in sys.modules),
        "AstrBot unload removes the entry point and all src modules",
    )
    try:
        reloaded = importlib.import_module(f"{prefix}.main")
        reload_ok = True
    except ValueError as exc:
        reload_ok = False
        reload_error = str(exc)
    check(
        reload_ok, "re-import after hot reload succeeds without duplicate registration"
    )
    if not reload_ok:
        check(False, f"duplicate registration failed: {reload_error}")
    check(
        provider_cls_map[PROVIDER_TYPE].cls_type is not first_cls,
        "provider metadata points to the newly imported class after reload",
    )
    if reload_ok:
        check_entry_point(reloaded)

    print("\n=== 7. Native Plugin Page and server-side persistence ===")
    root = Path(__file__).resolve().parents[1]
    login_src = (root / "src" / "login.py").read_text(encoding="utf-8")
    plugin_src = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [root / "main.py", *sorted((root / "src").glob("*.py"))]
    )
    check(
        "_persist_login_credentials" in login_src and "save_creds" not in plugin_src,
        "credentials are written back only by the server-side device session",
    )
    check("_LOGIN_PAGE_HTML" not in plugin_src, "standalone login HTML is removed")

    print("\n=== 8. README documents the Plugin Views workflow ===")
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    for fname in ("README.md", "README_en.md"):
        with open(os.path.join(repo_root, fname), encoding="utf-8") as fh:
            readme_src = fh.read()
        check(
            "Plugin Views → providers" in readme_src,
            f"{fname} documents the Plugin Views providers entry",
        )
        check("openai_login" in readme_src, f"{fname} documents the command fallback")
        check("HTTPS" in readme_src, f"{fname} recommends HTTPS")

    print()
    if FAILED:
        print(f"=== Smoke test failed: {len(FAILED)} check(s) ===")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("=== Smoke test passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
