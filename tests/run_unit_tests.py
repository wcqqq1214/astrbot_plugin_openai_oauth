"""Run framework-free regressions without importing AstrBot or real credentials."""

from __future__ import annotations

import importlib.abc
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class NoAstrBot(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "astrbot" or fullname.startswith("astrbot."):
            raise ModuleNotFoundError("Fast tests must not import AstrBot")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    blocker = NoAstrBot()
    sys.meta_path.insert(0, blocker)
    try:
        with (
            tempfile.TemporaryDirectory(prefix="oauth-unit-") as directory,
            patch.dict(
                os.environ,
                {
                    "CODEX_HOME": directory,
                    "OPENAI_OAUTH_CREDENTIAL_KEY_FILE": str(Path(directory) / "key"),
                },
            ),
        ):
            runpy.run_path(
                str(ROOT / "tests" / "credential_store_test.py"), run_name="__main__"
            )
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests" / "unit"))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            return int(not result.wasSuccessful())
    finally:
        sys.meta_path.remove(blocker)


if __name__ == "__main__":
    raise SystemExit(main())
