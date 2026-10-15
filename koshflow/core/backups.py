"""Consistent SQLite backup and validated restore routines.

Purpose: Create verified, timestamped local backups and validate restore candidates
         before replacing the active database file.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added SQLite online backup API, integrity validation, app identity
           checks, and atomic file replacement during restore.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from koshflow.config import APP_ID, DEFAULT_TIMEZONE, SCHEMA_VERSION


class BackupError(RuntimeError):
    """Raised when a backup or restore candidate cannot be trusted."""


class BackupManager:
    def __init__(self, database_path: str | Path, backup_dir: str | Path):
        self.database_path = Path(database_path).expanduser().resolve()
        self.backup_dir = Path(backup_dir).expanduser().resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, destination: str | Path | None = None) -> Path:
        if not self.database_path.exists():
            raise BackupError("The local database does not exist yet.")
        timestamp = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y%m%d-%H%M%S-%f")
        target = Path(destination).expanduser().resolve() if destination else (
            self.backup_dir / f"koshflow-backup-{timestamp}.sqlite3"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        try:
            source = sqlite3.connect(self.database_path, timeout=15.0)
            destination_conn = sqlite3.connect(temporary, timeout=15.0)
            try:
                source.backup(destination_conn, pages=256, sleep=0.05)
                check = destination_conn.execute("PRAGMA integrity_check").fetchone()[0]
                app_id = destination_conn.execute(
                    "SELECT meta_value FROM app_meta WHERE meta_key = 'app_id'"
                ).fetchone()
                if check != "ok" or not app_id or app_id[0] != APP_ID:
                    raise BackupError("The generated backup failed validation.")
                destination_conn.commit()
            finally:
                destination_conn.close()
                source.close()
            temporary.replace(target)
            return target
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if isinstance(exc, BackupError):
                raise
            raise BackupError(f"Could not create the backup: {exc}") from exc

    def validate_backup(self, candidate: str | Path) -> Path:
        path = Path(candidate).expanduser().resolve()
        if not path.is_file():
            raise BackupError("Select an existing backup file.")
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
            try:
                check = conn.execute("PRAGMA integrity_check").fetchone()[0]
                has_meta = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_meta'"
                ).fetchone()
                if not has_meta:
                    raise BackupError("This file is not a KoshFlow database backup.")
                app_id = conn.execute(
                    "SELECT meta_value FROM app_meta WHERE meta_key = 'app_id'"
                ).fetchone()
                version = conn.execute(
                    "SELECT meta_value FROM app_meta WHERE meta_key = 'schema_version'"
                ).fetchone()
                if check != "ok":
                    raise BackupError("This file failed SQLite integrity checks.")
                if not app_id or app_id[0] != APP_ID:
                    raise BackupError("This file is not a KoshFlow database backup.")
                if not version:
                    raise BackupError("The backup does not contain a schema version.")
                try:
                    backup_version = int(version[0])
                except (TypeError, ValueError) as exc:
                    raise BackupError("The backup contains an invalid schema version.") from exc
                if backup_version > SCHEMA_VERSION:
                    raise BackupError("This backup was created by a newer KoshFlow version; update the app before restoring it.")
            finally:
                conn.close()
            return path
        except BackupError:
            raise
        except sqlite3.DatabaseError as exc:
            raise BackupError(f"The selected file is not a readable KoshFlow backup: {exc}") from exc

    def restore_backup(self, candidate: str | Path) -> Path:
        """Validate first, copy to a sibling temporary file, then atomically replace DB."""
        source_path = self.validate_backup(candidate)
        if source_path == self.database_path:
            raise BackupError("The active database cannot be restored over itself.")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.database_path.with_suffix(self.database_path.suffix + ".restore")
        try:
            source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
            target = sqlite3.connect(temporary)
            try:
                source.backup(target, pages=256, sleep=0.05)
                check = target.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    raise BackupError("The restore copy failed integrity checks.")
                target.commit()
            finally:
                target.close()
                source.close()
            temporary.replace(self.database_path)
            # Stale WAL/SHM files must not be applied to the restored database.
            Path(f"{self.database_path}-wal").unlink(missing_ok=True)
            Path(f"{self.database_path}-shm").unlink(missing_ok=True)
            return source_path
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if isinstance(exc, BackupError):
                raise
            raise BackupError(f"Could not restore the selected backup: {exc}") from exc

    def list_backups(self) -> list[Path]:
        return sorted(
            (path for path in self.backup_dir.glob("koshflow-backup-*.sqlite3") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
