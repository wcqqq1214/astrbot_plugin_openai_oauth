"""Compare the built-in Codex version with GitHub's latest stable release JSON."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def built_in_version() -> str:
    for node in ast.parse((ROOT / "src" / "oauth.py").read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CODEX_CLIENT_VERSION"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value):
                return value
    raise ValueError("Missing built-in Codex version")


def compare_release(release: dict, current: str) -> tuple[bool, str]:
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("Expected a published stable Codex release")
    match = re.fullmatch(r"rust-v(\d+\.\d+\.\d+)", str(release.get("tag_name", "")))
    if match is None:
        raise ValueError("Unexpected Codex release tag")
    latest = match.group(1)
    outdated = tuple(map(int, latest.split("."))) > tuple(map(int, current.split(".")))
    return outdated, latest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_json", type=Path)
    args = parser.parse_args()
    try:
        release = json.loads(args.release_json.read_text())
        if not isinstance(release, dict):
            raise TypeError("Expected a release object")
        current = built_in_version()
        outdated, latest = compare_release(release, current)
    except (OSError, ValueError, TypeError, SyntaxError):
        print("::error::Could not validate the Codex release metadata.")
        return 2
    message = f"Built-in Codex version: {current}; latest stable release: {latest}."
    if outdated:
        message += " Review protocol compatibility, fallback models and image model before updating."
        print(f"::warning::{message}")
    else:
        print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")
    # A failed maintenance job makes version drift visible in workflow notifications.
    return int(outdated)


if __name__ == "__main__":
    raise SystemExit(main())
