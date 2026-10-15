"""First-run setup interface for the initial owner and business profile.

Purpose: Create the local owner account and primary business in a single flow.
Project: KoshFlow | Version: 0.6.0
Canonical path: koshflow/ui/pages/setup_page.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Pass SetupService and a no-argument completion callback.
Changelog: v0.3.0 — Retained branded first-run setup for the expanded billing release.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from koshflow.services.setup_service import SetupError, SetupService
from koshflow.ui.components import HoverButton, labeled_field, make_combo, make_line_edit
from koshflow.ui.icons import svg_icon


BUSINESS_TYPES = [
    "Retail", "Wholesale", "Manufacturing", "Services", "Professional services",
    "E-commerce", "Distributor", "Other",
]


class SetupPage(QWidget):
    def __init__(self, service: SetupService, on_complete, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.on_complete = on_complete
        self.setObjectName("gatewayRoot")
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.addWidget(self._build_hero(), 4)
        root.addWidget(self._build_form(), 6)

    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("setupHero")
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(30, 30, 28, 28)
        layout.setSpacing(17)

        brand_row = QHBoxLayout()
        mark = QLabel("K")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(42, 42)
        mark.setStyleSheet("background:#C9E86A;color:#171916;border-radius:13px;font-size:23px;font-weight:800;")
        brand = QLabel("KoshFlow")
        brand.setObjectName("smallBrand")
        brand.setStyleSheet("font-size:16px;")
        brand_row.addWidget(mark)
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)
        layout.addSpacing(28)

        eyebrow = QLabel("YOUR BUSINESS, BETTER ORGANIZED")
        eyebrow.setStyleSheet("color:#C9E86A;font-size:10px;font-weight:750;letter-spacing:1.5px;")
        layout.addWidget(eyebrow)
        title = QLabel("A calmer way\nto run your business.")
        title.setObjectName("heroTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        body = QLabel(
            "Bring your business essentials into one clear workspace — "
            "built for speed, designed for focus, and stored locally by default."
        )
        body.setObjectName("heroBody")
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addSpacing(14)

        features = [
            ("database", "Your records stay on this device"),
            ("shield", "Password-protected local access"),
            ("file-check", "Backup and restore infrastructure"),
        ]
        for icon_name, text in features:
            row = QHBoxLayout()
            icon = QLabel()
            icon.setPixmap(svg_icon(icon_name, "#C9E86A", 18).pixmap(18, 18))
            icon.setFixedWidth(25)
            label = QLabel(text)
            label.setStyleSheet("color:#E5E8DE;font-size:12px;")
            row.addWidget(icon)
            row.addWidget(label, 1)
            layout.addLayout(row)

        layout.addStretch(1)
        accent_rule = QFrame()
        accent_rule.setFixedHeight(3)
        accent_rule.setStyleSheet("background:#C9E86A;border:none;border-radius:1px;")
        layout.addWidget(accent_rule)
        footer = QLabel("BILLING · INVENTORY · ACCOUNTING  ·  v0.6.0")
        footer.setStyleSheet("color:#8E9385;font-size:10px;font-weight:650;letter-spacing:1px;")
        layout.addWidget(footer)
        return hero

    def _build_form(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("setupPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(34, 25, 34, 24)
        layout.setSpacing(10)

        kicker = QLabel("LET'S SET UP YOUR WORKSPACE")
        kicker.setObjectName("eyebrow")
        title = QLabel("Start with the essentials")
        title.setStyleSheet("font-size:23px;font-weight:750;")
        intro = QLabel("Create a local owner login and save your business profile.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(kicker)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addSpacing(6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(13)
        grid.setVerticalSpacing(10)

        self.legal_name = make_line_edit("e.g. KoshFlow Traders")
        self.trade_name = make_line_edit("Optional trading name")
        self.business_type = make_combo(BUSINESS_TYPES)
        self.state = make_line_edit("e.g. Chhattisgarh")
        self.gstin = make_line_edit("Optional — 15-character GSTIN")
        self.owner_name = make_line_edit("Full name")
        self.username = make_line_edit("Choose a username")
        self.password = make_line_edit("At least 10 characters", password=True)
        self.confirm_password = make_line_edit("Re-enter password", password=True)
        self.business_type.setCurrentText("Other")

        grid.addWidget(labeled_field("BUSINESS / LEGAL NAME *", self.legal_name), 0, 0, 1, 2)
        grid.addWidget(labeled_field("TRADING NAME", self.trade_name), 1, 0)
        grid.addWidget(labeled_field("BUSINESS TYPE", self.business_type), 1, 1)
        grid.addWidget(labeled_field("STATE / UT", self.state), 2, 0)
        grid.addWidget(labeled_field("GSTIN (OPTIONAL)", self.gstin), 2, 1)
        layout.addLayout(grid)

        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background:#E1E4DA;border:none;")
        layout.addSpacing(2)
        layout.addWidget(separator)
        owner_title = QLabel("Owner access")
        owner_title.setStyleSheet("font-size:13px;font-weight:750;")
        layout.addWidget(owner_title)

        owner_grid = QGridLayout()
        owner_grid.setHorizontalSpacing(13)
        owner_grid.setVerticalSpacing(10)
        owner_grid.addWidget(labeled_field("OWNER NAME *", self.owner_name), 0, 0)
        owner_grid.addWidget(labeled_field("USERNAME *", self.username), 0, 1)
        owner_grid.addWidget(labeled_field("PASSWORD *", self.password), 1, 0)
        owner_grid.addWidget(labeled_field("CONFIRM PASSWORD *", self.confirm_password), 1, 1)
        layout.addLayout(owner_grid)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color:#6C792C;font-size:11px;font-weight:600;")
        layout.addWidget(self.message)

        self.create_button = HoverButton("Create local workspace  →")
        self.create_button.setObjectName("primaryButton")
        self.create_button.setMinimumHeight(45)
        self.create_button.clicked.connect(self._submit)
        layout.addWidget(self.create_button)

        footnote = QLabel("Your password is hashed locally. KoshFlow will not upload your business records during setup.")
        footnote.setObjectName("muted")
        footnote.setWordWrap(True)
        footnote.setStyleSheet("font-size:10px;")
        layout.addWidget(footnote)
        layout.addStretch(1)

        self.legal_name.setFocus()
        self.confirm_password.returnPressed.connect(self._submit)
        return panel

    def _submit(self) -> None:
        self.create_button.setEnabled(False)
        self.message.setStyleSheet("color:#777B70;font-size:11px;font-weight:600;")
        self.message.setText("Creating your local workspace…")
        data = {
            "legal_name": self.legal_name.text(),
            "trade_name": self.trade_name.text(),
            "business_type": self.business_type.currentText(),
            "state": self.state.text(),
            "gstin": self.gstin.text(),
            "display_name": self.owner_name.text(),
            "username": self.username.text(),
            "password": self.password.text(),
            "confirm_password": self.confirm_password.text(),
        }
        try:
            self.service.complete_setup(data)
        except SetupError as exc:
            self.message.setStyleSheet("color:#7A6D28;font-size:11px;font-weight:600;")
            self.message.setText(str(exc))
            self.create_button.setEnabled(True)
            return
        self.password.clear()
        self.confirm_password.clear()
        self.message.setText("Workspace created. Opening local sign-in…")
        self.on_complete()
