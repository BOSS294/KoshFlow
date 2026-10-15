"""Bill register with search, lifecycle controls, payment recording and export.

Purpose: Operate on saved bills without bypassing BillService lifecycle validations.
Canonical path: koshflow/ui/pages/bill_list_page.py
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Integration: Instantiate with the database, session and navigation callback.
Changelog: v0.3.0 — Added searchable bill register and permitted CRUD/payment actions.
"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from koshflow.config import ensure_data_dirs
from koshflow.core.database import Database
from koshflow.core.session import Session
from koshflow.core.permissions import has_permission
from koshflow.services.bill_service import BillError, BillService
from koshflow.services.pdf_service import PDFGenerationError, generate_invoice_pdf
from koshflow.ui.components import HoverButton, make_line_edit
from koshflow.ui.icons import svg_icon


class BillListPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.navigate = navigate
        self.service = BillService(database)
        self.selected_bill_id: str | None = None
        self._rows: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(27, 22, 27, 20)
        root.setSpacing(15)

        top = QHBoxLayout()
        text = QVBoxLayout()
        eyebrow = QLabel("BILLING  /  REGISTER")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Manage bills")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Search the register, manage drafts, issue invoices, record payments and export a clean bill list.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        text.addWidget(eyebrow)
        text.addWidget(title)
        text.addWidget(subtitle)
        top.addLayout(text, 1)
        create = HoverButton("Create bill")
        create.setObjectName("primaryButton")
        create.setIcon(svg_icon("plus", "#171916", 16))
        create.clicked.connect(lambda: self.navigate("billing_create"))
        top.addWidget(create, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        filters = QFrame()
        filters.setObjectName("sectionToolbar")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(10, 7, 10, 7)
        self.search = make_line_edit("Search invoice, customer, phone or GSTIN…")
        self.search.setMinimumWidth(300)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "draft", "issued", "part_paid", "paid", "cancelled"])
        self.status_filter.setMinimumWidth(140)
        self.status_filter.currentTextChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        filter_layout.addWidget(self.search, 1)
        filter_layout.addWidget(QLabel("Status"))
        filter_layout.addWidget(self.status_filter)
        export_button = HoverButton("Export CSV")
        export_button.setIcon(svg_icon("file-spreadsheet", "#829B3E", 16))
        export_button.clicked.connect(self.export_csv)
        filter_layout.addWidget(export_button)
        refresh_button = HoverButton("Refresh")
        refresh_button.setIcon(svg_icon("refresh-cw", "#829B3E", 15))
        refresh_button.clicked.connect(self.refresh)
        filter_layout.addWidget(refresh_button)
        root.addWidget(filters)

        self.table_frame = QFrame()
        self.table_frame.setObjectName("contentCard")
        table_layout = QVBoxLayout(self.table_frame)
        table_layout.setContentsMargins(12, 12, 12, 12)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Invoice", "Customer", "Type", "Date", "Status", "Total", "Paid", "Balance"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(330)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 235)
        self.table.setColumnWidth(2, 72)
        self.table.setColumnWidth(3, 112)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 120)
        self.table.setColumnWidth(6, 120)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(self._open_selected)
        table_layout.addWidget(self.table)
        self.table_empty = QLabel("No bills match this view. Create a bill to begin your register.")
        self.table_empty.setObjectName("muted")
        self.table_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        table_layout.addWidget(self.table_empty)
        root.addWidget(self.table_frame, 1)

        actions = QHBoxLayout()
        self.view_button = HoverButton("View details")
        self.view_button.setIcon(svg_icon("file-text", "#829B3E", 15))
        self.view_button.clicked.connect(self._view_selected)
        self.edit_button = HoverButton("Edit draft")
        self.edit_button.setIcon(svg_icon("pencil", "#829B3E", 15))
        self.edit_button.clicked.connect(self._edit_selected)
        self.issue_button = HoverButton("Issue bill")
        self.issue_button.setObjectName("primaryButton")
        self.issue_button.clicked.connect(self._issue_selected)
        self.payment_button = HoverButton("Record payment")
        self.payment_button.clicked.connect(self._record_payment)
        self.pdf_button = HoverButton("Generate PDF")
        self.pdf_button.setIcon(svg_icon("file-down", "#829B3E", 15))
        self.pdf_button.clicked.connect(self._generate_pdf)
        self.cancel_button = HoverButton("Cancel issued bill")
        self.cancel_button.clicked.connect(self._cancel_selected)
        self.delete_button = HoverButton("Delete draft")
        self.delete_button.clicked.connect(self._delete_selected)
        self.back_button = HoverButton("Billing home")
        self.back_button.clicked.connect(lambda: self.navigate("billing"))
        for button in [self.view_button, self.edit_button, self.issue_button, self.payment_button, self.pdf_button, self.cancel_button, self.delete_button, self.back_button]:
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)
        self.refresh()

    def refresh(self, *args) -> None:
        try:
            self._rows = self.service.list_bills(
                self.session.business_id, self.search.text() if hasattr(self, "search") else "",
                self.status_filter.currentText() if hasattr(self, "status_filter") else "All",
            )
        except Exception:
            self._rows = []
        self.table.setRowCount(0)
        for row_data in self._rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            display = [
                row_data["bill_number"], row_data["customer_name"], row_data["customer_type"],
                row_data["invoice_date"], row_data["status"].replace("_", " ").title(),
                f"₹ {float(row_data['grand_total']):,.2f}", f"₹ {float(row_data['amount_paid']):,.2f}",
                f"₹ {float(row_data['balance_due']):,.2f}",
            ]
            for column, text in enumerate(display):
                item = QTableWidgetItem(str(text))
                item.setData(Qt.ItemDataRole.UserRole, row_data["bill_id"])
                if column >= 5:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column == 4:
                    color = {"Draft": "#8B7433", "Issued": "#6F8B31", "Part Paid": "#8B7433", "Paid": "#477D51", "Cancelled": "#9B5E54"}.get(text, "#74786E")
                    item.setForeground(Qt.GlobalColor.darkGreen if text == "Paid" else item.foreground())
                    item.setToolTip(f"Current bill status: {text}")
                    item.setText(f"  {text}  ")
                self.table.setItem(row, column, item)
        self.table_empty.setVisible(not self._rows)
        self.table.setVisible(bool(self._rows))
        self._selection_changed()

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        self.selected_bill_id = None
        selected = next((item for item in self.table.selectedItems()), None)
        if selected:
            self.selected_bill_id = selected.data(Qt.ItemDataRole.UserRole)
        bill = self.service.get_bill(self.session.business_id, self.selected_bill_id) if self.selected_bill_id else None
        status = bill["status"] if bill else ""
        can = lambda action: has_permission(self.session.role, f"billing.{action}")
        self.view_button.setEnabled(bool(bill))
        self.edit_button.setEnabled(status == "draft" and can("edit_draft"))
        self.issue_button.setEnabled(status == "draft" and can("issue"))
        self.payment_button.setEnabled(status in {"issued", "part_paid"} and can("payment"))
        self.pdf_button.setEnabled(bool(bill and status != "cancelled") and can("pdf"))
        self.cancel_button.setEnabled(status == "issued" and can("cancel"))
        self.delete_button.setEnabled(status == "draft" and can("delete_draft"))

    def _selected_bill(self) -> dict | None:
        if not self.selected_bill_id:
            QMessageBox.information(self, "Select a bill", "Select a row in the bill register first.")
            return None
        return self.service.get_bill(self.session.business_id, self.selected_bill_id)

    def _view_selected(self) -> None:
        bill = self._selected_bill()
        if bill:
            self.navigate(f"bill_view:{bill['bill_id']}")

    def _edit_selected(self) -> None:
        bill = self._selected_bill()
        if bill and bill["status"] == "draft":
            self.navigate(f"bill_edit:{bill['bill_id']}")

    def _open_selected(self, row: int, column: int) -> None:
        self._selection_changed()
        bill = self._selected_bill()
        if bill:
            self.navigate(f"bill_view:{bill['bill_id']}")

    def _issue_selected(self) -> None:
        bill = self._selected_bill()
        if not bill:
            return
        answer = QMessageBox.question(self, "Issue bill", f"Issue {bill['bill_number']} now? The bill can no longer be edited as a draft.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.issue_bill(self.session.business_id, self.session.user_id, bill["bill_id"])
            self.refresh()
            QMessageBox.information(self, "Bill issued", f"{bill['bill_number']} has been issued and preserved in the audit trail.")
        except BillError as exc:
            QMessageBox.warning(self, "Cannot issue bill", str(exc))

    def _delete_selected(self) -> None:
        bill = self._selected_bill()
        if not bill:
            return
        answer = QMessageBox.question(self, "Delete draft", f"Permanently delete draft {bill['bill_number']}? Only unissued drafts may be deleted.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_draft(self.session.business_id, self.session.user_id, bill["bill_id"])
            self.refresh()
        except BillError as exc:
            QMessageBox.warning(self, "Cannot delete bill", str(exc))

    def _cancel_selected(self) -> None:
        bill = self._selected_bill()
        if not bill:
            return
        reason, accepted = QInputDialog.getText(self, "Cancel issued bill", "Reason for cancellation (required):")
        if not accepted:
            return
        try:
            self.service.cancel_bill(self.session.business_id, self.session.user_id, bill["bill_id"], reason)
            self.refresh()
        except BillError as exc:
            QMessageBox.warning(self, "Cannot cancel bill", str(exc))

    def _record_payment(self) -> None:
        bill = self._selected_bill()
        if not bill:
            return
        due = float(bill["balance_due"])
        amount, accepted = QInputDialog.getDouble(self, "Record payment", f"Outstanding balance: ₹{due:,.2f}\nPayment amount (₹):", due, 0.01, due, 2)
        if not accepted:
            return
        method, accepted = QInputDialog.getItem(self, "Payment method", "Select payment method:",
                                                ["UPI", "Cash", "Bank transfer", "Card", "Cheque", "Other"], 0, False)
        if not accepted:
            return
        reference, accepted = QInputDialog.getText(self, "Payment reference", "UTR / transaction reference (optional):")
        if not accepted:
            reference = ""
        try:
            self.service.record_payment(self.session.business_id, self.session.user_id, bill["bill_id"], amount, method, reference)
            self.refresh()
        except BillError as exc:
            QMessageBox.warning(self, "Payment not recorded", str(exc))

    def _generate_pdf(self) -> None:
        bill = self._selected_bill()
        if not bill:
            return
        try:
            profile = self.session.business_id
            safe_number = "".join(c if c.isalnum() or c in "-_." else "_" for c in bill["bill_number"])
            path = Path(ensure_data_dirs()["exports"]) / f"{safe_number}.pdf"
            created = generate_invoice_pdf(self.database, profile, bill["bill_id"], path)
            QMessageBox.information(self, "PDF generated", f"PDF saved to:\n{created}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(created)))
        except (PDFGenerationError, BillError, ValueError) as exc:
            QMessageBox.warning(self, "PDF generation failed", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "PDF generation failed", str(exc))

    def export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export bill register", "KoshFlow-bills.csv", "CSV files (*.csv)")
        if not path:
            return
        fields = ["bill_number", "customer_name", "customer_type", "invoice_date", "due_date", "status", "grand_total", "amount_paid", "balance_due"]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows({field: row.get(field, "") for field in fields} for row in self._rows)
            QMessageBox.information(self, "Export complete", f"Exported {len(self._rows)} bill records to:\n{path}")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def refresh_after_return(self) -> None:
        self.refresh()
