"""Run each integration script against this checkout with isolated Codex auth."""

from __future__ import annotations

import importlib.abc
import importlib.util
import os
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class CheckoutFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "data.plugins.astrbot_plugin_openai_oauth":
            return importlib.util.spec_from_file_location(
                fullname,
                PLUGIN_ROOT / "__init__.py",
                submodule_search_locations=[str(PLUGIN_ROOT)],
            )
        return None


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--case":
        test = PLUGIN_ROOT / "tests" / sys.argv[2]
        sys.meta_path.insert(0, CheckoutFinder())
        sys.argv = [str(test)]
        runpy.run_path(str(test), run_name="__main__")
        return 0
    cases = sys.argv[1:] or [
        p.name for p in sorted((PLUGIN_ROOT / "tests").glob("*_test.py"))
    ]
    failed = []
    with tempfile.TemporaryDirectory(prefix="astrbot-test-codex-") as auth_home:
        env = {**os.environ, "CODEX_HOME": auth_home}
        for case in cases:
            print(f"Running {case}", flush=True)
            result = subprocess.run(
                [sys.executable, __file__, "--case", case], env=env, check=False
            )
            if result.returncode:
                failed.append(case)
    print(f"{len(cases) - len(failed)}/{len(cases)} test scripts passed", flush=True)
    if failed:
        print("Failed: " + ", ".join(failed), flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
