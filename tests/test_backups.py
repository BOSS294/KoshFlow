"""Tests for verified local backups and restore.

Purpose: Prove SQLite backups can be created, validated, and restored.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added create/restore and invalid-file tests.
"""

import sqlite3

import pytest

from koshflow.core.backups import BackupError, BackupManager
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


def test_backup_is_valid_and_listed(database, tmp_path):
    SetupService(database).complete_setup(valid_setup())
    manager = BackupManager(database.path, tmp_path / "backups")
    backup = manager.create_backup()
    assert backup.exists()
    assert manager.validate_backup(backup) == backup.resolve()
    assert backup in manager.list_backups()


def test_restore_returns_database_to_backup_state(database, tmp_path):
    SetupService(database).complete_setup(valid_setup())
    manager = BackupManager(database.path, tmp_path / "backups")
    backup = manager.create_backup()

    with database.transaction() as conn:
        conn.execute("UPDATE businesses SET legal_name = 'Changed Name'")
    assert database.integrity_check() == "ok"

    manager.restore_backup(backup)
    with database.connection() as conn:
        name = conn.execute("SELECT legal_name FROM businesses LIMIT 1").fetchone()[0]
    assert name == "Example Trading House"
    assert database.integrity_check() == "ok"


def test_non_koshflow_file_is_rejected(database, tmp_path):
    foreign_path = tmp_path / "not-koshflow.sqlite3"
    conn = sqlite3.connect(foreign_path)
    conn.execute("CREATE TABLE hello(value TEXT)")
    conn.commit()
    conn.close()
    manager = BackupManager(database.path, tmp_path / "backups")
    with pytest.raises(BackupError, match="not a KoshFlow"):
        manager.validate_backup(foreign_path)


def test_restore_rejects_foreign_database_without_modifying_it(database, tmp_path):
    foreign_path = tmp_path / "foreign.sqlite3"
    conn = sqlite3.connect(foreign_path)
    conn.execute("CREATE TABLE keep_me(value TEXT)")
    conn.execute("INSERT INTO keep_me(value) VALUES('untouched')")
    conn.commit()
    conn.close()

    from koshflow.core.database import DatabaseError
    foreign = type(database)(foreign_path)
    with pytest.raises(DatabaseError, match="not a recognized KoshFlow"):
        foreign.initialize()
    conn = sqlite3.connect(foreign_path)
    value = conn.execute("SELECT value FROM keep_me").fetchone()[0]
    table_names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert value == "untouched"
    assert table_names == {"keep_me"}
