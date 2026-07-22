"""Pilot-safe SQLite backup/restore utility with integrity and row-count proof.

This is intentionally scoped to the current pilot database.  It is not a claim
of multi-region or production-grade disaster recovery.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable


CRITICAL_TABLES = (
    "companies",
    "company_knowledge",
    "knowledge_sources",
    "leads",
    "messages",
    "commercial_decision_lineage",
    "commercial_events",
    "workspace_suggested_replies",
    "system_events",
)


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def integrity_check(path: Path) -> str:
    with closing(_connect(path)) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "missing")


def table_counts(path: Path, tables: Iterable[str] = CRITICAL_TABLES) -> dict[str, int | None]:
    with closing(_connect(path)) as connection:
        existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) if table in existing else None
            for table in tables
        }


def backup_database(source: Path, destination: Path, *, overwrite: bool = False) -> dict:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    if source == destination:
        raise ValueError("Backup destination must differ from the source database.")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Backup already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    try:
        with closing(_connect(source)) as source_db, closing(_connect(temporary)) as destination_db:
            source_db.backup(destination_db)
        if integrity_check(temporary) != "ok":
            raise RuntimeError("Backup integrity check failed.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "operation": "backup",
        "source": str(source),
        "destination": str(destination),
        "integrity": integrity_check(destination),
        "row_counts": table_counts(destination),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def restore_database(backup: Path, destination: Path, *, overwrite: bool = False) -> dict:
    backup = backup.resolve()
    destination = destination.resolve()
    if integrity_check(backup) != "ok":
        raise RuntimeError("Refusing to restore an invalid backup.")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Restore destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with closing(_connect(backup)) as backup_db, closing(_connect(destination)) as restored_db:
        backup_db.backup(restored_db)
    result = {
        "operation": "restore",
        "source": str(backup),
        "destination": str(destination),
        "integrity": integrity_check(destination),
        "row_counts": table_counts(destination),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if result["integrity"] != "ok":
        raise RuntimeError("Restored database integrity check failed.")
    return result


def rehearse(source: Path, work_dir: Path) -> dict:
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    backup_path = work_dir / "pilot-backup.sqlite3"
    restored_path = work_dir / "pilot-restored.sqlite3"
    backup_result = backup_database(source, backup_path, overwrite=True)
    restore_result = restore_database(backup_path, restored_path, overwrite=True)
    source_counts = table_counts(source.resolve())
    counts_match = source_counts == restore_result["row_counts"]
    if not counts_match:
        raise RuntimeError("Restored critical row counts do not match the source database.")
    return {
        "operation": "rehearsal",
        "source": str(source.resolve()),
        "backup": backup_result,
        "restore": restore_result,
        "source_row_counts": source_counts,
        "counts_match": counts_match,
        "critical_read_verified": restore_result["integrity"] == "ok" and counts_match,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "SQLite backup is single-region and operator-managed.",
            "No point-in-time recovery or off-site retention is provided by this utility.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="VELOR pilot SQLite backup and restore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    rehearsal = subparsers.add_parser("rehearse")
    rehearsal.add_argument("--database", required=True, type=Path)
    rehearsal.add_argument("--work-dir", required=True, type=Path)
    rehearsal.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    if args.command == "rehearse":
        result = rehearse(args.database, args.work_dir)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.manifest:
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
