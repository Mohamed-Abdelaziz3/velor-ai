#!/usr/bin/env python3
"""Verify that the active environment exactly matches VELOR's Python locks."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[[^]]+\])?==(?P<version>[^;\s]+)"
    r"(?:;\s*(?P<marker>.+))?$"
)
PLATFORM_MARKER = re.compile(r'^sys_platform\s*(?P<operator>==|!=)\s*"(?P<value>[^"]+)"$')


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def marker_applies(marker: str | None) -> bool:
    if marker is None:
        return True
    match = PLATFORM_MARKER.match(marker)
    if not match:
        raise ValueError(f"unsupported lock marker: {marker}")
    equal = sys.platform == match.group("value")
    return equal if match.group("operator") == "==" else not equal


def expected_versions(paths: list[Path]) -> dict[str, tuple[str, str]]:
    expected: dict[str, tuple[str, str]] = {}
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-")):
                continue
            match = PIN.match(stripped)
            if not match:
                raise ValueError(f"{path.name}:{number}: invalid exact pin")
            if marker_applies(match.group("marker")):
                expected[normalize(match.group("name"))] = (
                    match.group("name"),
                    match.group("version"),
                )
    return expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-only", action="store_true")
    args = parser.parse_args()
    locks = [ROOT / "backend" / "requirements.lock"]
    if not args.runtime_only:
        locks.append(ROOT / "backend" / "requirements-dev.lock")

    errors: list[str] = []
    try:
        expected = expected_versions(locks)
    except (OSError, ValueError) as exc:
        print(f"Python lock verification failed: {exc}", file=sys.stderr)
        return 1
    for _, (package, expected_version) in sorted(expected.items()):
        try:
            installed_version = version(package)
        except PackageNotFoundError:
            errors.append(f"{package}: missing")
            continue
        if installed_version != expected_version:
            errors.append(
                f"{package}: expected {expected_version}, installed {installed_version}"
            )
    if errors:
        print(f"Python lock verification failed with {len(errors)} issue(s):", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Python lock verification passed: {len(expected)} active package pins match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
