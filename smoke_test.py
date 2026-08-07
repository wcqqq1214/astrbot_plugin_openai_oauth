"""最小冒烟验证：插件能否通过真实 `data.plugins.` 命名空间注册 provider，
且 WebUI 元数据构建（config_service 读取的 provider_registry）能看到它。

从仓库根运行：
    .venv/bin/python /Users/wcqqq1214/Project/astrbot_plugin_openai_oauth/smoke_test.py
"""

from __future__ import annotations

import os
import sys

# 解析 AstrBot 仓库根（本文件位于 Project/astrbot_plugin_openai_oauth/ 下）
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "AstrBot"))
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


def check(cond: bool, msg: str) -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {msg}")
    if not cond:
        FAILED.append(msg)


def main() -> int:
    print("=== 1. 插件加载前 provider 不应存在 ===")
    check("openai_codex" not in provider_cls_map, "openai_codex 未注册（加载前）")

    print("\n=== 2. 通过真实命名空间导入插件（模拟 StarManager.load 的导入路径） ===")
    # 与 star_manager.load() 的 `data.plugins.<root_dir_name>.main` 完全一致
    import importlib

    module = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
    check(module is not None, "data.plugins.astrbot_plugin_openai_oauth.main 导入成功")

    print("\n=== 3. provider 已进入注册表 ===")
    check("openai_codex" in provider_cls_map, "provider_cls_map 包含 openai_codex")
    meta = provider_cls_map.get("openai_codex")
    if meta is not None:
        check(bool(meta.desc), f"描述非空: {meta.desc[:40]}...")
        check(
            meta.provider_display_name == "OpenAI 订阅 (ChatGPT 登录)",
            f"provider_display_name: {meta.provider_display_name}",
        )
        check(meta.default_config_tmpl is not None, "default_config_tmpl 存在")
        check(
            "key" in (meta.default_config_tmpl or {}),
            "config 模板包含 key 字段",
        )
        check(meta.cls_type is not None, "cls_type 已绑定")
    else:
        check(False, "provider_cls_map 中无 openai_codex 元数据")

    print("\n=== 4. WebUI 元数据构建（config_service）读到的同一份列表能看到它 ===")
    check(
        any(getattr(p, "type", None) == "openai_codex" for p in cfg_registry),
        "config_service 的 provider_registry 包含 openai_codex",
    )
    check(
        cfg_registry is provider_registry,
        "config_service 与 register 模块是同一份列表对象（同一进程共享）",
    )

    print("\n=== 5. 插件 Star 是否注册成功 ===")
    from astrbot.core.star.star import star_map

    registered = [k for k in star_map if "astrbot_plugin_openai_oauth" in k]
    check(bool(registered), f"star_map 含插件注册项: {registered}")

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
