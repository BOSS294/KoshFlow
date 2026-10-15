"""Pytest fixtures for isolated KoshFlow core tests.

Purpose: Provide a fresh temporary SQLite database per test.
Project: KoshFlow | Version: 0.5.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added initialized temporary database fixture.
"""

import pytest

from koshflow.core.database import Database


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "koshflow.sqlite3")
    db.initialize()
    return db
