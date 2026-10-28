"""Release consistency checks for CI and the release workflow.

python .github/scripts/release_check.py versions
    Fail unless every place that names the plugin version agrees.
python .github/scripts/release_check.py notes vX.Y.Z
    Print that version's CHANGELOG section; fail if it is missing or empty.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _one(pattern: str, text: str, where: str) -> str:
    found = set(re.findall(pattern, text, flags=re.MULTILINE))
    if len(found) != 1:
        raise SystemExit(f"{where}: expected one version, found {sorted(found)}")
    return found.pop()


def versions() -> dict[str, str]:
    found = {
        "metadata.yaml": _one(
            r"^version:\s*v?([0-9][^\s#]*)", _read("metadata.yaml"), "metadata.yaml"
        ),
        "pyproject.toml": tomllib.loads(_read("pyproject.toml"))["project"]["version"],
        "main.py": _one(
            r'^\s+"(\d+\.\d+\.\d+[^"]*)",\s*\n\)\s*\nclass ',
            _read("main.py"),
            "main.py",
        ),
    }
    lock = tomllib.loads(_read("uv.lock"))
    found["uv.lock"] = next(
        package["version"]
        for package in lock["package"]
        if package["name"] == "astrbot-plugin-openai-oauth"
    )
    for readme in ("README.md", "README_en.md"):
        text = _read(readme)
        for label, pattern in (
            ("release link", r"releases/tag/v([^\"\s)]+)"),
            ("badge", r"badge/version-([^-\s]+)-"),
            ("badge text", r'alt="Version ([^"]+)"'),
        ):
            found[f"{readme} {label}"] = _one(pattern, text, f"{readme} {label}")
    return found


def check_versions() -> int:
    found = versions()
    expected = found["metadata.yaml"]
    mismatched = {where: v for where, v in found.items() if v != expected}
    if mismatched:
        for where, version in sorted(mismatched.items()):
            print(f"::error::{where} names {version}, metadata.yaml names {expected}")
        return 1
    print(f"All {len(found)} version references name {expected}.")
    return 0


def release_notes(tag: str) -> int:
    version = tag.removeprefix("v")
    changelog = _read("CHANGELOG.md")
    match = re.search(
        rf"^## \[v?{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    body = match.group(1).strip() if match else ""
    if not body:
        print(f"::error::CHANGELOG.md has no notes for {tag}", file=sys.stderr)
        return 1
    print(body)
    return 0


def main(argv: list[str]) -> int:
    if argv == ["versions"]:
        return check_versions()
    if len(argv) == 2 and argv[0] == "notes":
        return release_notes(argv[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
