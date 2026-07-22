#!/usr/bin/env python3
"""Fail closed when public-source candidates contain local artifacts or secrets.

The checker never prints matched values. It is intentionally stdlib-only so it
can run before project dependencies are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MAX_SCAN_BYTES = 25 * 1024 * 1024
FORBIDDEN_DIRS = {
    ".git",
    ".pytest_cache",
    ".pytest_tmp",
    "__pycache__",
    "htmlcov",
    "logs",
    "node_modules",
    "sessions",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".log",
    ".sqlite",
    ".sqlite3",
}
ALLOWED_SYNTHETIC_SECRET_SHA256 = {
    # Deliberately fake provider-token fixtures used by automated tests. Store
    # only digests here so the checker never has to echo or duplicate values.
    "0ba24659502b0f2c4b0c0d6c39072a05763369caebe3208a5f80c874dd7c7e81",
    "afeaad62ab468f7f0a57f853f4e9053ca738eff8a873e0805358f0ae9b9e7fdc",
    "ee4f33aefca76554519e71e6e83d89889a71d97ad8a41024065b25063698c4e2",
    "f81fd9d719ee9cb9ae94069fa055334e4b7fce8f0070589e93a1a7f3d1a55c54",
}
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "GitHub token": re.compile(rb"(?:github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,})"),
    "Google API key": re.compile(rb"AIza[A-Za-z0-9_-]{30,}"),
    "Groq token": re.compile(rb"gsk_[A-Za-z0-9_-]{20,}"),
    "OpenAI-style token": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "Slack token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "Stripe live key": re.compile(rb"(?:sk|rk)_live_[A-Za-z0-9]{20,}"),
    "Meta access token": re.compile(rb"EAA[A-Za-z0-9]{45,}"),
}
REQUIRED_EMPTY_ENV_KEYS = {
    "GROQ_API_KEY",
    "GOOGLE_CLIENT_ID",
    "JWT_SECRET",
    "META_APP_SECRET",
    "META_COMPANY_ID",
    "META_GRAPH_API_TOKEN",
    "META_PHONE_NUMBER_ID",
    "NODE_INTERNAL_SECRET",
    "VELOR_META_VERIFY_TOKEN",
    "VITE_GOOGLE_CLIENT_ID",
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def candidate_paths(errors: list[str]) -> list[Path]:
    result = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if result.returncode:
        errors.append("Git could not enumerate source candidates")
        return []
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        path = ROOT / os.fsdecode(raw)
        if path.is_file():
            paths.append(path)
    return sorted(paths, key=lambda item: rel(item).casefold())


def check_candidate_path(path: Path, errors: list[str]) -> None:
    relative = rel(path)
    parts = {part.casefold() for part in Path(relative).parts}
    name = path.name.casefold()
    suffixes = "".join(path.suffixes[-2:]).casefold()

    if any(part.startswith(".venv") for part in parts):
        errors.append(f"{relative}: virtual environment is a source candidate")
    if parts & FORBIDDEN_DIRS:
        errors.append(f"{relative}: runtime/cache directory is a source candidate")
    if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
        errors.append(f"{relative}: runtime environment file is a source candidate")
    if path.suffix.casefold() in FORBIDDEN_SUFFIXES or suffixes in FORBIDDEN_SUFFIXES:
        errors.append(f"{relative}: database or log artifact is a source candidate")
    if name in {"api_keys.json", "google_keys.json", "credentials.json", "service-account.json"}:
        errors.append(f"{relative}: credential artifact is a source candidate")


def scan_candidate(path: Path, errors: list[str]) -> int:
    relative = rel(path)
    try:
        size = path.stat().st_size
        if size > MAX_SCAN_BYTES:
            errors.append(f"{relative}: exceeds the 25 MiB secret-scan limit")
            return 0
        data = path.read_bytes()
    except OSError:
        errors.append(f"{relative}: could not be read for secret scanning")
        return 0

    approved = 0
    for kind, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(data):
            digest = hashlib.sha256(match.group(0)).hexdigest()
            if digest in ALLOWED_SYNTHETIC_SECRET_SHA256:
                approved += 1
                continue
            line = data.count(b"\n", 0, match.start()) + 1
            errors.append(f"{relative}:{line}: possible {kind}; value suppressed")
    return approved


def parse_env_example(path: Path, errors: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        errors.append(f"{rel(path)}: required environment example is unreadable")
        return values
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        values[key] = value
        if key in REQUIRED_EMPTY_ENV_KEYS and value:
            errors.append(f"{rel(path)}:{number}: {key} must be empty in public examples")
    return values


def check_env_examples(errors: list[str]) -> None:
    required = [
        ROOT / "backend" / ".env.example",
        ROOT / "backend" / ".env.verification.example",
        ROOT / "frontend" / ".env.example",
        ROOT / "frontend" / ".env.verification.example",
    ]
    parsed: dict[Path, dict[str, str]] = {}
    for path in required:
        if not path.is_file():
            errors.append(f"{rel(path)}: required environment example is missing")
            continue
        parsed[path] = parse_env_example(path, errors)

    for path in required[:2]:
        values = parsed.get(path, {})
        for engine in (
            "PUBLIC_WEB_CHAT_RESPONSE_ENGINE",
            "WHATSAPP_RESPONSE_ENGINE",
            "EXTERNAL_API_RESPONSE_ENGINE",
        ):
            if values.get(engine) != "v2":
                errors.append(f"{rel(path)}: {engine} must use the current v2 path")
        for flag in (
            "ALLOW_SYNTHETIC_DEMO_SEED",
            "ENABLE_LEGACY_INTELLIGENCE_WORKER",
            "ENABLE_META_WEBHOOK",
        ):
            if values.get(flag, "").casefold() not in {"0", "false"}:
                errors.append(f"{rel(path)}: {flag} must fail closed")


def requirement_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "-")):
        return None
    match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?", stripped)
    return match.group(1).replace("_", "-").casefold() if match else None


def check_python_locks(errors: list[str]) -> None:
    runtime_spec = ROOT / "backend" / "requirements.txt"
    runtime_lock = ROOT / "backend" / "requirements.lock"
    dev_lock = ROOT / "backend" / "requirements-dev.lock"
    for path in (runtime_spec, runtime_lock, dev_lock):
        if not path.is_file():
            errors.append(f"{rel(path)}: required Python dependency file is missing")
            return

    spec_names = {
        name
        for line in runtime_spec.read_text(encoding="utf-8-sig").splitlines()
        if (name := requirement_name(line))
    }
    lock_names: set[str] = set()
    exact_pin = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?==[^;\s]+(?:;\s*.+)?$")
    for number, line in enumerate(runtime_lock.read_text(encoding="utf-8-sig").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not exact_pin.match(stripped):
            errors.append(f"{rel(runtime_lock)}:{number}: dependency is not exactly pinned")
        name = requirement_name(stripped)
        if name:
            lock_names.add(name)
    for missing in sorted(spec_names - lock_names):
        errors.append(f"{rel(runtime_lock)}: direct dependency {missing} is not pinned")

    dev_text = dev_lock.read_text(encoding="utf-8-sig")
    if "-r requirements.lock" not in dev_text.splitlines():
        errors.append(f"{rel(dev_lock)}: must include requirements.lock")
    dev_names = {name for line in dev_text.splitlines() if (name := requirement_name(line))}
    for required in ("pytest", "pytest-asyncio"):
        if required not in dev_names:
            errors.append(f"{rel(dev_lock)}: {required} is not pinned")


def check_node_locks(errors: list[str]) -> None:
    for directory in (ROOT / "backend", ROOT / "frontend"):
        package_path = directory / "package.json"
        lock_path = directory / "package-lock.json"
        try:
            package = json.loads(package_path.read_text(encoding="utf-8-sig"))
            lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"{rel(directory)}: package manifest or lockfile is invalid")
            continue
        if lock.get("lockfileVersion") != 3:
            errors.append(f"{rel(lock_path)}: lockfileVersion must be 3")
        root_package = lock.get("packages", {}).get("", {})
        for key in ("dependencies", "devDependencies", "optionalDependencies"):
            if package.get(key, {}) != root_package.get(key, {}):
                errors.append(f"{rel(lock_path)}: root {key} do not match package.json")


def check_ignore_contract(errors: list[str]) -> None:
    must_ignore = [
        ".env",
        "backend/.env",
        "frontend/.env",
        "backend/sessions/example/session.json",
        "backend/local.db",
        "backend/runtime.log",
        ".venv-local/pyvenv.cfg",
        "backend/.pytest_tmp/state",
    ]
    must_include = [
        ".env.example",
        "backend/.env.example",
        "backend/.env.verification.example",
        "frontend/.env.example",
        "frontend/.env.verification.example",
    ]
    for path in must_ignore:
        if git("check-ignore", "--no-index", "-q", path).returncode != 0:
            errors.append(f".gitignore: {path} is not ignored")
    for path in must_include:
        if git("check-ignore", "--no-index", "-q", path).returncode == 0:
            errors.append(f".gitignore: safe example {path} is unexpectedly ignored")


def summarize_tree(path: Path) -> tuple[int, int, int]:
    count = size = failures = 0
    if not path.exists():
        return count, size, failures
    if path.is_file():
        try:
            return 1, path.stat().st_size, 0
        except OSError:
            return 0, 0, 1
    walk_failures: list[OSError] = []
    for current, _, files in os.walk(
        path,
        followlinks=False,
        onerror=walk_failures.append,
    ):
        for name in files:
            count += 1
            try:
                size += (Path(current) / name).stat().st_size
            except OSError:
                failures += 1
    return count, size, failures + len(walk_failures)


def inventory_local_artifacts() -> None:
    categories: dict[str, list[Path]] = {
        "environment files": [],
        "databases": [],
        "logs": [],
        "sessions": [ROOT / "backend" / "sessions"],
        "virtual environments": [
            path for path in ROOT.iterdir() if path.is_dir() and path.name.startswith(".venv")
        ],
        "test caches": [ROOT / ".pytest_cache", ROOT / "backend" / ".pytest_tmp"],
    }
    for directory in (ROOT, ROOT / "backend", ROOT / "frontend"):
        if directory.is_dir():
            inventory = categories["environment files"]
            inventory.extend(
                path
                for path in directory.glob(".env*")
                if path.is_file() and not path.name.endswith(".example")
            )
    skip = {".git", "node_modules", "sessions"}
    repository_walk_failures: list[OSError] = []
    for current, dirs, files in os.walk(
        ROOT,
        followlinks=False,
        onerror=repository_walk_failures.append,
    ):
        dirs[:] = [
            name
            for name in dirs
            if name not in skip and not name.startswith(".venv") and name not in {".pytest_cache", ".pytest_tmp"}
        ]
        for name in files:
            path = Path(current) / name
            lowered = name.casefold()
            if lowered.endswith((".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")):
                categories["databases"].append(path)
            elif lowered.endswith(".log"):
                categories["logs"].append(path)

    print("Local artifact inventory (content and names suppressed):")
    for category, paths in categories.items():
        total_count = total_size = total_failures = 0
        for path in dict.fromkeys(paths):
            count, size, failures = summarize_tree(path)
            total_count += count
            total_size += size
            total_failures += failures
        print(f"- {category}: {total_count} files, {total_size} bytes, {total_failures} read errors")
    print(
        "- repository walk gaps: 0 files, 0 bytes, "
        f"{len(repository_walk_failures)} read errors"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory-local",
        action="store_true",
        help="also print aggregate local-artifact counts without names or contents",
    )
    args = parser.parse_args()

    errors: list[str] = []
    paths = candidate_paths(errors)
    approved = 0
    for path in paths:
        check_candidate_path(path, errors)
        approved += scan_candidate(path, errors)
    check_env_examples(errors)
    check_python_locks(errors)
    check_node_locks(errors)
    check_ignore_contract(errors)

    if args.inventory_local:
        inventory_local_artifacts()
    if errors:
        print(f"Repository hygiene check failed with {len(errors)} issue(s):", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        f"Repository hygiene check passed: {len(paths)} source candidates scanned; "
        f"{approved} approved synthetic fixture match(es)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
