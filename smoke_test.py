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

# 步骤 1 在导入前就需要该类型名，因此静态声明；步骤 2 导入后会校验与
# module._PROVIDER_TYPE 一致，避免改名后测试静默失联。
PROVIDER_TYPE = "OpenAI Subscribe"


def check(cond: bool, msg: str) -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {msg}")
    if not cond:
        FAILED.append(msg)


def main() -> int:
    print("=== 1. 插件加载前 provider 不应存在 ===")
    check(PROVIDER_TYPE not in provider_cls_map, "provider 未注册（加载前）")

    print("\n=== 2. 通过真实命名空间导入插件（模拟 StarManager.load 的导入路径） ===")
    # 与 star_manager.load() 的 `data.plugins.<root_dir_name>.main` 完全一致
    import importlib

    module = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")
    check(module is not None, "data.plugins.astrbot_plugin_openai_oauth.main 导入成功")
    check(
        PROVIDER_TYPE == module._PROVIDER_TYPE,
        f"测试常量与 module._PROVIDER_TYPE 一致（{module._PROVIDER_TYPE}）",
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

    print("\n=== 6. 热重载模拟：清 sys.modules 后重导入，注册必须幂等 ===")
    # AstrBot 插件热重载（astrbot run --reload）会清掉 sys.modules 里的插件
    # 模块，却不清 provider_cls_map；重导入会再次执行注册。若注册非幂等，会抛
    # “已经注册” ValueError。这里模拟 _cleanup_plugin_state 并重导入，验证不报错。
    first_cls = provider_cls_map[PROVIDER_TYPE].cls_type
    prefix = "data.plugins.astrbot_plugin_openai_oauth"
    for key in [m for m in sys.modules if m == prefix or m.startswith(prefix + ".")]:
        del sys.modules[key]
    try:
        importlib.import_module(f"{prefix}.main")
        reload_ok = True
    except ValueError as exc:
        reload_ok = False
        reload_error = str(exc)
    check(reload_ok, "热重载后重新导入成功（无重复注册错误）")
    if not reload_ok:
        check(False, f"重复注册报错：{reload_error}")
    check(
        provider_cls_map[PROVIDER_TYPE].cls_type is first_cls,
        "provider 元数据仍是首次导入的类（未重复注册）",
    )

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
