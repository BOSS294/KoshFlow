"""Transparent holding page for modules scheduled after Foundation.

Purpose: Keep navigation coherent while clearly marking modules not implemented yet.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added clear roadmap placeholders with return-to-overview action.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from koshflow.ui.components import CardFrame, HoverButton
from koshflow.ui.icons import svg_icon


MODULE_INFO = {
    "billing": ("Billing & PDF studio", "Phase 2", "Create invoices, build custom PDF themes, print receipts and share bills through WhatsApp."),
    "inventory": ("Inventory & purchasing", "Phase 2", "Manage products, purchase bills, stock movements, reorder levels and valuation."),
    "contacts": ("Customers & suppliers", "Phase 2", "Keep customer and supplier profiles, ledgers, terms and outstanding balances together."),
    "services": ("Service management", "Phase 2", "Track service requests, jobs, labour, materials, completion status and billable work."),
    "accounts": ("Accounting & taxation", "Phase 3", "Manage your chart of accounts, post balanced journals, inspect the ledger and lock closed accounting periods."),
    "reports": ("Reports & statements", "Phase 3", "Generate trial balance, profit and loss, balance sheet, general ledger, GST-supporting summaries and exportable registers."),
    "ai": ("AI business insights", "Phase 5", "Add optional Groq-powered analysis after business records and accounting calculations are established."),
}


class PlaceholderPage(QWidget):
    def __init__(self, module_key: str, on_overview, on_settings, parent: QWidget | None = None):
        super().__init__(parent)
        title, phase, description = MODULE_INFO.get(module_key, ("Workspace", "Planned", "This workspace will be available in a later release."))
        root = QVBoxLayout(self)
        root.setContentsMargins(38, 34, 38, 28)
        root.setSpacing(20)
        trail = QLabel(f"WORKSPACE   /   {title.upper()}")
        trail.setObjectName("eyebrow")
        root.addWidget(trail)
        root.addStretch(1)

        panel = CardFrame("contentCard")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(36, 34, 36, 34)
        panel_layout.setSpacing(14)
        icon_container = QFrame()
        icon_container.setFixedSize(58, 58)
        icon_container.setStyleSheet("background:#C9E86A;border-radius:17px;")
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel()
        icon_label.setPixmap(svg_icon({"billing":"receipt", "inventory":"package", "contacts":"users", "services":"briefcase", "accounts":"wallet", "reports":"chart", "ai":"sparkles"}.get(module_key, "sparkles"), "#171916", 25).pixmap(25, 25))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(icon_label)
        panel_layout.addWidget(icon_container, 0, Qt.AlignmentFlag.AlignLeft)
        stage = QLabel(phase.upper())
        stage.setObjectName("accentPill")
        stage.setMaximumWidth(120)
        panel_layout.addWidget(stage, 0, Qt.AlignmentFlag.AlignLeft)
        heading = QLabel(title)
        heading.setObjectName("headline")
        panel_layout.addWidget(heading)
        body = QLabel(description)
        body.setObjectName("muted")
        body.setWordWrap(True)
        body.setMaximumWidth(620)
        panel_layout.addWidget(body)
        note = QLabel("This module is not represented as functional until its underlying business rules, data model and tests are implemented.")
        note.setWordWrap(True)
        note.setStyleSheet("font-size:11px;")
        panel_layout.addWidget(note)
        actions = QHBoxLayout()
        home = HoverButton("Back to overview")
        home.setObjectName("primaryButton")
        home.clicked.connect(on_overview)
        settings = HoverButton("Business settings")
        settings.clicked.connect(on_settings)
        actions.addWidget(home)
        actions.addWidget(settings)
        actions.addStretch(1)
        panel_layout.addLayout(actions)
        root.addWidget(panel, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)
