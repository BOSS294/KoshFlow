"""Application bootstrap and first-run/login gateway.

Purpose: Initialize local directories, database, backup manager, Qt styling,
         and route between setup, login, and the authenticated application shell.
Project: KoshFlow | Version: 0.6.3
Canonical path: koshflow/app.py
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.6.3 — Connected updated dashboard, AI Insights and persistent desktop notification settings.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from koshflow import __version__
from koshflow.config import APP_NAME, ensure_data_dirs
from koshflow.core.backups import BackupManager
from koshflow.core.database import Database, DatabaseError
from koshflow.core.session import Session
from koshflow.services.auth_service import AuthService
from koshflow.services.setup_service import SetupService
from koshflow.ui.animations import fade_in
from koshflow.ui.pages.login_page import LoginPage
from koshflow.ui.pages.setup_page import SetupPage
from koshflow.ui.styles import apply_theme
from koshflow.ui.main_window import MainWindow


class GatewayWindow(QMainWindow):
    """First-run setup or local login window."""

    def __init__(self, database: Database, on_authenticated, parent=None):
        super().__init__(parent)
        self.database = database
        self.on_authenticated = on_authenticated
        self.setWindowTitle(f"{APP_NAME} — Local workspace")
        self.setMinimumSize(1080, 760)
        self.resize(1260, 820)
        self.setObjectName("gatewayWindow")

        root = QWidget()
        root.setObjectName("gatewayRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.setCentralWidget(root)

        if self.database.has_users():
            self._show_login()
        else:
            setup = SetupPage(SetupService(database), self._show_login)
            self.stack.addWidget(setup)
            self.stack.setCurrentWidget(setup)
            fade_in(setup, 240)

    def _show_login(self) -> None:
        for index in range(self.stack.count() - 1, -1, -1):
            widget = self.stack.widget(index)
            if isinstance(widget, LoginPage):
                self.stack.setCurrentWidget(widget)
                fade_in(widget, 220)
                return
        login = LoginPage(AuthService(self.database), self._authenticated)
        self.stack.addWidget(login)
        self.stack.setCurrentWidget(login)
        fade_in(login, 220)

    def _authenticated(self, session: Session) -> None:
        self.hide()
        self.on_authenticated(session)


class ApplicationController:
    """Own top-level windows to support setup, login, logout, and restored sessions."""

    def __init__(self, app: QApplication, database: Database, backup_manager: BackupManager):
        self.app = app
        self.database = database
        self.backup_manager = backup_manager
        self.gateway: GatewayWindow | None = None
        self.main_window: MainWindow | None = None

    def start(self) -> None:
        self.show_gateway()

    def show_gateway(self) -> None:
        self.gateway = GatewayWindow(self.database, self.open_workspace)
        self.gateway.show()

    def open_workspace(self, session: Session) -> None:
        if self.gateway:
            self.gateway.close()
            self.gateway = None
        self.main_window = MainWindow(
            self.database,
            self.backup_manager,
            session,
            self.logout,
        )
        self.main_window.show()

    def logout(self) -> None:
        self.main_window = None
        self.show_gateway()


def configure_logging(log_path: Path) -> None:
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
        force=True,
    )


def run() -> int:
    paths = ensure_data_dirs()
    configure_logging(paths["logs"] / "koshflow.log")
    logging.getLogger(__name__).info("Starting KoshFlow v%s", __version__)

    app = QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("KoshFlow")
    brand_icon = Path(__file__).resolve().parents[1] / "assets" / "koshflow.ico"
    if brand_icon.exists():
        app.setWindowIcon(QIcon(str(brand_icon)))
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")

    # QFontDatabase is the supported way to inspect installed font families.
    try:
        from PySide6.QtGui import QFontDatabase
        font_database = QFontDatabase()
        available_fonts = {family.casefold() for family in font_database.families()}
    except Exception:
        available_fonts = set()
    preferred_font = next(
        (candidate for candidate in ("Inter", "Segoe UI", "Noto Sans", "Arial")
         if candidate.casefold() in available_fonts),
        "Segoe UI",
    )
    app.setFont(QFont(preferred_font, 10))
    app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

    database = Database(paths["root"] / "koshflow.sqlite3")
    try:
        database.initialize()
    except DatabaseError as exc:
        logging.getLogger(__name__).exception("Could not initialize local database")
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "KoshFlow could not start", str(exc))
        return 1

    theme = database.get_setting("theme", "light") or "light"
    apply_theme(app, theme)
    backup_manager = BackupManager(database.path, paths["backups"])
    controller = ApplicationController(app, database, backup_manager)
    controller.start()
    return app.exec()
