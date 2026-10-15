"""Billing and PDF Studio landing hubs.

Purpose: Provide action-card routing into implemented bill CRUD and PDF workflows.
Canonical path: koshflow/ui/pages/billing_hub_page.py
Project: KoshFlow | Version: 0.5.4
Developer: Mayank Chawdhari AKA BOSS294
Integration: Instantiate with database, session, business profile and route callback.
Changelog: v0.5.2 — Rebuilt workflow cards as responsive, keyboard-accessible QFrames and tightened workspace sizing.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from koshflow.core.database import Database
from koshflow.core.session import Session
from koshflow.services.bill_service import BillService
from koshflow.ui.components import CardFrame, HoverButton
from koshflow.ui.icons import svg_icon


BILLING_ACTIONS = [
    ("Quick billing", "Keyboard-first counter checkout using pre-added products and live stock checks.", "zap", "quick_billing", True),
    ("Create bill", "Start a new B2B or B2C bill with line items, tax and payment terms.", "file-plus", "billing_create", False),
    ("Manage bills", "Search, edit drafts, issue invoices, record payments and audit status.", "receipt", "billing_manage", False),
    ("Send a bill", "Prepare a WhatsApp message and a PDF file for manual attachment.", "send", "billing_send", False),
    ("Generate PDF", "Render a selected bill with a saved invoice theme.", "file-down", "pdf_generator", False),
    ("PDF Studio", "Build your invoice look, page size, accent color and reusable themes.", "palette", "pdf_studio", False),
    ("PDF theme library", "Create, edit, duplicate and choose the default bill design.", "layers", "pdf_templates", False),
    ("Exports & documents", "Find generated PDFs and open the local export folder.", "folder-open", "billing_exports", False),
    ("Billing workflow", "Review totals, draft counts, issued bills and outstanding balances.", "chart", "billing_manage", False),
]

PDF_ACTIONS = [
    ("Generate a PDF", "Select an existing bill and apply a saved template.", "file-down", "pdf_generator", True),
    ("Customize theme", "Change layout, typography, accent and document defaults.", "palette", "pdf_templates", False),
    ("Manage themes", "Maintain a reusable library of branded invoice templates.", "layers", "pdf_templates", False),
    ("Send a bill", "Generate the document, then open the customer's WhatsApp chat.", "send", "billing_send", False),
    ("Exports & documents", "Access previously generated PDF files on this device.", "folder-open", "billing_exports", False),
    ("Return to billing", "Create and manage documents in the billing workspace.", "receipt", "billing", False),
]


class ActionCard(QFrame):
    """Responsive clickable workspace card with reliable keyboard interaction."""

    clicked = Signal(bool)

    def __init__(self, title: str, description: str, icon_name: str, accent: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("workspaceActionCard")
        self.setProperty("accent", "true" if accent else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMinimumWidth(0)
        self.setMinimumHeight(148)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        self.setToolTip(f"{title}\n{description}")
        self._pressed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 15)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        icon_box = QFrame(self)
        icon_box.setObjectName("actionCardIcon")
        icon_box.setProperty("accent", "true" if accent else "false")
        icon_box.setFixedSize(39, 39)
        icon_box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel(icon_box)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        icon_label.setPixmap(svg_icon(icon_name, "#171916" if accent else "#829B3E", 20).pixmap(20, 20))
        icon_layout.addWidget(icon_label)
        top.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        top.addStretch(1)

        arrow = QLabel(self)
        arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        arrow.setPixmap(svg_icon("arrow-up-right", "#8A907E", 16).pixmap(16, 16))
        top.addWidget(arrow, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        title_label = QLabel(title, self)
        title_label.setObjectName("actionCardTitle")
        title_label.setWordWrap(True)
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        body_label = QLabel(description, self)
        body_label.setObjectName("actionCardDescription")
        body_label.setWordWrap(True)
        body_label.setMinimumWidth(0)
        body_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        body_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(title_label)
        layout.addWidget(body_label, 1)

    def mousePressEvent(self, event) -> None:
        self._pressed = event.button() == Qt.MouseButton.LeftButton
        self.setProperty("pressed", "true" if self._pressed else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.setProperty("pressed", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        if was_pressed and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(False)
            event.accept()
            return
        super().keyPressEvent(event)


class BillingHubPage(QWidget):
    def __init__(self, database: Database, session: Session, profile: dict, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.profile = profile
        self.navigate = navigate
        self.setObjectName("billingHubPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.workspace_scroll = QScrollArea(self)
        self.workspace_scroll.setObjectName("workspaceScroll")
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.workspace_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace_content = QWidget()
        self.workspace_content.setObjectName("workspaceCanvas")
        self.workspace_content.setMinimumWidth(0)
        self.workspace_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        outer.addWidget(self.workspace_scroll)
        self.workspace_scroll.setWidget(self.workspace_content)
        root = QVBoxLayout(self.workspace_content)
        root.setContentsMargins(26, 20, 26, 22)
        root.setSpacing(15)

        top = QHBoxLayout()
        copy = QVBoxLayout()
        eyebrow = QLabel("SALES WORKSPACE  /  BILLING")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Billing & documents")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Create a bill in seconds, keep every change auditable, and generate a polished document when you need it.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        copy.addWidget(eyebrow)
        copy.addWidget(title)
        copy.addWidget(subtitle)
        top.addLayout(copy, 1)
        quick = HoverButton("Create bill")
        quick.setObjectName("primaryButton")
        quick.setIcon(svg_icon("plus", "#171916", 16))
        quick.clicked.connect(lambda: self.navigate("billing_create"))
        top.addWidget(quick, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        self.stats = QGridLayout()
        self.stats.setHorizontalSpacing(12)
        self.stats.setVerticalSpacing(12)
        self._stat_tiles = []
        self._stats_columns = 0
        summary = BillService(database).summary(session.business_id)
        stat_specs = [
            ("All bills", str(summary["total_bills"]), "receipt"),
            ("Drafts", str(summary["drafts"]), "file-check"),
            ("Collected", f"₹{DecimalSafe(summary['collected'])}", "hand-coins"),
            ("Outstanding", f"₹{DecimalSafe(summary['outstanding'])}", "clock"),
        ]
        self._summary_value_labels = []
        for label, value, icon in stat_specs:
            tile, value_label = self._stat_tile(label, value, icon)
            self._summary_value_labels.append(value_label)
            self._stat_tiles.append(tile)
        self._layout_stat_tiles()
        root.addLayout(self.stats)

        section_title = QLabel("Choose a workflow")
        section_title.setObjectName("sectionTitle")
        root.addWidget(section_title)
        grid = QGridLayout()
        grid.setSpacing(14)
        self._action_grid = grid
        self._action_cards = []
        self._current_columns = 0
        for title, description, icon, key, accent in BILLING_ACTIONS:
            card = ActionCard(title, description, icon, accent)
            card.clicked.connect(lambda checked=False, target=key: self.navigate(target))
            self._action_cards.append(card)
        self._layout_action_cards()
        root.addLayout(grid)

        footer = QFrame()
        footer.setObjectName("softPanel")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        hint_icon = QLabel()
        hint_icon.setPixmap(svg_icon("shield-check", "#829B3E", 19).pixmap(19, 19))
        footer_layout.addWidget(hint_icon)
        hint = QLabel("Issued bills are preserved. Edit drafts freely; record payments or use a documented cancellation workflow for issued documents.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        footer_layout.addWidget(hint, 1)
        root.addWidget(footer)
        root.addStretch(1)

    def _available_workspace_width(self) -> int:
        viewport = getattr(self, "workspace_scroll", None)
        if viewport is not None:
            return max(0, viewport.viewport().width() - 52)
        return max(0, self.width() - 52)

    def _layout_stat_tiles(self) -> None:
        if not hasattr(self, "stats") or not self._stat_tiles:
            return
        available_width = self._available_workspace_width()
        columns = 4 if available_width >= 1580 else 2 if available_width >= 660 else 1
        if columns == self._stats_columns and self.stats.count() == len(self._stat_tiles):
            return
        while self.stats.count():
            self.stats.takeAt(0)
        self._stats_columns = columns
        for index, tile in enumerate(self._stat_tiles):
            tile.setMinimumWidth(0)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.stats.addWidget(tile, index // columns, index % columns)
        for column in range(4):
            self.stats.setColumnStretch(column, 1 if column < columns else 0)

    def _layout_action_cards(self) -> None:
        if not hasattr(self, "_action_grid"):
            return
        available_width = self._available_workspace_width()
        columns = 4 if available_width >= 1760 else 3 if available_width >= 1040 else 2 if available_width >= 620 else 1
        if columns == self._current_columns and self._action_grid.count() == len(self._action_cards):
            return
        while self._action_grid.count():
            self._action_grid.takeAt(0)
        self._current_columns = columns
        for index, card in enumerate(self._action_cards):
            card.setMinimumWidth(0)
            self._action_grid.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self._action_grid.setColumnMinimumWidth(column, 0)
            self._action_grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_stat_tiles()
        self._layout_action_cards()

    @staticmethod
    def _stat_tile(label: str, value: str, icon: str) -> tuple[QFrame, QLabel]:
        tile = CardFrame("metricCard")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(15, 12, 15, 13)
        top = QHBoxLayout()
        caption = QLabel(label)
        caption.setObjectName("muted")
        glyph = QLabel()
        glyph.setPixmap(svg_icon(icon, "#829B3E", 17).pixmap(17, 17))
        top.addWidget(caption, 1)
        top.addWidget(glyph)
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size:21px;font-weight:760;")
        layout.addLayout(top)
        layout.addWidget(value_label)
        return tile, value_label

    def refresh(self) -> None:
        summary = BillService(self.database).summary(self.session.business_id)
        values = [
            str(summary["total_bills"]), str(summary["drafts"]),
            f"₹{DecimalSafe(summary['collected'])}", f"₹{DecimalSafe(summary['outstanding'])}",
        ]
        for label, value in zip(self._summary_value_labels, values):
            label.setText(value)


class PDFStudioHubPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.navigate = navigate
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setObjectName("workspaceScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._pdf_scroll = scroll
        content = QWidget()
        content.setObjectName("workspaceCanvas")
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        root = QVBoxLayout(content)
        root.setContentsMargins(26, 20, 26, 22)
        root.setSpacing(15)
        outer.addWidget(scroll)
        scroll.setWidget(content)
        eyebrow = QLabel("DOCUMENT DESIGN  /  PDF STUDIO")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("PDF Studio")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Create consistent, business-ready invoices with reusable layouts and print-aware page settings.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(eyebrow)
        root.addWidget(title)
        root.addWidget(subtitle)

        self.service = BillService(database)
        self.service.ensure_starter_templates(session.business_id)
        self.templates = self.service.list_templates(session.business_id)
        summary = QFrame()
        summary.setObjectName("darkFeaturePanel")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(20, 17, 20, 17)
        left = QVBoxLayout()
        label = QLabel("YOUR DOCUMENT SYSTEM")
        label.setObjectName("taskbarMuted")
        label.setStyleSheet("letter-spacing:1.1px;font-size:9px;")
        self.theme_count_heading = QLabel(f"{len(self.templates)} saved theme{'s' if len(self.templates) != 1 else ''} ready to use")
        heading = self.theme_count_heading
        heading.setObjectName("heroTitle")
        heading.setStyleSheet("font-size:21px;color:#FFFFFF;font-weight:750;")
        body = QLabel("Business identity, mandatory invoice fields and totals are rendered from saved records—not typed into a static design.")
        body.setObjectName("heroBody")
        body.setWordWrap(True)
        left.addWidget(label)
        left.addWidget(heading)
        left.addWidget(body)
        summary_layout.addLayout(left, 1)
        make = HoverButton("Manage themes")
        make.setObjectName("primaryButton")
        make.clicked.connect(lambda: self.navigate("pdf_templates"))
        summary_layout.addWidget(make, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(summary)

        grid = QGridLayout()
        grid.setSpacing(14)
        self._pdf_action_grid = grid
        self._pdf_action_cards = []
        self._pdf_current_columns = 0
        for title_text, description, icon, key, accent in PDF_ACTIONS:
            card = ActionCard(title_text, description, icon, accent)
            card.clicked.connect(lambda checked=False, target=key: self.navigate(target))
            self._pdf_action_cards.append(card)
        self._layout_pdf_action_cards()
        root.addLayout(grid)
        note = QLabel("PDF output is generated from the selected bill and template. WhatsApp opens a prepared chat; attach the generated PDF manually in WhatsApp.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch(1)

    def _layout_pdf_action_cards(self) -> None:
        if not hasattr(self, "_pdf_action_grid"):
            return
        available_width = max(0, self._pdf_scroll.viewport().width() - 52) if hasattr(self, "_pdf_scroll") else max(0, self.width() - 52)
        columns = 3 if available_width >= 1500 else 2 if available_width >= 680 else 1
        if columns == self._pdf_current_columns and self._pdf_action_grid.count() == len(self._pdf_action_cards):
            return
        while self._pdf_action_grid.count():
            self._pdf_action_grid.takeAt(0)
        self._pdf_current_columns = columns
        for index, card in enumerate(self._pdf_action_cards):
            card.setMinimumWidth(0)
            self._pdf_action_grid.addWidget(card, index // columns, index % columns)
        for column in range(3):
            self._pdf_action_grid.setColumnMinimumWidth(column, 0)
            self._pdf_action_grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_pdf_action_cards()

    def refresh(self) -> None:
        self.service.ensure_starter_templates(self.session.business_id)
        self.templates = self.service.list_templates(self.session.business_id)
        self.theme_count_heading.setText(f"{len(self.templates)} saved theme{'s' if len(self.templates) != 1 else ''} ready to use")


def DecimalSafe(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"
