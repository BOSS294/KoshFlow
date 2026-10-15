"""Local sign-in page for KoshFlow.

Purpose: Authenticate local users and hand an in-memory Session to the app shell.
Project: KoshFlow | Version: 0.6.3
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.6.3 — Kept login branding aligned with the current desktop release.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from koshflow.core.session import Session
from koshflow.services.auth_service import AuthService, AuthenticationError
from koshflow.ui.components import HoverButton, labeled_field, make_line_edit
from koshflow.ui.icons import svg_icon


class LoginPage(QWidget):
    def __init__(self, service: AuthService, on_authenticated, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.on_authenticated = on_authenticated
        self.setObjectName("gatewayRoot")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)

        hero = QFrame()
        hero.setObjectName("setupHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(34, 32, 32, 30)
        hero_layout.setSpacing(16)
        mark_row = QHBoxLayout()
        mark = QLabel("K")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(42, 42)
        mark.setStyleSheet("background:#C9E86A;color:#171916;border-radius:13px;font-size:23px;font-weight:800;")
        brand = QLabel("KoshFlow")
        brand.setStyleSheet("color:#FFFFFF;font-size:16px;font-weight:750;")
        mark_row.addWidget(mark)
        mark_row.addWidget(brand)
        mark_row.addStretch(1)
        hero_layout.addLayout(mark_row)
        hero_layout.addSpacing(56)
        eyebrow = QLabel("WELCOME BACK")
        eyebrow.setStyleSheet("color:#C9E86A;font-size:10px;font-weight:750;letter-spacing:1.5px;")
        hero_layout.addWidget(eyebrow)
        title = QLabel("Good to have\nyou back.")
        title.setStyleSheet("color:#FFFFFF;font-size:32px;font-weight:750;")
        hero_layout.addWidget(title)
        body = QLabel("Your business workspace is ready when you are. Sign in to continue where you left off.")
        body.setObjectName("heroBody")
        body.setWordWrap(True)
        hero_layout.addWidget(body)
        hero_layout.addSpacing(16)
        privacy = QHBoxLayout()
        privacy_icon = QLabel()
        privacy_icon.setPixmap(svg_icon("lock", "#C9E86A", 18).pixmap(18, 18))
        privacy_text = QLabel("Local sign-in  ·  No cloud account required")
        privacy_text.setStyleSheet("color:#D3D7CA;font-size:11px;")
        privacy.addWidget(privacy_icon)
        privacy.addWidget(privacy_text)
        privacy.addStretch(1)
        hero_layout.addLayout(privacy)
        hero_layout.addStretch(1)
        line = QFrame()
        line.setFixedHeight(3)
        line.setStyleSheet("background:#C9E86A;border:none;")
        hero_layout.addWidget(line)
        version = QLabel("KOSHFLOW  ·  BUSINESS DESKTOP 0.6.3")
        version.setStyleSheet("color:#8E9385;font-size:10px;font-weight:650;letter-spacing:1px;")
        hero_layout.addWidget(version)

        panel = QFrame()
        panel.setObjectName("setupPanel")
        form = QVBoxLayout(panel)
        form.setContentsMargins(45, 52, 45, 42)
        form.setSpacing(14)
        kicker = QLabel("YOUR WORKSPACE")
        kicker.setObjectName("eyebrow")
        title = QLabel("Sign in")
        title.setStyleSheet("font-size:27px;font-weight:750;")
        subtitle = QLabel("Enter your local account details to continue.")
        subtitle.setObjectName("muted")
        form.addWidget(kicker)
        form.addWidget(title)
        form.addWidget(subtitle)
        form.addSpacing(18)

        self.username = make_line_edit("Username")
        self.password = make_line_edit("Password", password=True)
        form.addWidget(labeled_field("USERNAME", self.username))
        form.addWidget(labeled_field("PASSWORD", self.password))
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color:#7A6D28;font-size:11px;font-weight:600;")
        form.addWidget(self.message)
        self.sign_in = HoverButton("Unlock workspace  →")
        self.sign_in.setObjectName("primaryButton")
        self.sign_in.setMinimumHeight(46)
        self.sign_in.clicked.connect(self._submit)
        form.addWidget(self.sign_in)
        form.addSpacing(4)
        form.addWidget(QLabel("Tip: press Enter to sign in."))
        form.itemAt(form.count() - 1).widget().setObjectName("muted")
        form.addStretch(1)
        bottom = QLabel("Forgot your password? Keep a separate backup of your data; a secure recovery flow will be added before production release.")
        bottom.setObjectName("muted")
        bottom.setWordWrap(True)
        bottom.setStyleSheet("font-size:10px;")
        form.addWidget(bottom)

        outer.addWidget(hero, 4)
        outer.addWidget(panel, 6)
        self.username.setFocus()
        self.password.returnPressed.connect(self._submit)
        self.username.returnPressed.connect(self.password.setFocus)

    def _submit(self) -> None:
        self.sign_in.setEnabled(False)
        self.message.setText("Checking local credentials…")
        try:
            session: Session = self.service.authenticate(self.username.text(), self.password.text())
        except AuthenticationError as exc:
            self.message.setText(str(exc))
            self.sign_in.setEnabled(True)
            self.password.selectAll()
            return
        self.message.setText("")
        self.password.clear()
        self.on_authenticated(session)
