import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from schema_verification import migration_head


CRITICAL_LEAD_COLUMNS = {"sales_state_snapshot"}
CRITICAL_COMPANY_KNOWLEDGE_COLUMNS = {"google_sheet_webhook_url"}
CRITICAL_REFRESH_TOKEN_COLUMNS = {"updated_at"}
CRITICAL_MESSAGE_COLUMNS = {
    "processing_status",
    "processing_started_at",
    "processing_completed_at",
    "processing_attempts",
}


def _run_alembic(backend_dir, db_path, *args):
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=backend_dir,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result


def test_fresh_alembic_upgrade_reaches_head(tmp_path):
    db_path = tmp_path / "fresh_migration.db"
    backend_dir = Path(__file__).resolve().parents[1]

    _run_alembic(backend_dir, db_path, "upgrade", "head")

    current = _run_alembic(backend_dir, db_path, "current")
    assert migration_head(backend_dir) in current.stdout

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"lead_memory", "lead_analytics", "lead_evidence", "messages", "message_events", "workspace_suggested_replies", "commercial_decision_lineage", "commercial_events"}.issubset(tables)

        lead_columns = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
        assert {"conversation_state", "is_paused", "last_message", "is_test", "channel_type", "external_customer_id"}.issubset(lead_columns)
        assert CRITICAL_LEAD_COLUMNS.issubset(lead_columns)

        message_columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        assert CRITICAL_MESSAGE_COLUMNS.issubset(message_columns)
        
        # Verify phone nullable: dflt_value, notnull, etc. 
        # PRAGMA table_info returns (cid, name, type, notnull, dflt_value, pk)
        phone_info = [row for row in conn.execute("PRAGMA table_info(leads)") if row[1] == "phone"][0]
        assert phone_info[3] == 0  # notnull == 0 means nullable!

        company_columns = {row[1] for row in conn.execute("PRAGMA table_info(companies)")}
        assert {
            "bot_auto_reply_enabled",
            "is_web_chat_enabled",
            "public_chat_slug",
            "auth_provider",
            "google_subject",
        }.issubset(company_columns)

        knowledge_columns = {row[1] for row in conn.execute("PRAGMA table_info(company_knowledge)")}
        assert CRITICAL_COMPANY_KNOWLEDGE_COLUMNS.issubset(knowledge_columns)

        refresh_token_columns = {row[1] for row in conn.execute("PRAGMA table_info(refresh_tokens)")}
        assert CRITICAL_REFRESH_TOKEN_COLUMNS.issubset(refresh_token_columns)


def test_revenue_recovery_migration_backfills_legacy_follow_up_tenant_and_downgrades_safely(tmp_path):
    db_path = tmp_path / "legacy_follow_up_backfill.db"
    backend_dir = Path(__file__).resolve().parents[1]
    _run_alembic(backend_dir, db_path, "upgrade", "e27a6c4d9b10")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO companies (company_id, company_name, email, password, api_key_hash, plan)
            VALUES ('migration_tenant', 'Migration Tenant', 'migration@example.com', 'hashed', 'hash', 'PRO')
            """
        )
        conn.execute(
            """
            INSERT INTO leads (company_id, name, stage)
            VALUES ('migration_tenant', 'Legacy customer', 'Interested')
            """
        )
        lead_id = conn.execute("SELECT id FROM leads WHERE company_id = 'migration_tenant'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO follow_up_tasks (lead_id, task_level, task_type, status, due_at)
            VALUES (?, 2, 'RE_ENGAGE', 'pending', CURRENT_TIMESTAMP)
            """,
            (lead_id,),
        )

    _run_alembic(backend_dir, db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT company_id, source_type, source_identifier, reason_code,
                   idempotency_key, category, priority
            FROM follow_up_tasks
            """
        ).fetchone()
        assert row == (
            "migration_tenant",
            "legacy_stage_sweeper",
            "legacy-follow-up:1",
            "RE_ENGAGE",
            "legacy-follow-up:1",
            "FOLLOW_UP_DUE",
            50,
        )

    _run_alembic(backend_dir, db_path, "downgrade", "e27a6c4d9b10")
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(follow_up_tasks)")}
        assert "company_id" not in columns
        assert conn.execute("SELECT lead_id, task_type, status FROM follow_up_tasks").fetchone() == (
            lead_id,
            "RE_ENGAGE",
            "pending",
        )

    _run_alembic(backend_dir, db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT company_id FROM follow_up_tasks").fetchone()[0] == "migration_tenant"


def test_already_stamped_web_chat_runtime_schema_repairs_without_data_loss(tmp_path):
    db_path = tmp_path / "stale_head_runtime.db"
    backend_dir = Path(__file__).resolve().parents[1]

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES ('a059afd118e1')")
        conn.execute(
            """
            CREATE TABLE leads (
                id INTEGER PRIMARY KEY,
                company_id VARCHAR(64),
                name VARCHAR(200) NOT NULL,
                phone VARCHAR(20),
                channel_type VARCHAR(50) NOT NULL DEFAULT 'VELOR_WEB_CHAT',
                external_customer_id VARCHAR(100),
                is_deleted BOOLEAN DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                internal_message_id VARCHAR(64) NOT NULL,
                public_message_id VARCHAR(64),
                wa_message_id VARCHAR(128),
                company_id VARCHAR(64),
                user_id VARCHAR(100) NOT NULL,
                sender VARCHAR(20) NOT NULL,
                direction VARCHAR(20) NOT NULL,
                message TEXT NOT NULL,
                delivery_status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_deleted BOOLEAN DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            INSERT INTO leads (id, company_id, name, phone, channel_type, external_customer_id, is_deleted)
            VALUES (1, 'company_live', 'Visitor', NULL, 'VELOR_WEB_CHAT', 'wc_v_existing', 0)
            """
        )
        conn.execute(
            """
            INSERT INTO messages (
                id, internal_message_id, public_message_id, wa_message_id, company_id,
                user_id, sender, direction, message, delivery_status, is_deleted
            )
            VALUES (
                1, 'internal-1', 'pub-existing', 'wc:company_live:client-1', 'company_live',
                'wc_v_existing', 'user', 'incoming', 'hello', 'received', 0
            )
            """
        )

    _run_alembic(backend_dir, db_path, "upgrade", "head")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == migration_head(backend_dir)

        lead_columns = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
        message_columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        assert CRITICAL_LEAD_COLUMNS.issubset(lead_columns)
        assert CRITICAL_MESSAGE_COLUMNS.issubset(message_columns)

        lead_row = conn.execute(
            "SELECT name, channel_type, external_customer_id FROM leads WHERE id = 1"
        ).fetchone()
        assert lead_row == ("Visitor", "VELOR_WEB_CHAT", "wc_v_existing")

        message_row = conn.execute(
            """
            SELECT message, processing_status, processing_attempts
            FROM messages
            WHERE id = 1
            """
        ).fetchone()
        assert message_row == ("hello", "completed", 0)
