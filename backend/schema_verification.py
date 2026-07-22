"""Runtime-safe database URL resolution and Alembic/ORM schema checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.schema import MetaData


def resolve_database_url(raw_url: str, backend_dir: Path) -> str:
    """Resolve SQLite file URLs relative to the backend directory, never CWD."""
    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql://", 1)

    url = make_url(raw_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return str(url)

    database_path = Path(url.database)
    if not database_path.is_absolute():
        database_path = (backend_dir / database_path).resolve()
    return str(url.set(database=database_path.as_posix()))


def migration_head(backend_dir: Path) -> str | None:
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


def database_target_for_log(database_url: str) -> str:
    """Return a useful database target without exposing passwords."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return url.database or ":memory:"
    host = url.host or ""
    if url.port:
        host = f"{host}:{url.port}"
    return f"{host}/{url.database or ''}".strip("/")


def schema_status(
    engine: Engine,
    metadata: MetaData,
    backend_dir: Path,
    *,
    require_migration_head: bool,
) -> dict[str, Any]:
    """Check that all mapped tables/columns exist and the DB is at code head."""
    result: dict[str, Any] = {
        "database_reachable": False,
        "schema_compatible": False,
        "migration_revision": None,
        "migration_head": migration_head(backend_dir),
        "missing_tables": [],
        "missing_columns": {},
        "error": None,
    }
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            result["database_reachable"] = True
            for table_name, table in metadata.tables.items():
                if table_name not in tables:
                    result["missing_tables"].append(table_name)
                    continue
                available_columns = {column["name"] for column in inspector.get_columns(table_name)}
                missing = sorted(column.name for column in table.columns if column.name not in available_columns)
                if missing:
                    result["missing_columns"][table_name] = missing

            if "alembic_version" in tables:
                result["migration_revision"] = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
    except Exception as exc:  # pragma: no cover - exercised by startup environments
        result["error"] = str(exc)
        return result

    revision_ok = (
        not require_migration_head
        or result["migration_revision"] == result["migration_head"]
    )
    result["schema_compatible"] = bool(
        result["database_reachable"]
        and not result["missing_tables"]
        and not result["missing_columns"]
        and revision_ok
    )
    return result


def assert_schema_compatible(
    engine: Engine,
    metadata: MetaData,
    backend_dir: Path,
    *,
    require_migration_head: bool,
) -> dict[str, Any]:
    status = schema_status(
        engine,
        metadata,
        backend_dir,
        require_migration_head=require_migration_head,
    )
    if status["schema_compatible"]:
        return status

    details = []
    if status["error"]:
        details.append(f"database error: {status['error']}")
    if status["missing_tables"]:
        details.append(f"missing tables: {', '.join(status['missing_tables'])}")
    if status["missing_columns"]:
        rendered = "; ".join(
            f"{table}({', '.join(columns)})"
            for table, columns in status["missing_columns"].items()
        )
        details.append(f"missing columns: {rendered}")
    if require_migration_head and status["migration_revision"] != status["migration_head"]:
        details.append(
            "migration revision "
            f"{status['migration_revision'] or 'missing'} does not match head {status['migration_head']}"
        )
    raise RuntimeError(
        "Database schema is incompatible. Run 'alembic upgrade head'. " + "; ".join(details)
    )
