"""Reusable live preview for invoice theme selection and PDF Studio.

Purpose: Show a visual document preview when users select or customize an invoice theme.
Canonical path: koshflow/ui/pages/invoice_theme_preview.py
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Integration: Instantiate InvoiceThemePreview and call set_template(template_row).
Changelog: v0.3.1 — Added coordinated full-document live theme preview.
"""

from __future__ import annotations

from typing import Any
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from koshflow.services.theme_design import resolve_theme_design


class InvoiceThemePreview(QWidget):
    """Small but readable representation of a full invoice theme, not a color swatch."""

    def __init__(self, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self.compact = compact
        self.template: dict[str, Any] = {}
        self.business_profile: dict[str, Any] = {}
        self.invoice_profile: dict[str, Any] = {}
        self.setObjectName("invoiceThemePreviewHost")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._rebuild()

    @staticmethod
    def _label(text: str, color: str, size: int, bold: bool = False) -> QLabel:
        label = QLabel(text)
        weight = 750 if bold else 450
        label.setStyleSheet(f"color:{color};font-size:{size}px;font-weight:{weight};background:transparent;border:none;")
        label.setWordWrap(True)
        return label

    def set_template(self, template: dict[str, Any] | None) -> None:
        self.template = dict(template or {})
        self._rebuild()

    def set_invoice_identity(self, business_profile: dict[str, Any] | None,
                             invoice_profile: dict[str, Any] | None) -> None:
        """Show the actual configured business identity and payment options in preview."""
        self.business_profile = dict(business_profile or {})
        self.invoice_profile = dict(invoice_profile or {})
        self._rebuild()

    def _rebuild(self) -> None:
        while self._root_layout.count():
            item = self._root_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        design = resolve_theme_design(self.template)
        colors = design["colors"]
        accent, page, text = design["accent"], colors["page_bg"], colors["text"]
        muted, surface, border = colors["muted"], colors["surface"], colors["border"]
        surface_text = colors.get("surface_text", text)
        surface_muted = colors.get("surface_muted", muted)
        accent_text, style = colors["accent_text"], design["style"]
        paper = QFrame()
        paper.setObjectName("invoicePreviewPaper")
        paper.setStyleSheet(f"QFrame#invoicePreviewPaper{{background:{page};border:1px solid {border};border-radius:10px;}}")
        paper_layout = QVBoxLayout(paper)
        paper_layout.setContentsMargins(14 if self.compact else 20, 0, 14 if self.compact else 20, 12 if self.compact else 16)
        paper_layout.setSpacing(9 if self.compact else 12)
        self._root_layout.addWidget(paper)

        accent_bar = QFrame()
        accent_bar.setFixedHeight(5 if style in {"bold", "dark"} else 3)
        accent_bar.setStyleSheet(f"background:{accent};border:none;border-radius:1px;")
        # Extend the top stripe to the edge of the paper, with rounded paper corners clipping naturally.
        top_wrap = QWidget()
        top_wrap_layout = QHBoxLayout(top_wrap)
        top_wrap_layout.setContentsMargins(-14 if self.compact else -20, 0, -14 if self.compact else -20, 0)
        top_wrap_layout.addWidget(accent_bar)
        paper_layout.addWidget(top_wrap)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        business = QVBoxLayout()
        business.setSpacing(3)
        profile = self.business_profile
        payment = self.invoice_profile
        business_name = str(profile.get("trade_name") or profile.get("legal_name") or "YOUR BUSINESS NAME")
        brand = self._label(business_name, text, 12 if self.compact else 14, True)
        brand.setMaximumHeight(34)
        business.addWidget(brand)
        address = ", ".join(part for part in (
            str(profile.get("address") or ""), str(profile.get("city") or ""),
            str(profile.get("state") or ""), str(profile.get("pincode") or ""),
        ) if part)
        contact = " · ".join(part for part in (
            str(profile.get("phone") or ""), str(profile.get("email") or ""),
            str(payment.get("website") or ""),
        ) if part)
        gstin = str(profile.get("gstin") or "")
        business.addWidget(self._label(address or "Business address", muted, 8 if self.compact else 9))
        business.addWidget(self._label(contact or (f"GSTIN: {gstin}" if gstin else "Business contact details"), muted, 8 if self.compact else 9))
        if contact and gstin:
            business.addWidget(self._label(f"GSTIN: {gstin}", muted, 8 if self.compact else 9))
        invoice = QVBoxLayout()
        invoice.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        invoice.setSpacing(4)
        invoice_title = self._label("TAX INVOICE", accent_text if style in {"bold", "dark", "boxed"} else text, 10 if self.compact else 12, True)
        invoice_title.setAlignment(Qt.AlignmentFlag.AlignRight)
        invoice_num = self._label("KF-2026-00001", text, 8 if self.compact else 9, True)
        invoice_num.setAlignment(Qt.AlignmentFlag.AlignRight)
        invoice.addWidget(invoice_title)
        invoice.addWidget(invoice_num)
        logo_path = str(payment.get("logo_path") or "")
        logo_widget = None
        if logo_path and Path(logo_path).is_file():
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                logo_widget = QLabel()
                logo_widget.setFixedSize(48 if self.compact else 58, 48 if self.compact else 58)
                logo_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                logo_widget.setPixmap(pixmap.scaled(
                    logo_widget.size(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                logo_widget.setStyleSheet("background:transparent;border:none;")
        business_identity = QHBoxLayout()
        business_identity.setSpacing(9)
        if logo_widget is not None:
            business_identity.addWidget(logo_widget, 0, Qt.AlignmentFlag.AlignTop)
        business_identity.addLayout(business, 1)
        if style in {"bold", "dark", "boxed"}:
            invoice_panel = QFrame()
            invoice_panel.setStyleSheet(f"background:{accent};border:1px solid {border};border-radius:6px;")
            invoice_panel_layout = QVBoxLayout(invoice_panel)
            invoice_panel_layout.setContentsMargins(8, 7, 8, 7)
            invoice_panel_layout.addLayout(invoice)
            header_row.addLayout(business_identity, 6)
            header_row.addWidget(invoice_panel, 4)
        elif style == "receipt":
            header_row.addLayout(business_identity)
            header_row.addLayout(invoice)
        else:
            header_row.addLayout(business_identity, 6)
            header_row.addLayout(invoice, 4)
        paper_layout.addLayout(header_row)

        if style in {"editorial", "ledger", "formal"}:
            rule = QFrame()
            rule.setFixedHeight(1)
            rule.setStyleSheet(f"background:{accent};border:none;")
            paper_layout.addWidget(rule)

        party = QFrame()
        party.setStyleSheet(f"background:{surface};border:1px solid {border};border-radius:6px;")
        party_layout = QHBoxLayout(party)
        party_layout.setContentsMargins(9, 7, 9, 7)
        customer_col = QVBoxLayout()
        customer_col.setSpacing(3)
        party_uses_surface = style in {"boxed", "modern", "bold", "dark"}
        party_text = surface_text if party_uses_surface else text
        party_muted = surface_muted if party_uses_surface else muted
        customer_col.addWidget(self._label("BILL TO", party_muted, 8 if self.compact else 9, True))
        customer_col.addWidget(self._label("Customer or business name", party_text, 9 if self.compact else 10, True))
        customer_col.addWidget(self._label("Billing address · Contact details", party_muted, 8 if self.compact else 9))
        meta_col = QVBoxLayout()
        meta_col.setSpacing(3)
        meta_col.addWidget(self._label("DATE", party_muted, 8, True))
        meta_col.addWidget(self._label("14 Oct 2026", party_text, 9, True))
        meta_col.addWidget(self._label("DUE · 29 Oct 2026", party_muted, 8))
        party_layout.addLayout(customer_col, 7)
        party_layout.addLayout(meta_col, 3)
        if style not in {"boxed", "modern", "bold", "dark"}:
            party.setStyleSheet(f"background:{page};border:1px solid {border};border-radius:6px;")
        paper_layout.addWidget(party)

        table = QFrame()
        table.setStyleSheet(f"background:{page};border:1px solid {border};border-radius:5px;")
        table_layout = QVBoxLayout(table)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_head = QFrame()
        table_head.setStyleSheet(f"background:{accent};border:none;border-radius:4px 4px 0 0;")
        table_head_layout = QHBoxLayout(table_head)
        table_head_layout.setContentsMargins(7, 6, 7, 6)
        table_head_layout.addWidget(self._label("ITEM / SERVICE", accent_text, 7 if self.compact else 8, True), 5)
        table_head_layout.addWidget(self._label("QTY", accent_text, 7 if self.compact else 8, True), 1)
        table_head_layout.addWidget(self._label("AMOUNT", accent_text, 7 if self.compact else 8, True), 2)
        table_layout.addWidget(table_head)
        for index, row in enumerate((("Professional service", "2", "₹ 1,000.00"), ("Additional item", "1", "₹ 250.00"))):
            use_surface = style not in {"minimal", "editorial"} and index == 1
            row_frame = QFrame()
            row_frame.setStyleSheet(f"background:{surface if use_surface else page};border:none;border-top:1px solid {border};")
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(7, 6, 7, 6)
            row_color = surface_text if use_surface else text
            row_layout.addWidget(self._label(row[0], row_color, 8 if self.compact else 9), 5)
            row_layout.addWidget(self._label(row[1], row_color, 8 if self.compact else 9), 1)
            amount = self._label(row[2], row_color, 8 if self.compact else 9)
            amount.setAlignment(Qt.AlignmentFlag.AlignRight)
            row_layout.addWidget(amount, 2)
            table_layout.addWidget(row_frame)
        paper_layout.addWidget(table)

        totals = QFrame()
        totals.setStyleSheet(f"background:{surface};border:1px solid {border};border-radius:6px;")
        totals_layout = QVBoxLayout(totals)
        totals_layout.setContentsMargins(9, 7, 9, 7)
        totals_layout.setSpacing(4)
        for label, value in (("Subtotal", "₹ 1,250.00"), ("Tax", "₹ 225.00")):
            row = QHBoxLayout()
            row.addWidget(self._label(label, surface_muted, 8 if self.compact else 9))
            row.addStretch(1)
            row.addWidget(self._label(value, surface_text, 8 if self.compact else 9))
            totals_layout.addLayout(row)
        total_row = QFrame()
        total_row.setStyleSheet(f"background:{accent};border:none;border-radius:5px;")
        total_row_layout = QHBoxLayout(total_row)
        total_row_layout.setContentsMargins(7, 6, 7, 6)
        total_row_layout.addWidget(self._label("TOTAL DUE", accent_text, 9 if self.compact else 10, True))
        total_row_layout.addStretch(1)
        total_row_layout.addWidget(self._label("₹ 1,475.00", accent_text, 9 if self.compact else 10, True))
        totals_layout.addWidget(total_row)
        paper_layout.addWidget(totals)

        bank_lines = []
        if payment.get("show_bank", True):
            for label, key in (("Account holder", "bank_account_name"), ("Bank", "bank_name"),
                               ("Account no.", "account_number"), ("IFSC", "ifsc"), ("Branch", "branch")):
                value = str(payment.get(key) or "").strip()
                if value:
                    bank_lines.append(f"{label}: {value}")
        upi_id = str(payment.get("upi_id") or "").strip() if payment.get("show_upi", True) else ""
        qr_path = str(payment.get("qr_code_path") or "") if payment.get("show_qr", True) else ""
        qr_pixmap = QPixmap(qr_path) if qr_path and Path(qr_path).is_file() else QPixmap()
        if bank_lines or upi_id or not qr_pixmap.isNull():
            pay_panel = QFrame()
            pay_panel.setStyleSheet(f"background:{surface};border:1px solid {border};border-radius:6px;")
            pay_layout = QHBoxLayout(pay_panel)
            pay_layout.setContentsMargins(9, 7, 9, 7)
            pay_layout.setSpacing(10)
            pay_text = QVBoxLayout()
            pay_text.setSpacing(3)
            pay_text.addWidget(self._label("PAYMENT DETAILS", surface_muted, 8 if self.compact else 9, True))
            for line in bank_lines:
                pay_text.addWidget(self._label(line, surface_text, 8 if self.compact else 9))
            if upi_id:
                pay_text.addWidget(self._label(f"UPI: {upi_id}", surface_text, 8 if self.compact else 9, True))
            pay_layout.addLayout(pay_text, 1)
            if not qr_pixmap.isNull():
                qr = QLabel()
                qr.setFixedSize(64 if self.compact else 76, 64 if self.compact else 76)
                qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
                qr.setPixmap(qr_pixmap.scaled(qr.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                qr.setStyleSheet("background:transparent;border:none;")
                pay_layout.addWidget(qr, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            paper_layout.addWidget(pay_panel)

        footer = self._label("Thank you for your business.  ·  Generated by KoshFlow", muted, 8, False)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        paper_layout.addWidget(footer)
        self.setMinimumHeight(250 if self.compact else 300)
