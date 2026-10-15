"""Read-only bill details with lifecycle-safe actions.

Purpose: Present saved invoice, item, amount and payment details from local records.
Canonical path: koshflow/ui/pages/bill_detail_page.py
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Integration: Route to bill_view:<bill_id> from the bill register.
Changelog: v0.3.0 — Added a dedicated invoice details and payment-history page.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from koshflow.config import ensure_data_dirs
from koshflow.core.database import Database
from koshflow.core.permissions import has_permission
from koshflow.core.session import Session
from koshflow.services.bill_service import BillError, BillService
from koshflow.services.pdf_service import PDFGenerationError, generate_invoice_pdf
from koshflow.ui.components import HoverButton
from koshflow.ui.icons import svg_icon


class BillDetailPage(QWidget):
    def __init__(self, database: Database, session: Session, bill_id: str, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.bill_id = bill_id
        self.navigate = navigate
        self.service = BillService(database)

        root = QVBoxLayout(self)
        root.setContentsMargins(27, 22, 27, 20)
        root.setSpacing(14)

        top = QHBoxLayout()
        heading = QVBoxLayout()
        eyebrow = QLabel("BILLING  /  BILL DETAILS")
        eyebrow.setObjectName("eyebrow")
        self.title = QLabel("Bill details")
        self.title.setObjectName("pageTitle")
        self.subtitle = QLabel("Saved invoice record and payment history.")
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        heading.addWidget(eyebrow)
        heading.addWidget(self.title)
        heading.addWidget(self.subtitle)
        top.addLayout(heading, 1)

        self.edit_button = HoverButton("Edit draft")
        self.edit_button.setIcon(svg_icon("pencil", "#829B3E", 15))
        self.edit_button.clicked.connect(lambda: self.navigate(f"bill_edit:{self.bill_id}"))
        self.payment_button = HoverButton("Record payment")
        self.payment_button.setIcon(svg_icon("hand-coins", "#829B3E", 15))
        self.payment_button.clicked.connect(self._record_payment)
        self.pdf_button = HoverButton("Generate PDF")
        self.pdf_button.setObjectName("primaryButton")
        self.pdf_button.setIcon(svg_icon("file-down", "#171916", 15))
        self.pdf_button.clicked.connect(self._generate_pdf)
        self.cancel_button = HoverButton("Cancel issued bill")
        self.cancel_button.clicked.connect(self._cancel_bill)
        self.back_button = HoverButton("Manage bills")
        self.back_button.clicked.connect(lambda: self.navigate("billing_manage"))
        for button in (self.edit_button, self.payment_button, self.pdf_button, self.cancel_button, self.back_button):
            top.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(1, 1, 8, 4)
        content_layout.setSpacing(13)
        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)

        self.summary_card = QFrame()
        self.summary_card.setObjectName("contentCard")
        summary_layout = QGridLayout(self.summary_card)
        summary_layout.setContentsMargins(17, 14, 17, 14)
        summary_layout.setHorizontalSpacing(22)
        summary_layout.setVerticalSpacing(7)
        self.summary_labels: dict[str, QLabel] = {}
        for index, (key, label) in enumerate((
            ("number", "Invoice number"), ("status", "Status"), ("invoice_date", "Invoice date"),
            ("due_date", "Due date"), ("subtotal", "Subtotal"), ("discount_total", "Total discount"),
            ("taxable_total", "Taxable value"), ("tax_total", "Tax total"),
            ("grand_total", "Grand total"), ("amount_paid", "Amount paid"),
            ("balance_due", "Balance due"), ("template_name", "PDF theme"),
        )):
            cell = QVBoxLayout()
            caption = QLabel(label.upper())
            caption.setObjectName("eyebrow")
            value = QLabel("—")
            value.setObjectName("sectionTitle")
            value.setWordWrap(True)
            cell.addWidget(caption)
            cell.addWidget(value)
            summary_layout.addLayout(cell, index // 4, index % 4)
            self.summary_labels[key] = value
        content_layout.addWidget(self.summary_card)

        details_row = QHBoxLayout()
        details_row.setSpacing(14)
        self.customer_card, self.customer_detail = self._info_card("Customer / party")
        self.invoice_card, self.invoice_detail = self._info_card("Invoice information")
        details_row.addWidget(self.customer_card, 1)
        details_row.addWidget(self.invoice_card, 1)
        content_layout.addLayout(details_row)

        self.items_card = QFrame()
        self.items_card.setObjectName("contentCard")
        items_layout = QVBoxLayout(self.items_card)
        items_layout.setContentsMargins(13, 12, 13, 13)
        self.items_title = QLabel("Bill items")
        self.items_title.setObjectName("sectionTitle")
        items_layout.addWidget(self.items_title)
        self.items_table = QTableWidget(0, 8)
        self.items_table.setHorizontalHeaderLabels(["Item / service", "HSN/SAC", "Qty", "Unit", "Rate", "Discount", "GST %", "Line total"])
        self._style_table(self.items_table)
        self.items_table.setMinimumHeight(175)
        items_layout.addWidget(self.items_table)
        content_layout.addWidget(self.items_card)

        self.payments_card = QFrame()
        self.payments_card.setObjectName("contentCard")
        payments_layout = QVBoxLayout(self.payments_card)
        payments_layout.setContentsMargins(13, 12, 13, 13)
        payments_title = QLabel("Payment history")
        payments_title.setObjectName("sectionTitle")
        payments_layout.addWidget(payments_title)
        self.payments_table = QTableWidget(0, 4)
        self.payments_table.setHorizontalHeaderLabels(["Recorded at", "Amount", "Method", "Reference"])
        self._style_table(self.payments_table)
        self.payments_table.setMinimumHeight(105)
        payments_layout.addWidget(self.payments_table)
        content_layout.addWidget(self.payments_card)
        content_layout.addStretch(1)
        self.refresh()

    @staticmethod
    def _style_table(table: QTableWidget) -> None:
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)

    @staticmethod
    def _info_card(title: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setObjectName("contentCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 13, 15, 14)
        caption = QLabel(title)
        caption.setObjectName("sectionTitle")
        layout.addWidget(caption)
        detail = QLabel("—")
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        detail.setMinimumHeight(62)
        layout.addWidget(detail)
        return frame, detail

    def refresh(self) -> None:
        bill = self.service.get_bill(self.session.business_id, self.bill_id)
        if not bill:
            self.title.setText("Bill not found")
            self.subtitle.setText("This invoice may have been removed or does not belong to this business.")
            for button in (self.edit_button, self.payment_button, self.pdf_button, self.cancel_button):
                button.setEnabled(False)
            return

        self.title.setText(bill["bill_number"])
        self.subtitle.setText(f"{bill['customer_name']}  ·  {bill['document_type'].replace('_', ' ').title()}  ·  {bill['customer_type']}")
        displayed = {
            "number": bill["bill_number"],
            "status": bill["status"].replace("_", " ").title(),
            "invoice_date": bill["invoice_date"] or "—",
            "due_date": bill["due_date"] or "Not set",
            "subtotal": f"₹ {Decimal(bill['subtotal']):,.2f}",
            "discount_total": f"₹ {Decimal(bill['discount_total']):,.2f}",
            "taxable_total": f"₹ {Decimal(bill['taxable_total']):,.2f}",
            "tax_total": f"₹ {Decimal(bill['tax_total']):,.2f}",
            "grand_total": f"₹ {Decimal(bill['grand_total']):,.2f}",
            "amount_paid": f"₹ {Decimal(bill['amount_paid']):,.2f}",
            "balance_due": f"₹ {Decimal(bill['balance_due']):,.2f}",
            "template_name": bill.get("template_name") or "Current default",
        }
        for key, value in displayed.items():
            self.summary_labels[key].setText(value)

        customer = [bill["customer_name"], bill["customer_phone"], bill["customer_email"], bill["customer_address"], f"GSTIN: {bill['customer_gstin']}" if bill["customer_gstin"] else ""]
        self.customer_detail.setText("\n".join(value for value in customer if value) or "No customer details recorded.")
        with self.database.connection() as conn:
            profile = conn.execute("SELECT legal_name, trade_name, gstin, address, city, state, pincode FROM businesses WHERE business_id = ?", (self.session.business_id,)).fetchone()
        profile = dict(profile) if profile else {}
        business_lines = [profile.get("trade_name") or profile.get("legal_name", ""), profile.get("address", ""), ", ".join(part for part in (profile.get("city", ""), profile.get("state", ""), profile.get("pincode", "")) if part)]
        if profile.get("gstin"):
            business_lines.append(f"Business GSTIN: {profile['gstin']}")
        business_lines.extend([
            f"Place of supply: {bill['place_of_supply']}" if bill["place_of_supply"] else "",
            f"Notes: {bill['notes']}" if bill["notes"] else "",
            f"Terms: {bill['terms']}" if bill["terms"] else "",
            f"Created: {bill['created_at']}",
        ])
        self.invoice_detail.setText("\n".join(value for value in business_lines if value) or "Business information not available.")

        self.items_table.setRowCount(0)
        for line in bill["items"]:
            row = self.items_table.rowCount()
            self.items_table.insertRow(row)
            values = [line["description"], line["hsn_sac"], line["quantity"], line["unit"], f"₹ {Decimal(line['unit_price']):,.2f}", f"{line['discount_percent']}%", f"{line['tax_rate']}%", f"₹ {Decimal(line['line_total']):,.2f}"]
            for col, value in enumerate(values):
                self.items_table.setItem(row, col, QTableWidgetItem(str(value)))

        self.payments_table.setRowCount(0)
        for payment in bill["payments"]:
            row = self.payments_table.rowCount()
            self.payments_table.insertRow(row)
            values = [payment["paid_at"], f"₹ {Decimal(payment['amount']):,.2f}", payment["payment_method"], payment["reference"] or "—"]
            for col, value in enumerate(values):
                self.payments_table.setItem(row, col, QTableWidgetItem(str(value)))
        if not bill["payments"]:
            self.payments_table.setRowCount(1)
            empty = QTableWidgetItem("No payments recorded")
            empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.payments_table.setItem(0, 0, empty)
            self.payments_table.setSpan(0, 0, 1, 4)

        role = self.session.role
        status = bill["status"]
        self.edit_button.setEnabled(status == "draft" and has_permission(role, "billing.edit_draft"))
        self.payment_button.setEnabled(status in {"issued", "part_paid"} and has_permission(role, "billing.payment"))
        self.pdf_button.setEnabled(status != "cancelled" and has_permission(role, "billing.pdf"))
        self.cancel_button.setEnabled(status == "issued" and has_permission(role, "billing.cancel"))

    def _generate_pdf(self) -> None:
        bill = self.service.get_bill(self.session.business_id, self.bill_id)
        if not bill:
            return
        safe_number = "".join(character if character.isalnum() or character in "-_." else "_" for character in bill["bill_number"])
        path = Path(ensure_data_dirs()["exports"]) / f"{safe_number}.pdf"
        try:
            created = generate_invoice_pdf(self.database, self.session.business_id, self.bill_id, path)
            QMessageBox.information(self, "PDF generated", f"PDF saved to:\n{created}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(created)))
        except (PDFGenerationError, BillError, ValueError) as exc:
            QMessageBox.warning(self, "PDF generation failed", str(exc))

    def _record_payment(self) -> None:
        bill = self.service.get_bill(self.session.business_id, self.bill_id)
        if not bill:
            return
        due = float(bill["balance_due"])
        amount, accepted = QInputDialog.getDouble(self, "Record payment", f"Outstanding balance: ₹{due:,.2f}\nPayment amount (₹):", due, 0.01, due, 2)
        if not accepted:
            return
        method, accepted = QInputDialog.getItem(self, "Payment method", "Select payment method:", ["UPI", "Cash", "Bank transfer", "Card", "Cheque", "Other"], 0, False)
        if not accepted:
            return
        reference, accepted = QInputDialog.getText(self, "Payment reference", "UTR / transaction reference (optional):")
        if not accepted:
            reference = ""
        try:
            self.service.record_payment(self.session.business_id, self.session.user_id, self.bill_id, amount, method, reference)
            self.refresh()
        except BillError as exc:
            QMessageBox.warning(self, "Payment not recorded", str(exc))

    def _cancel_bill(self) -> None:
        reason, accepted = QInputDialog.getText(self, "Cancel issued bill", "Reason for cancellation (required):")
        if not accepted:
            return
        try:
            self.service.cancel_bill(self.session.business_id, self.session.user_id, self.bill_id, reason)
            self.refresh()
        except BillError as exc:
            QMessageBox.warning(self, "Cannot cancel bill", str(exc))
