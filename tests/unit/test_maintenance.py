"""Offline tests for the scheduled Codex compatibility reminder."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "scripts"
    / "check_codex_release.py"
)
spec = importlib.util.spec_from_file_location("codex_release_check", SCRIPT)
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


class ReleaseTests(unittest.TestCase):
    def test_numeric_version_comparison(self):
        for latest, current, expected in (
            ("0.10.0", "0.9.0", True),
            ("0.9.0", "0.10.0", False),
            ("0.10.0", "0.10.0", False),
        ):
            release = {
                "tag_name": f"rust-v{latest}",
                "draft": False,
                "prerelease": False,
            }
            self.assertEqual(
                release_check.compare_release(release, current), (expected, latest)
            )

    def test_untrusted_or_prerelease_metadata_is_rejected(self):
        for release in (
            {},
            {"tag_name": "rust-v0.9.0", "draft": True, "prerelease": False},
            {"tag_name": "rust-v0.9.0-alpha.1", "draft": False, "prerelease": True},
            {
                "tag_name": "rust-v0.9.0\n::error::injected",
                "draft": False,
                "prerelease": False,
            },
        ):
            with self.assertRaises(ValueError):
                release_check.compare_release(release, "0.8.0")

    def test_constant_is_read_without_loading_oauth(self):
        self.assertRegex(release_check.built_in_version(), r"^\d+\.\d+\.\d+$")
