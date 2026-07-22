"""Migration-runtime checks that intentionally use Alembic, never create_all()."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine

from database import Base
from schema_verification import migration_head, resolve_database_url, schema_status


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_relative_sqlite_database_url_is_anchored_to_backend_directory():
    resolved = resolve_database_url("sqlite:///phase_one_relative.db", BACKEND_DIR)
    assert resolved == f"sqlite:///{(BACKEND_DIR / 'phase_one_relative.db').as_posix()}"


def _env_for(db_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
            "ENV": "development",
            "JWT_SECRET": "migration-runtime-test-secret-32-chars-long",
            "NODE_INTERNAL_SECRET": "migration-runtime-internal-secret",
            "REDIS_URL": "redis://127.0.0.1:6399/0",
            "ENABLE_META_WEBHOOK": "false",
            "PUBLIC_WEB_CHAT_RESPONSE_ENGINE": "v2",
            "ALLOW_SYNTHETIC_DEMO_SEED": "1",
        }
    )
    return env


def _run(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND_DIR,
        env=_env_for(db_path),
        text=True,
        capture_output=True,
        timeout=90,
    )


def _upgrade(db_path: Path) -> None:
    result = _run(db_path, "-m", "alembic", "upgrade", "head")
    assert result.returncode == 0, result.stderr


def _seed(db_path: Path) -> str:
    result = _run(db_path, "scripts/seed_trusted_demo_tenant.py")
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_fresh_alembic_database_has_all_orm_required_tables_and_columns(tmp_path):
    db_path = tmp_path / "fresh_parity.db"
    _upgrade(db_path)

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    status = schema_status(engine, Base.metadata, BACKEND_DIR, require_migration_head=True)
    assert status["schema_compatible"], status
    assert status["missing_tables"] == []
    assert status["missing_columns"] == {}
    assert status["migration_revision"] == migration_head(BACKEND_DIR)


def test_fresh_alembic_database_seeds_trusted_arvena_fixture(tmp_path):
    db_path = tmp_path / "fresh_seed.db"
    _upgrade(db_path)
    stdout = _seed(db_path)
    assert '"company_id": "velor_demo_arvena"' in stdout
    assert '"public_chat_slug": "arvena-demo"' in stdout

    with sqlite3.connect(db_path) as connection:
        company_count = connection.execute(
            "SELECT COUNT(*) FROM companies WHERE company_id = ?", ("velor_demo_arvena",)
        ).fetchone()[0]
        knowledge = connection.execute(
            "SELECT products_data FROM company_knowledge WHERE company_id = ?", ("velor_demo_arvena",)
        ).fetchone()
    assert company_count == 1
    products = json.loads(knowledge[0])
    prices = {product["name"]: product["price"] for product in products}
    assert prices["Arvena Ergo One"] == 6900
    assert prices["Arvena Ergo Pro"] == 10900
    assert prices["FocusDesk 120"] == 8500
    assert prices["FocusDesk 140"] == 10500
    assert prices["LiftDesk Electric 120"] == 19900


def test_trusted_arvena_seed_is_idempotent(tmp_path):
    db_path = tmp_path / "idempotent_seed.db"
    _upgrade(db_path)
    _seed(db_path)
    _seed(db_path)

    with sqlite3.connect(db_path) as connection:
        company_count = connection.execute(
            "SELECT COUNT(*) FROM companies WHERE company_id = ?", ("velor_demo_arvena",)
        ).fetchone()[0]
        knowledge_count = connection.execute(
            "SELECT COUNT(*) FROM company_knowledge WHERE company_id = ?", ("velor_demo_arvena",)
        ).fetchone()[0]
        products_data = connection.execute(
            "SELECT products_data FROM company_knowledge WHERE company_id = ?", ("velor_demo_arvena",)
        ).fetchone()[0]
    assert company_count == 1
    assert knowledge_count == 1
    assert len(json.loads(products_data)) == len({row["name"] for row in json.loads(products_data)})


def test_migrated_seeded_database_starts_application_and_resolves_public_session(tmp_path):
    db_path = tmp_path / "migrated_smoke.db"
    _upgrade(db_path)
    _seed(db_path)
    smoke_code = """
import json
from fastapi.testclient import TestClient
from main import app
with TestClient(app) as client:
    health = client.get('/health')
    ready = client.get('/ready')
    session = client.post('/api/public/companies/arvena-demo/session')
    print(json.dumps({'health_status': health.status_code, 'health': health.json(), 'ready_status': ready.status_code, 'ready': ready.json(), 'session_status': session.status_code, 'session': session.json()}))
"""
    result = _run(db_path, "-c", smoke_code)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["health_status"] == 200
    assert payload["health"]["status"] == "ok"
    assert "schema" not in payload["health"]
    assert payload["ready_status"] == 200
    assert payload["ready"]["database"] == "compatible"
    assert payload["ready"]["engine_version"] == "v2"
    assert payload["ready"]["fallback_available"] is True
    assert payload["session_status"] == 200
    assert payload["session"]["visitor_id"]
    assert payload["session"]["token"]


def test_migration_head_is_single_and_database_current_matches_it(tmp_path):
    db_path = tmp_path / "head_consistency.db"
    _upgrade(db_path)
    heads = _run(db_path, "-m", "alembic", "heads")
    current = _run(db_path, "-m", "alembic", "current")
    assert heads.returncode == 0, heads.stderr
    assert current.returncode == 0, current.stderr
    head = migration_head(BACKEND_DIR)
    assert heads.stdout.count("(head)") == 1
    assert head in heads.stdout
    assert head in current.stdout
