"""Application configuration and local data paths.

Purpose: Centralize application identity, paths, and runtime configuration.
Project: KoshFlow | Version: 0.6.3
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.6.3 — Refined dashboard migration, profile popover state, and consistent light/dark surfaces.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "KoshFlow"
APP_VERSION = "0.6.3"
APP_ID = "in.boss294.koshflow"
SCHEMA_VERSION = 7
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_ACCENT = "#C9E86A"


def get_data_dir() -> Path:
    """Return the per-user application data directory.

    KOSHFLOW_HOME is intended for portable use and automated tests. In normal
    installations data is kept in the operating system's standard user-data path.
    """
    override = os.environ.get("KOSHFLOW_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def ensure_data_dirs() -> dict[str, Path]:
    """Create required local directories and return their paths."""
    root = get_data_dir()
    paths = {
        "root": root,
        "backups": root / "backups",
        "logs": root / "logs",
        "exports": root / "exports",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths
