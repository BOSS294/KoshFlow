"""PDF Studio pages: theme library, PDF generator, WhatsApp preparation and exports.

Purpose: Give the billing workspace complete routes for document rendering and template management.
Canonical path: koshflow/ui/pages/pdf_studio_pages.py
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Integration: Pages are routed from BillingHubPage and PDFStudioHubPage.
Changelog: v0.3.0 — Added functional template CRUD, invoice PDF generation, send preparation and export browser.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QColorDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from koshflow.config import ensure_data_dirs
from koshflow.core.database import Database
from koshflow.core.session import Session
from koshflow.core.permissions import has_permission
from koshflow.services.bill_service import BillError, BillService
from koshflow.services.pdf_service import PDFGenerationError, generate_invoice_pdf
from koshflow.services.business_service import BusinessService
from koshflow.services.invoice_profile_service import load_invoice_profile
from koshflow.services.theme_design import resolve_theme_design
from koshflow.ui.pages.invoice_theme_preview import InvoiceThemePreview
from koshflow.ui.components import HoverButton, make_combo, make_line_edit
from koshflow.ui.icons import svg_icon


def _prime_invoice_preview(preview: InvoiceThemePreview, database: Database, session: Session) -> None:
    """Use the business's saved logo, contact and payment details in every invoice preview."""
    try:
        preview.set_invoice_identity(
            BusinessService(database).get_profile(session.business_id),
            load_invoice_profile(database, session.business_id),
        )
    except Exception:
        # Preview must remain available even if an optional profile setting is incomplete.
        preview.set_invoice_identity({}, {})


