"""最小冒烟验证：插件能否通过真实 `data.plugins.` 命名空间注册 provider，
且 WebUI 元数据构建（config_service 读取的 provider_registry）能看到它。

从仓库根运行（需 AstrBot 仓库 venv，见 AGENTS.md）：
    /Users/wcqqq1214/Project/AstrBot/.venv/bin/python \
        /Users/wcqqq1214/Project/astrbot_plugin_openai_oauth/tests/smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 解析 AstrBot 仓库根（本文件位于 Project/astrbot_plugin_openai_oauth/tests/ 下）
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AstrBot")
)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)  # 使 `data` 命名空间包可解析

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
    print("=== 1. 插件加载前 provider 不应存在 ===")
    check(PROVIDER_TYPE not in provider_cls_map, "provider 未注册（加载前）")

    print("\n=== 2. 通过真实命名空间导入插件（模拟 StarManager.load 的导入路径） ===")
    # 与 star_manager.load() 的 `data.plugins.<root_dir_name>.main` 完全一致
    import importlib

    module = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
    runtime = importlib.import_module(f"{module.__package__}.src.runtime")
    check(module is not None, "data.plugins.astrbot_plugin_openai_oauth.main 导入成功")
    check(
        PROVIDER_TYPE == runtime._PROVIDER_TYPE,
        f"test constant matches the runtime provider type ({runtime._PROVIDER_TYPE})",
    )

    print("\n=== 3. provider 已进入注册表 ===")
    check(PROVIDER_TYPE in provider_cls_map, "provider_cls_map 包含 provider")
    meta = provider_cls_map.get(PROVIDER_TYPE)
    if meta is not None:
        check(bool(meta.desc), f"描述非空: {meta.desc[:40]}...")
        check(
            meta.provider_display_name == "OpenAI Subscribe",
            f"provider_display_name: {meta.provider_display_name}",
        )
        check(meta.default_config_tmpl is not None, "default_config_tmpl 存在")
        check(
            (meta.default_config_tmpl or {}).get("provider") == "openai",
            "config 模板带 provider=openai（前端图标查找）",
        )
        check(
            (meta.default_config_tmpl or {}).get("provider_type") == "chat_completion",
            "config 模板带 provider_type=chat_completion（前端 tab 过滤）",
        )
        check(
            "key" in (meta.default_config_tmpl or {}),
            "config 模板包含 key 字段",
        )
        check(meta.cls_type is not None, "cls_type 已绑定")
    else:
        check(False, "provider_cls_map 中无 provider 元数据")

    print("\n=== 4. WebUI 元数据构建（config_service）读到的同一份列表能看到它 ===")
    check(
        any(getattr(p, "type", None) == PROVIDER_TYPE for p in cfg_registry),
        "config_service 的 provider_registry 包含 provider",
    )
    check(
        cfg_registry is provider_registry,
        "config_service 与 register 模块是同一份列表对象（同一进程共享）",
    )

    print("\n=== 5. 插件 Star 是否注册成功 ===")
    from astrbot.core.star.star import star_map

    registered = [k for k in star_map if "astrbot_plugin_openai_oauth" in k]
    check(bool(registered), f"star_map 含插件注册项: {registered}")
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
    check(reload_ok, "热重载后重新导入成功（无重复注册错误）")
    if not reload_ok:
        check(False, f"重复注册报错：{reload_error}")
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

    print("\n=== 8. README documents the Plugin Page workflow ===")
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    for fname in ("README.md", "README_en.md"):
        with open(os.path.join(repo_root, fname), encoding="utf-8") as fh:
            readme_src = fh.read()
        check(
            "Plugin Page" in readme_src or "插件 Page" in readme_src,
            f"{fname} names the Plugin Page",
        )
        check("openai_login" in readme_src, f"{fname} documents the command fallback")
        check("HTTPS" in readme_src, f"{fname} recommends HTTPS")

    print()
    if FAILED:
        print(f"=== 冒烟验证失败：{len(FAILED)} 项 ===")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("=== 冒烟验证全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
