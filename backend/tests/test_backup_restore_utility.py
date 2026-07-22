import sqlite3

import pytest

from scripts.pilot_backup_restore import backup_database, integrity_check, rehearse, restore_database, table_counts


def _representative_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE companies (id INTEGER PRIMARY KEY, company_id TEXT NOT NULL);
            CREATE TABLE leads (id INTEGER PRIMARY KEY, company_id TEXT NOT NULL, name TEXT);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, company_id TEXT NOT NULL, user_id TEXT, message TEXT);
            INSERT INTO companies(company_id) VALUES ('pilot_a');
            INSERT INTO leads(company_id, name) VALUES ('pilot_a', 'Visitor 1');
            INSERT INTO messages(company_id, user_id, message) VALUES ('pilot_a', 'visitor_1', 'hello');
            """
        )


def test_backup_restore_rehearsal_proves_integrity_and_critical_counts(tmp_path):
    source = tmp_path / "source.sqlite3"
    _representative_database(source)

    result = rehearse(source, tmp_path / "rehearsal")

    assert result["critical_read_verified"] is True
    assert result["counts_match"] is True
    assert result["source_row_counts"]["companies"] == 1
    assert result["source_row_counts"]["leads"] == 1
    assert result["source_row_counts"]["messages"] == 1
    assert result["source_row_counts"]["knowledge_sources"] is None
    assert result["restore"]["integrity"] == "ok"


def test_backup_refuses_overwrite_and_invalid_restore(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    _representative_database(source)
    backup_database(source, backup)

    with pytest.raises(FileExistsError):
        backup_database(source, backup)

    restore_database(backup, restored)
    assert integrity_check(restored) == "ok"
    assert table_counts(restored)["messages"] == 1
    with pytest.raises(FileExistsError):
        restore_database(backup, restored)

    invalid = tmp_path / "invalid.sqlite3"
    invalid.write_bytes(b"not a sqlite database")
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        restore_database(invalid, tmp_path / "bad-restore.sqlite3")