class PDFTemplatePage(QWidget):
    """Theme library with full-document controls and a live invoice preview."""

    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.navigate = navigate
        self.service = BillService(database)
        self._selected_template_id: str | None = None
        self._color_values: dict[str, str] = {}
        self.service.ensure_starter_templates(session.business_id)

        root = QVBoxLayout(self)
        root.setContentsMargins(27, 22, 27, 20)
        root.setSpacing(15)
        top = QHBoxLayout()
        header = QVBoxLayout()
        eyebrow = QLabel("PDF STUDIO  /  THEME LIBRARY")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Invoice themes")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Design the entire invoice: composition, typography, paper, panels, borders and color contrast.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        header.addWidget(eyebrow)
        header.addWidget(title)
        header.addWidget(subtitle)
        top.addLayout(header, 1)
        back = HoverButton("PDF Studio")
        back.clicked.connect(lambda: self.navigate("pdf_studio"))
        top.addWidget(back, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        library = QFrame()
        library.setObjectName("contentCard")
        library.setMinimumWidth(245)
        library.setMaximumWidth(300)
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(14, 14, 14, 14)
        listing_title = QLabel("Saved themes")
        listing_title.setObjectName("sectionTitle")
        self.theme_list = QListWidget()
        self.theme_list.setObjectName("templateList")
        self.theme_list.currentItemChanged.connect(self._load_selected)
        library_layout.addWidget(listing_title)
        library_layout.addWidget(self.theme_list, 1)
        library_actions = QHBoxLayout()
        new_button = HoverButton("New")
        new_button.setIcon(svg_icon("plus", "#829B3E", 15))
        new_button.clicked.connect(self._new_template)
        duplicate_button = HoverButton("Duplicate")
        duplicate_button.setIcon(svg_icon("copy", "#829B3E", 15))
        duplicate_button.clicked.connect(self._duplicate_template)
        delete_button = HoverButton("Delete")
        delete_button.setIcon(svg_icon("trash-2", "#8B604A", 15))
        delete_button.clicked.connect(self._delete_template)
        library_actions.addWidget(new_button)
        library_actions.addWidget(duplicate_button)
        library_actions.addWidget(delete_button)
        library_layout.addLayout(library_actions)
        columns.addWidget(library)

        form_frame = QFrame()
        form_frame.setObjectName("contentCard")
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_content = QWidget()
        form_layout = QVBoxLayout(form_content)
        form_layout.setContentsMargins(17, 15, 17, 15)
        form_layout.setSpacing(13)
        title_form = QLabel("Document design")
        title_form.setObjectName("sectionTitle")
        form_layout.addWidget(title_form)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.name = make_line_edit("Theme name")
        self.page_size = make_combo(["A4", "A5", "THERMAL_80"], "Document page size")
        self.accent_color = make_line_edit("#C9E86A")
        self.font = make_combo(["Unicode Sans", "Helvetica", "Times-Roman", "Courier"], "Font family")
        self.font_size = QSpinBox()
        self.font_size.setRange(7, 18)
        self.font_size.setValue(9)
        self.design_style = QComboBox()
        for style_key, label in [
            ("modern", "Modern split layout"), ("classic", "Classic invoice"),
            ("editorial", "Editorial / offset header"), ("boxed", "Structured panels"),
            ("minimal", "Minimal rules"), ("compact", "Compact invoice"),
            ("formal", "Formal document"), ("ledger", "Ledger / ruled"),
            ("bold", "Bold accent header"), ("receipt", "Thermal receipt"),
            ("dark", "Charcoal feature blocks"),
        ]:
            self.design_style.addItem(label, style_key)
        self.show_contact = QCheckBox("Show business contact block")
        self.show_contact.setChecked(True)
        self.show_gstin = QCheckBox("Show business GSTIN when available")
        self.show_gstin.setChecked(True)
        self.is_default = QCheckBox("Use as the default PDF theme")
        self.footer = QTextEdit()
        self.footer.setPlaceholderText("Invoice footer note")
        self.footer.setMaximumHeight(75)

        fields = [
            ("Theme name", self.name), ("Page size", self.page_size),
            ("Document composition", self.design_style), ("Font family", self.font),
            ("Accent color (hex)", self.accent_color), ("Base font size", self.font_size),
        ]
        for index, (label_text, widget) in enumerate(fields):
            row, col = divmod(index, 2)
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            label_widget = QLabel(label_text)
            label_widget.setObjectName("muted")
            field_layout.addWidget(label_widget)
            field_layout.addWidget(widget)
            grid.addWidget(field, row, col)
        form_layout.addLayout(grid)

        color_heading = QLabel("Full-document color system")
        color_heading.setObjectName("sectionTitle")
        form_layout.addWidget(color_heading)
        color_hint = QLabel("Colors are contrast-checked before the PDF is drawn. These choices affect the paper, every text block, panels, borders and highlighted totals.")
        color_hint.setObjectName("muted")
        color_hint.setWordWrap(True)
        form_layout.addWidget(color_hint)

        self.color_labels = {
            "page_bg": "Paper background",
            "text": "Main text",
            "muted": "Secondary text",
            "surface": "Panel / table surface",
            "border": "Borders and rules",
            "accent_text": "Text on accent color",
        }
        self.color_buttons: dict[str, QPushButton] = {}
        color_grid = QGridLayout()
        color_grid.setHorizontalSpacing(12)
        color_grid.setVerticalSpacing(9)
        for index, (key, label_text) in enumerate(self.color_labels.items()):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(4)
            label_widget = QLabel(label_text)
            label_widget.setObjectName("muted")
            button = QPushButton("#FFFFFF")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(34)
            button.clicked.connect(lambda checked=False, color_key=key: self._pick_color(color_key))
            self.color_buttons[key] = button
            cell_layout.addWidget(label_widget)
            cell_layout.addWidget(button)
            color_grid.addWidget(cell, index // 2, index % 2)
        form_layout.addLayout(color_grid)

        self.show_contact.setChecked(True)
        for checkbox in (self.show_contact, self.show_gstin, self.is_default):
            form_layout.addWidget(checkbox)
        form_layout.addWidget(QLabel("Footer text"))
        form_layout.addWidget(self.footer)

        swatch_row = QHBoxLayout()
        swatch_label = QLabel("Accent swatch")
        swatch_label.setObjectName("muted")
        self.swatch = QPushButton("Pick accent")
        self.swatch.setFixedSize(100, 30)
        self.swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.swatch.setStyleSheet("background:#C9E86A;color:#171916;border:1px solid #ADBFA0;border-radius:8px;font-weight:650;")
        self.swatch.clicked.connect(self._pick_accent_color)
        self.accent_color.textChanged.connect(self._update_swatch)
        self.accent_color.textChanged.connect(self._refresh_preview)
        self.design_style.currentIndexChanged.connect(self._refresh_preview)
        self.font.currentTextChanged.connect(self._refresh_preview)
        self.font_size.valueChanged.connect(self._refresh_preview)
        self.page_size.currentTextChanged.connect(self._refresh_preview)
        swatch_row.addWidget(swatch_label)
        swatch_row.addStretch(1)
        swatch_row.addWidget(self.swatch)
        form_layout.addLayout(swatch_row)

        form_actions = QHBoxLayout()
        self.save_button = HoverButton("Save theme")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setIcon(svg_icon("check", "#171916", 15))
        self.save_button.clicked.connect(self._save_template)
        self.save_button.setEnabled(has_permission(self.session.role, "billing.theme_manage"))
        self.default_button = HoverButton("Make default")
        self.default_button.clicked.connect(self._make_default)
        self.default_button.setEnabled(has_permission(self.session.role, "billing.theme_manage"))
        new_button.setEnabled(has_permission(self.session.role, "billing.theme_manage"))
        duplicate_button.setEnabled(has_permission(self.session.role, "billing.theme_manage"))
        delete_button.setEnabled(has_permission(self.session.role, "billing.theme_manage"))
        form_actions.addWidget(self.save_button)
        form_actions.addWidget(self.default_button)
        form_layout.addLayout(form_actions)
        note = QLabel("A saved theme controls the composition of the whole invoice. Mandatory bill information remains present for the selected document type.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        form_layout.addWidget(note)
        form_layout.addStretch(1)
        form_scroll.setWidget(form_content)
        wrapper_layout = QVBoxLayout(form_frame)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(form_scroll)
        columns.addWidget(form_frame, 2)

        preview_frame = QFrame()
        preview_frame.setObjectName("contentCard")
        preview_frame.setMinimumWidth(300)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(10)
        preview_title = QLabel("Live bill preview")
        preview_title.setObjectName("sectionTitle")
        preview_note = QLabel("A visual sample of the full page layout. Your saved bill data will replace these sample details when a PDF is generated.")
        preview_note.setObjectName("muted")
        preview_note.setWordWrap(True)
        self.preview = InvoiceThemePreview(compact=False)
        _prime_invoice_preview(self.preview, self.database, self.session)
        self.preview.setMinimumHeight(430)
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(preview_note)
        preview_layout.addWidget(self.preview, 1)
        columns.addWidget(preview_frame, 2)

        root.addLayout(columns, 1)
        self._refresh_templates()

    def _set_color(self, key: str, value: str) -> None:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            return
        self._color_values[key] = value.upper()
        button = self.color_buttons[key]
        button.setText(value.upper())
        from PySide6.QtGui import QColor
        text_color = "#FFFFFF" if self._is_dark_color(value) else "#171916"
        button.setStyleSheet(f"QPushButton{{background:{value};color:{text_color};border:1px solid #C8CEC0;border-radius:7px;text-align:left;padding:6px 9px;font-weight:650;}} QPushButton:hover{{border:2px solid #91AD3D;}}")
        self._refresh_preview()

    @staticmethod
    def _is_dark_color(value: str) -> bool:
        from PySide6.QtGui import QColor
        return QColor(value).lightness() < 145

    def _pick_color(self, key: str) -> None:
        from PySide6.QtGui import QColor
        current = QColor(self._color_values.get(key, "#FFFFFF"))
        picked = QColorDialog.getColor(current, self, f"Choose {self.color_labels[key]}")
        if picked.isValid():
            self._set_color(key, picked.name())

    def _current_layout(self) -> dict:
        return {
            "style": self.design_style.currentData() or "modern",
            "colors": dict(self._color_values),
        }

    def _preview_template(self) -> dict:
        layout = self._current_layout()
        return {
            "template_id": self._selected_template_id or "preview-template",
            "template_name": self.name.text().strip() or "Custom invoice theme",
            "page_size": self.page_size.currentText(),
            "accent_color": self.accent_color.text().strip(),
            "font_family": self.font.currentText(),
            "font_size": self.font_size.value(),
            "layout_json": __import__("json").dumps(layout),
        }

    def _refresh_preview(self, *args) -> None:
        if hasattr(self, "preview"):
            self.preview.set_template(self._preview_template())

    def _refresh_templates(self) -> None:
        templates = self.service.list_templates(self.session.business_id)
        current = self._selected_template_id
        self.theme_list.blockSignals(True)
        self.theme_list.clear()
        for template in templates:
            default_label = "  ·  DEFAULT" if template["is_default"] else ""
            item = QListWidgetItem(f"{template['template_name']}{default_label}\n{template['page_size']}  ·  {template['accent_color']}")
            item.setData(Qt.ItemDataRole.UserRole, template["template_id"])
            self.theme_list.addItem(item)
            if current and template["template_id"] == current:
                self.theme_list.setCurrentItem(item)
        self.theme_list.blockSignals(False)
        if self.theme_list.currentItem():
            self._load_selected(self.theme_list.currentItem(), None)
        elif self.theme_list.count():
            self.theme_list.setCurrentRow(0)
        else:
            self._new_template()

    def _apply_design(self, template: dict) -> None:
        design = resolve_theme_design(template)
        index = self.design_style.findData(design["style"])
        self.design_style.setCurrentIndex(max(0, index))
        for key in self.color_labels:
            self._set_color(key, design["colors"][key])
        self._refresh_preview()

    def _load_selected(self, current, previous) -> None:
        if not current:
            return
        template_id = current.data(Qt.ItemDataRole.UserRole)
        template = next((item for item in self.service.list_templates(self.session.business_id) if item["template_id"] == template_id), None)
        if not template:
            return
        self._selected_template_id = template_id
        self.name.setText(template["template_name"])
        self.page_size.setCurrentText(template["page_size"])
        self.accent_color.setText(template["accent_color"])
        self.font.setCurrentText(template["font_family"])
        self.font_size.setValue(int(template["font_size"]))
        self.show_contact.setChecked(bool(template["show_business_contact"]))
        self.show_gstin.setChecked(bool(template["show_gstin"]))
        self.is_default.setChecked(bool(template["is_default"]))
        self.footer.setPlainText(template["footer_text"])
        self._apply_design(template)
        self.default_button.setEnabled(has_permission(self.session.role, "billing.theme_manage") and not bool(template["is_default"]))

    def _new_template(self) -> None:
        self._selected_template_id = None
        self.theme_list.clearSelection()
        self.name.clear()
        self.page_size.setCurrentText("A4")
        self.accent_color.setText("#C9E86A")
        self.font.setCurrentText("Unicode Sans")
        self.font_size.setValue(9)
        self.show_contact.setChecked(True)
        self.show_gstin.setChecked(True)
        self.is_default.setChecked(False)
        self.footer.setPlainText("Thank you for your business.")
        self._apply_design({"template_name": "KoshFlow Classic", "accent_color": "#C9E86A", "layout_json": "{}"})
        self.default_button.setEnabled(False)

    def _duplicate_template(self) -> None:
        item = self.theme_list.currentItem()
        if not item:
            QMessageBox.information(self, "Select a theme", "Choose a saved theme to duplicate first.")
            return
        source_id = item.data(Qt.ItemDataRole.UserRole)
        source = next((theme for theme in self.service.list_templates(self.session.business_id) if theme["template_id"] == source_id), None)
        if not source:
            QMessageBox.warning(self, "Theme unavailable", "The selected theme could not be found.")
            return
        existing_names = {theme["template_name"].casefold() for theme in self.service.list_templates(self.session.business_id)}
        base_name = f"{source['template_name']} Copy"
        candidate = base_name
        suffix = 2
        while candidate.casefold() in existing_names:
            candidate = f"{base_name} {suffix}"
            suffix += 1
        self._selected_template_id = None
        self.name.setText(candidate)
        self.page_size.setCurrentText(source["page_size"])
        self.accent_color.setText(source["accent_color"])
        self.font.setCurrentText(source["font_family"])
        self.font_size.setValue(int(source["font_size"]))
        self.show_contact.setChecked(bool(source["show_business_contact"]))
        self.show_gstin.setChecked(bool(source["show_gstin"]))
        self.is_default.setChecked(False)
        self.footer.setPlainText(source["footer_text"])
        self._apply_design(source)
        self.default_button.setEnabled(False)
        self.name.setFocus()
        self.name.selectAll()

    def _pick_accent_color(self) -> None:
        from PySide6.QtGui import QColor
        current = QColor(self.accent_color.text().strip() if re.fullmatch(r"#[0-9A-Fa-f]{6}", self.accent_color.text().strip()) else "#C9E86A")
        picked = QColorDialog.getColor(current, self, "Choose invoice accent color")
        if picked.isValid():
            self.accent_color.setText(picked.name().upper())

    def _update_swatch(self, value: str) -> None:
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", value.strip()):
            text_color = "#FFFFFF" if self._is_dark_color(value.strip()) else "#171916"
            self.swatch.setText(value.strip().upper())
            self.swatch.setStyleSheet(f"background:{value.strip()};color:{text_color};border:1px solid #ADBFA0;border-radius:8px;font-weight:650;")
        else:
            self.swatch.setText("Invalid hex")
            self.swatch.setStyleSheet("background:palette(alternate-base);color:palette(text);border:1px solid #C55;border-radius:8px;")

    def _values(self) -> dict:
        return {
            "template_name": self.name.text(), "page_size": self.page_size.currentText(),
            "accent_color": self.accent_color.text().strip(), "font_family": self.font.currentText(),
            "font_size": self.font_size.value(), "show_business_contact": self.show_contact.isChecked(),
            "show_gstin": self.show_gstin.isChecked(), "is_default": self.is_default.isChecked(),
            "footer_text": self.footer.toPlainText(), "layout": self._current_layout(),
        }

    def _save_template(self) -> None:
        try:
            self._selected_template_id = self.service.save_template(
                self.session.business_id, self.session.user_id, self._values(), self._selected_template_id,
            )
            self._refresh_templates()
            QMessageBox.information(self, "Theme saved", "The complete invoice theme has been saved and is ready for bill selection.")
        except (BillError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot save theme", str(exc))

    def _make_default(self) -> None:
        self.is_default.setChecked(True)
        self._save_template()

    def _delete_template(self) -> None:
        item = self.theme_list.currentItem()
        if not item:
            QMessageBox.information(self, "Select a theme", "Choose a saved theme first.")
            return
        template_id = item.data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(self, "Delete PDF theme", f"Delete '{item.text().splitlines()[0]}'? Bills that reference it will use the current default theme when regenerated.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_template(self.session.business_id, self.session.user_id, template_id)
            self._selected_template_id = None
            self.service.ensure_default_template(self.session.business_id)
            self._refresh_templates()
        except BillError as exc:
            QMessageBox.warning(self, "Cannot delete theme", str(exc))


class PDFGeneratorPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.navigate = navigate
        self.service = BillService(database)
        self.service.ensure_starter_templates(session.business_id)
        root = QVBoxLayout(self)
        root.setContentsMargins(27, 22, 27, 20)
        root.setSpacing(15)
        root.addWidget(_eyebrow("PDF STUDIO  /  GENERATE"))
        root.addWidget(_title("Generate PDF"))
        description = QLabel("Choose a saved bill and a document theme. The final file is rendered locally and can be opened or saved elsewhere.")
        description.setObjectName("muted")
        description.setWordWrap(True)
        root.addWidget(description)

        panel = QFrame()
        panel.setObjectName("contentCard")
        form = QVBoxLayout(panel)
        form.setContentsMargins(22, 22, 22, 22)
        form.setSpacing(14)
        form.addWidget(_section_title("Document source"))
        self.bill_combo = QComboBox()
        self.bill_combo.setMinimumHeight(42)
        self.template_combo = QComboBox()
        self.template_combo.setMinimumHeight(42)
        form.addWidget(_labelled("Bill to render", self.bill_combo))
        form.addWidget(_labelled("PDF theme", self.template_combo))
        self.info = QLabel("Select a bill to see a summary.")
        self.info.setObjectName("softPanel")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("padding:13px;border:1px solid palette(mid);border-radius:12px;")
        form.addWidget(self.info)
        actions = QHBoxLayout()
        generate = HoverButton("Generate PDF")
        generate.setObjectName("primaryButton")
        generate.setIcon(svg_icon("file-down", "#171916", 16))
        generate.clicked.connect(self._generate)
        themes = HoverButton("Manage themes")
        themes.clicked.connect(lambda: self.navigate("pdf_templates"))
        actions.addWidget(generate)
        actions.addWidget(themes)
        actions.addStretch(1)
        form.addLayout(actions)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(panel, 3)
        preview_frame = QFrame()
        preview_frame.setObjectName("contentCard")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(9)
        preview_title = QLabel("Selected theme preview")
        preview_title.setObjectName("sectionTitle")
        preview_help = QLabel("Switch themes above to see the full invoice composition update.")
        preview_help.setObjectName("muted")
        preview_help.setWordWrap(True)
        self.theme_preview = InvoiceThemePreview(compact=False)
        _prime_invoice_preview(self.theme_preview, self.database, self.session)
        self.theme_preview.setMinimumHeight(430)
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(preview_help)
        preview_layout.addWidget(self.theme_preview, 1)
        body.addWidget(preview_frame, 2)
        root.addLayout(body, 1)
        self.bill_combo.currentIndexChanged.connect(self._update_summary)
        self.template_combo.currentIndexChanged.connect(self._update_theme_preview)
        self._refresh_sources()

    def refresh_after_return(self) -> None:
        self._refresh_sources()

    def _refresh_sources(self) -> None:
        self.bill_combo.clear()
        rows = self.service.list_bills(self.session.business_id)
        usable = [row for row in rows if row["status"] != "cancelled"]
        for bill in usable:
            label = f"{bill['bill_number']}  ·  {bill['customer_name']}  ·  ₹{float(bill['grand_total']):,.2f}"
            self.bill_combo.addItem(label, bill["bill_id"])
        self.template_combo.clear()
        for template in self.service.list_templates(self.session.business_id):
            suffix = " · Default" if template["is_default"] else ""
            self.template_combo.addItem(f"{template['template_name']}{suffix} ({template['page_size']})", template["template_id"])
        self._update_summary()
        self._update_theme_preview()

    def _update_summary(self, *args) -> None:
        bill_id = self.bill_combo.currentData()
        bill = self.service.get_bill(self.session.business_id, bill_id) if bill_id else None
        if not bill:
            self.info.setText("No saved bills are available yet. Create and save a bill first, then return here to generate the PDF.")
            return
        self.info.setText(
            f"Invoice: {bill['bill_number']}\nCustomer: {bill['customer_name']}\n"
            f"Status: {bill['status'].replace('_', ' ').title()}\nTotal: ₹{float(bill['grand_total']):,.2f}"
        )

    def _update_theme_preview(self, *args) -> None:
        template_id = self.template_combo.currentData() if hasattr(self, "template_combo") else None
        template = next((item for item in self.service.list_templates(self.session.business_id) if item["template_id"] == template_id), None)
        if template is None:
            template = next((item for item in self.service.list_templates(self.session.business_id) if item["is_default"]), None)
        self.theme_preview.set_template(template or {"template_name": "KoshFlow Classic", "accent_color": "#C9E86A", "layout_json": "{}"})

    def _generate(self) -> None:
        bill_id = self.bill_combo.currentData()
        if not bill_id:
            QMessageBox.information(self, "No bill selected", "Create and save a bill before generating a PDF.")
            return
        bill = self.service.get_bill(self.session.business_id, bill_id)
        if not bill:
            QMessageBox.warning(self, "Bill missing", "The selected bill could not be found.")
            self._refresh_sources()
            return
        safe_number = re.sub(r"[^A-Za-z0-9_.-]", "_", bill["bill_number"])
        default_path = Path(ensure_data_dirs()["exports"]) / f"{safe_number}.pdf"
        output, _ = QFileDialog.getSaveFileName(self, "Save invoice PDF", str(default_path), "PDF documents (*.pdf)")
        if not output:
            return
        if not output.lower().endswith(".pdf"):
            output += ".pdf"
        try:
            file_path = generate_invoice_pdf(self.database, self.session.business_id, bill_id, output, self.template_combo.currentData())
            QMessageBox.information(self, "PDF generated", f"Your PDF has been created locally:\n{file_path}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))
        except (PDFGenerationError, BillError, ValueError) as exc:
            QMessageBox.warning(self, "PDF generation failed", str(exc))


class SendBillPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.navigate = navigate
        self.service = BillService(database)
        self.service.ensure_starter_templates(session.business_id)
        self.last_pdf_path: Path | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(27, 22, 27, 20)
        root.setSpacing(15)
        root.addWidget(_eyebrow("BILLING  /  SEND"))
        root.addWidget(_title("Send a bill"))
        subtitle = QLabel("Generate the bill PDF and prepare the customer message. WhatsApp must attach the PDF manually after the chat opens.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("contentCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(13)
        self.bill_combo = QComboBox()
        self.bill_combo.setMinimumHeight(42)
        self.phone = make_line_edit("Customer WhatsApp number, including country code")
        self.message = QTextEdit()
        self.message.setMinimumHeight(145)
        self.message.setPlaceholderText("Message will be prepared from the selected bill…")
        self.template_combo = QComboBox()
        layout.addWidget(_labelled("Select invoice", self.bill_combo))
        layout.addWidget(_labelled("WhatsApp number", self.phone))
        layout.addWidget(_labelled("PDF theme", self.template_combo))
        layout.addWidget(_labelled("Message text", self.message))
        buttons = QHBoxLayout()
        prepare = HoverButton("Generate PDF & open WhatsApp")
        prepare.setObjectName("primaryButton")
        prepare.setIcon(svg_icon("send", "#171916", 16))
        prepare.clicked.connect(self._prepare_and_open)
        open_pdf = HoverButton("Open generated PDF")
        open_pdf.clicked.connect(self._open_pdf)
        copy_path = HoverButton("Show export folder")
        copy_path.clicked.connect(self._open_export_folder)
        buttons.addWidget(prepare)
        buttons.addWidget(open_pdf)
        buttons.addWidget(copy_path)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(panel, 3)
        preview_frame = QFrame()
        preview_frame.setObjectName("contentCard")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(9)
        preview_title = QLabel("Invoice appearance")
        preview_title.setObjectName("sectionTitle")
        preview_help = QLabel("Check the selected theme before generating the PDF to share.")
        preview_help.setObjectName("muted")
        preview_help.setWordWrap(True)
        self.theme_preview = InvoiceThemePreview(compact=True)
        _prime_invoice_preview(self.theme_preview, self.database, self.session)
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(preview_help)
        preview_layout.addWidget(self.theme_preview, 1)
        body.addWidget(preview_frame, 2)
        root.addLayout(body, 1)
        self.bill_combo.currentIndexChanged.connect(self._sync_bill)
        self.template_combo.currentIndexChanged.connect(self._update_theme_preview)
        self._refresh_sources()

    def refresh_after_return(self) -> None:
        self._refresh_sources()

    def _refresh_sources(self) -> None:
        for combo in (self.bill_combo, self.template_combo):
            combo.clear()
        for bill in self.service.list_bills(self.session.business_id):
            if bill["status"] == "cancelled":
                continue
            self.bill_combo.addItem(f"{bill['bill_number']} · {bill['customer_name']} · ₹{float(bill['grand_total']):,.2f}", bill["bill_id"])
        for template in self.service.list_templates(self.session.business_id):
            self.template_combo.addItem(template["template_name"], template["template_id"])
        self._sync_bill()
        self._update_theme_preview()

    def _update_theme_preview(self, *args) -> None:
        template_id = self.template_combo.currentData() if hasattr(self, "template_combo") else None
        template = next((item for item in self.service.list_templates(self.session.business_id) if item["template_id"] == template_id), None)
        if template is None:
            template = next((item for item in self.service.list_templates(self.session.business_id) if item["is_default"]), None)
        self.theme_preview.set_template(template or {"template_name": "KoshFlow Classic", "accent_color": "#C9E86A", "layout_json": "{}"})

    def _sync_bill(self, *args) -> None:
        bill = self.service.get_bill(self.session.business_id, self.bill_combo.currentData()) if self.bill_combo.currentData() else None
        if not bill:
            self.phone.clear()
            self.message.setPlainText("Create a bill first, then select it here to prepare a message.")
            return
        self.phone.setText(bill["customer_phone"])
        balance = float(bill["balance_due"])
        self.message.setPlainText(
            f"Hello {bill['customer_name']},\n\nPlease find invoice {bill['bill_number']} for ₹{float(bill['grand_total']):,.2f}. "
            + (f"Outstanding balance: ₹{balance:,.2f}. " if balance > 0 else "The invoice is fully paid. ")
            + "Thank you for your business."
        )

    def _prepare_and_open(self) -> None:
        bill_id = self.bill_combo.currentData()
        bill = self.service.get_bill(self.session.business_id, bill_id) if bill_id else None
        if not bill:
            QMessageBox.information(self, "No bill selected", "Create and save a bill before sending it.")
            return
        phone = re.sub(r"\D", "", self.phone.text())
        if len(phone) < 8:
            QMessageBox.warning(self, "Check WhatsApp number", "Enter the customer's full WhatsApp number, including country code digits.")
            return
        if not bill["customer_phone"] and not self.phone.text().strip():
            QMessageBox.warning(self, "Phone number required", "Enter a WhatsApp number first.")
            return
        exports = Path(ensure_data_dirs()["exports"])
        safe_number = re.sub(r"[^A-Za-z0-9_.-]", "_", bill["bill_number"])
        output_path = exports / f"{safe_number}.pdf"
        try:
            self.last_pdf_path = generate_invoice_pdf(
                self.database, self.session.business_id, bill_id, output_path, self.template_combo.currentData(),
            )
        except (PDFGenerationError, BillError, ValueError) as exc:
            QMessageBox.warning(self, "PDF generation failed", str(exc))
            return
        message = self.message.toPlainText().strip()
        url = QUrl(f"https://wa.me/{phone}?text={quote(message)}")
        opened = QDesktopServices.openUrl(url)
        QMessageBox.information(
            self, "Bill prepared",
            f"PDF saved to:\n{self.last_pdf_path}\n\n" +
            ("WhatsApp was opened. Attach this PDF to the chat before sending." if opened else
             "The PDF is ready, but WhatsApp could not be opened automatically. Open WhatsApp and attach this PDF manually."),
        )

    def _open_pdf(self) -> None:
        if self.last_pdf_path and self.last_pdf_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_pdf_path)))
        else:
            QMessageBox.information(self, "No PDF yet", "Generate a PDF first.")

    def _open_export_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ensure_data_dirs()["exports"])))


class BillingExportsPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.navigate = navigate
        self.export_dir = Path(ensure_data_dirs()["exports"])
        root = QVBoxLayout(self)
        root.setContentsMargins(27, 22, 27, 20)
        root.setSpacing(15)
        top = QHBoxLayout()
        copy = QVBoxLayout()
        copy.addWidget(_eyebrow("DOCUMENTS  /  LOCAL EXPORTS"))
        copy.addWidget(_title("Exports & documents"))
        note = QLabel("Files listed here are stored locally in your KoshFlow exports directory.")
        note.setObjectName("muted")
        copy.addWidget(note)
        top.addLayout(copy, 1)
        folder = HoverButton("Open folder")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.export_dir))))
        top.addWidget(folder, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)
        panel = QFrame()
        panel.setObjectName("contentCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        self.list = QListWidget()
        self.list.setMinimumHeight(300)
        self.list.itemDoubleClicked.connect(self._open_selected)
        layout.addWidget(self.list)
        actions = QHBoxLayout()
        open_file = HoverButton("Open selected")
        open_file.clicked.connect(self._open_selected)
        refresh = HoverButton("Refresh")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(open_file)
        actions.addWidget(refresh)
        actions.addStretch(1)
        layout.addLayout(actions)
        root.addWidget(panel, 1)
        root.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        files = sorted(self.export_dir.glob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files:
            item = QListWidgetItem(f"{path.name}\n{path.stat().st_size / 1024:.1f} KB · {path.stat().st_mtime_ns}")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.list.addItem(item)
        if not files:
            self.list.addItem(QListWidgetItem("No PDF exports yet. Generate a bill PDF to see it here."))

    def _open_selected(self, item=None) -> None:
        current = item or self.list.currentItem()
        path = current.data(Qt.ItemDataRole.UserRole) if current else None
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif current:
            QMessageBox.information(self, "No file selected", "Select a generated PDF file first.")


def _eyebrow(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("eyebrow")
    return label


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("pageTitle")
    return label


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _labelled(label_text: str, widget: QWidget) -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    label = QLabel(label_text)
    label.setObjectName("muted")
    label.setStyleSheet("font-size:11px;font-weight:650;")
    layout.addWidget(label)
    layout.addWidget(widget)
    return wrapper
