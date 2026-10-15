"""Customer, supplier-detail and keyboard-first counter billing workspaces.

Purpose: Complete contact directory workflows, supplier account views and fast stock-linked checkout.
Project: KoshFlow | Version: 0.5.4
Canonical path: koshflow/ui/pages/contact_pages.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Route contacts to CustomerDirectoryPage, customer_view:<id> and supplier_view:<id> to detail pages,
             and quick_billing[:customer_id] to QuickBillingPage.
Changelog: v0.5.4 — Rebuilt Quick Billing around search-first product selection, a visible customer form and a sale-only cart.
"""
from __future__ import annotations

import csv
from html import escape
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QSize, Qt, QDate, QStringListModel
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QHeaderView,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QSizePolicy,
    QCompleter,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from koshflow.core.database import Database
from koshflow.core.permissions import has_permission
from koshflow.core.session import Session
from koshflow.services.bill_service import BillError, BillService
from koshflow.services.customer_service import CustomerError, CustomerService
from koshflow.services.inventory_service import InventoryError, InventoryService
from koshflow.ui.components import CardFrame, HoverButton, make_line_edit
from koshflow.ui.icons import svg_icon
from koshflow.ui.pages.billing_hub_page import ActionCard

ACCENT = "#829B3E"
MONEY = Decimal("0.01")


def money(value: Any) -> str:
    try:
        return f"₹{Decimal(str(value or '0')):,.2f}"
    except Exception:
        return "₹0.00"


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return str(value if value is not None else "")


def _make_table(columns: list[str], min_height: int = 320) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setMinimumHeight(min_height)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSortingEnabled(True)
    return table


def _put_row(table: QTableWidget, values: list[Any], identifier: str, numeric: set[int] | None = None) -> None:
    index = table.rowCount()
    table.insertRow(index)
    numeric = numeric or set()
    for col, value in enumerate(values):
        cell = QTableWidgetItem(str(value if value is not None else ""))
        cell.setData(Qt.ItemDataRole.UserRole, identifier)
        if col in numeric:
            cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(index, col, cell)


def _selected_id(table: QTableWidget) -> str | None:
    selected = table.selectedItems()
    return str(selected[0].data(Qt.ItemDataRole.UserRole)) if selected and selected[0].data(Qt.ItemDataRole.UserRole) else None


def _header(root: QVBoxLayout, eyebrow: str, title: str, subtitle: str, action=None, action_text: str = "") -> None:
    row = QHBoxLayout()
    copy = QVBoxLayout()
    label = QLabel(eyebrow.upper()); label.setObjectName("eyebrow")
    heading = QLabel(title); heading.setObjectName("pageTitle")
    description = QLabel(subtitle); description.setObjectName("muted"); description.setWordWrap(True)
    copy.addWidget(label); copy.addWidget(heading); copy.addWidget(description)
    row.addLayout(copy, 1)
    if action and action_text:
        button = HoverButton(action_text); button.setObjectName("primaryButton"); button.setIcon(svg_icon("plus", "#171916", 16)); button.clicked.connect(action)
        row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
    root.addLayout(row)


def _metric(label: str, value: str, icon: str, hint: str = "") -> QFrame:
    card = CardFrame("metricCard")
    layout = QVBoxLayout(card); layout.setContentsMargins(15, 12, 15, 13); layout.setSpacing(7)
    top = QHBoxLayout(); title = QLabel(label); title.setObjectName("muted")
    glyph = QLabel(); glyph.setPixmap(svg_icon(icon, ACCENT, 18).pixmap(18, 18))
    top.addWidget(title, 1); top.addWidget(glyph); layout.addLayout(top)
    number = QLabel(value); number.setStyleSheet("font-size:21px;font-weight:760;"); layout.addWidget(number)
    if hint:
        note = QLabel(hint); note.setObjectName("muted"); note.setWordWrap(True); layout.addWidget(note)
    return card


def _export_csv(parent: QWidget, filename: str, headers: list[str], rows: list[list[Any]]) -> None:
    path, _ = QFileDialog.getSaveFileName(parent, "Export CSV", filename, "CSV files (*.csv)")
    if not path:
        return
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file); writer.writerow(headers); writer.writerows(rows)
        QMessageBox.information(parent, "Export complete", f"CSV exported successfully:\n{path}")
    except OSError as exc:
        QMessageBox.critical(parent, "Export failed", str(exc))


class CustomerDialog(QDialog):
    def __init__(self, service: CustomerService, business_id: str, customer: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.service, self.business_id, self.customer = service, business_id, customer
        self.setWindowTitle("Edit customer" if customer else "Add customer")
        self.setMinimumSize(590, 620)
        root = QVBoxLayout(self); root.setContentsMargins(22, 20, 22, 20); root.setSpacing(12)
        form = QFormLayout(); form.setSpacing(10)
        self.code = make_line_edit("Auto-generated customer code"); self.code.setReadOnly(True)
        self.code.setText(_text(customer, "customer_code") if customer else service.next_customer_code(business_id))
        self.name = make_line_edit("Customer / business name")
        self.type = QComboBox(); self.type.addItem("Individual", "individual"); self.type.addItem("Business", "business")
        self.contact = make_line_edit("Contact person")
        self.phone = make_line_edit("Primary phone / WhatsApp")
        self.alt_phone = make_line_edit("Alternate phone")
        self.email = make_line_edit("Email address")
        self.gstin = make_line_edit("GSTIN (optional unless applicable)")
        self.pan = make_line_edit("PAN (optional)")
        self.address = make_line_edit("Street / billing address")
        self.city = make_line_edit("City")
        self.state = make_line_edit("State")
        self.pin = make_line_edit("PIN code")
        self.credit_limit = QDoubleSpinBox(); self.credit_limit.setRange(0, 1_000_000_000); self.credit_limit.setDecimals(2); self.credit_limit.setMinimumHeight(38)
        self.terms = QSpinBox(); self.terms.setRange(0, 365); self.terms.setSuffix(" days"); self.terms.setMinimumHeight(38)
        self.notes = QTextEdit(); self.notes.setMaximumHeight(65); self.notes.setPlaceholderText("Internal notes / delivery preferences")
        for label, widget in [("Customer code", self.code), ("Name *", self.name), ("Type", self.type),
                              ("Contact person", self.contact), ("Phone", self.phone), ("Alternate phone", self.alt_phone),
                              ("Email", self.email), ("GSTIN", self.gstin), ("PAN", self.pan), ("Address", self.address),
                              ("City", self.city), ("State", self.state), ("PIN code", self.pin),
                              ("Credit limit (₹)", self.credit_limit), ("Payment terms", self.terms), ("Notes", self.notes)]:
            form.addRow(label, widget)
        root.addLayout(form, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate); buttons.rejected.connect(self.reject); root.addWidget(buttons)
        if customer:
            for widget, key in [(self.name,"name"),(self.contact,"contact_person"),(self.phone,"phone"),(self.alt_phone,"alternate_phone"),
                                (self.email,"email"),(self.gstin,"gstin"),(self.pan,"pan"),(self.address,"address"),
                                (self.city,"city"),(self.state,"state"),(self.pin,"pincode")]: widget.setText(_text(customer,key))
            idx = self.type.findData(customer.get("customer_type", "individual")); self.type.setCurrentIndex(max(0,idx))
            self.credit_limit.setValue(float(customer.get("credit_limit", 0))); self.terms.setValue(int(customer.get("payment_terms_days",0)))
            self.notes.setPlainText(_text(customer,"notes"))

    def _validate(self):
        if not self.name.text().strip():
            return QMessageBox.warning(self,"Name required","Enter a customer name.")
        self.accept()

    def values(self) -> dict[str, Any]:
        return {"customer_code": _text(self.customer or {}, "customer_code"), "name": self.name.text(),
                "customer_type": str(self.type.currentData()), "contact_person": self.contact.text(), "phone": self.phone.text(),
                "alternate_phone": self.alt_phone.text(), "email": self.email.text(), "gstin": self.gstin.text(),
                "pan": self.pan.text(), "address": self.address.text(), "city": self.city.text(), "state": self.state.text(),
                "pincode": self.pin.text(), "credit_limit": self.credit_limit.value(), "payment_terms_days": self.terms.value(),
                "notes": self.notes.toPlainText()}


class CustomerDirectoryPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database, self.session, self.navigate = database, session, navigate
        self.service = CustomerService(database); self.rows: list[dict[str, Any]] = []
        root = QVBoxLayout(self); root.setContentsMargins(28,22,28,20); root.setSpacing(13)
        _header(root,"Contacts / customer directory","Customers","A proper customer book with contact details, GST profile, credit terms, sales history and outstanding balances.",self._add,"Add customer")
        self.metrics = QHBoxLayout(); self.metrics.setSpacing(12); root.addLayout(self.metrics)
        toolbar = QFrame(); toolbar.setObjectName("sectionToolbar"); row = QHBoxLayout(toolbar); row.setContentsMargins(10,7,10,7)
        self.search = make_line_edit("Search customer, code, phone, email or GSTIN…"); self.search.textChanged.connect(self.refresh)
        export = HoverButton("Export CSV"); export.clicked.connect(self._export)
        refresh = HoverButton("Refresh"); refresh.clicked.connect(self.refresh)
        row.addWidget(self.search,1); row.addWidget(export); row.addWidget(refresh); root.addWidget(toolbar)
        frame=QFrame(); frame.setObjectName("contentCard"); frame_layout=QVBoxLayout(frame); frame_layout.setContentsMargins(10,10,10,10)
        self.table=_make_table(["Code","Customer","Type","Phone","GSTIN","Invoices","Sales total","Collected","Outstanding"],350)
        self.table.itemSelectionChanged.connect(self._selection_changed); self.table.cellDoubleClicked.connect(lambda *_:self._view())
        frame_layout.addWidget(self.table); self.empty=QLabel("No customers yet. Add customers here or create one from Quick Billing."); self.empty.setObjectName("muted"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); frame_layout.addWidget(self.empty); root.addWidget(frame,1)
        actions=QHBoxLayout(); self.view_btn=HoverButton("View account"); self.view_btn.clicked.connect(self._view)
        self.edit_btn=HoverButton("Edit customer"); self.edit_btn.clicked.connect(self._edit)
        self.archive_btn=HoverButton("Archive customer"); self.archive_btn.clicked.connect(self._archive)
        quick=HoverButton("Quick bill"); quick.setObjectName("primaryButton"); quick.clicked.connect(self._quick_bill)
        for button in (self.view_btn,self.edit_btn,self.archive_btn,quick): actions.addWidget(button)
        actions.addStretch(1); root.addLayout(actions); self.refresh()

    def refresh(self,*args):
        self.rows=self.service.list_customers(self.session.business_id,self.search.text())
        while self.metrics.count():
            item=self.metrics.takeAt(0); widget=item.widget()
            if widget: widget.deleteLater()
        count=len(self.rows); sales=sum((Decimal(r["sales_total"]) for r in self.rows),Decimal("0")); outstanding=sum((Decimal(r["outstanding_balance"]) for r in self.rows),Decimal("0"))
        for label,value,icon,hint in [("Customers",str(count),"users","Active contact records"),("Sales linked",money(sales),"receipt","From linked customer invoices"),("Outstanding",money(outstanding),"wallet","Issued and partially paid invoices")]: self.metrics.addWidget(_metric(label,value,icon,hint),1)
        self.table.setSortingEnabled(False); self.table.setRowCount(0)
        for r in self.rows:_put_row(self.table,[r["customer_code"],r["name"],"Business" if r["customer_type"]=="business" else "Individual",r["phone"],r["gstin"],r["invoice_count"],money(r["sales_total"]),money(r["collected_total"]),money(r["outstanding_balance"])],str(r["customer_id"]),{5,6,7,8})
        self.table.setSortingEnabled(True); self.empty.setVisible(not self.rows); self.table.setVisible(bool(self.rows)); self._selection_changed()

    def _selected(self):
        key=_selected_id(self.table); return next((r for r in self.rows if r["customer_id"]==key),None)

    def _selection_changed(self):
        row=self._selected(); manage=has_permission(self.session.role,"contacts.manage")
        self.view_btn.setEnabled(bool(row)); self.edit_btn.setEnabled(bool(row and manage)); self.archive_btn.setEnabled(bool(row and manage))

    def _add(self):
        if not has_permission(self.session.role,"contacts.manage"):
            return QMessageBox.warning(self,"Permission required","Your role cannot manage customer records. You can still add a customer during an authorized sale.")
        dialog=CustomerDialog(self.service,self.session.business_id,parent=self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.create_customer(self.session.business_id,self.session.user_id,dialog.values()); self.refresh()
        except CustomerError as exc:QMessageBox.warning(self,"Customer not saved",str(exc))

    def _edit(self):
        row=self._selected()
        if not row:return
        dialog=CustomerDialog(self.service,self.session.business_id,row,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.update_customer(self.session.business_id,self.session.user_id,row["customer_id"],dialog.values()); self.refresh()
        except CustomerError as exc:QMessageBox.warning(self,"Customer not updated",str(exc))

    def _archive(self):
        row=self._selected()
        if not row:return
        if QMessageBox.question(self,"Archive customer",f"Archive {row['name']}? Historical documents remain intact.")!=QMessageBox.StandardButton.Yes:return
        try:self.service.archive_customer(self.session.business_id,self.session.user_id,row["customer_id"]); self.refresh()
        except CustomerError as exc:QMessageBox.warning(self,"Could not archive",str(exc))

    def _view(self):
        row=self._selected()
        if row:self.navigate(f"customer_view:{row['customer_id']}")

    def _quick_bill(self):
        row=self._selected()
        self.navigate(f"quick_billing:{row['customer_id']}" if row else "quick_billing")

    def _export(self):_export_csv(self,"koshflow-customers.csv",["Customer code","Name","Type","Phone","Email","GSTIN","City","State","Invoices","Sales total","Collected","Outstanding","Active"],[[r["customer_code"],r["name"],r["customer_type"],r["phone"],r["email"],r["gstin"],r["city"],r["state"],r["invoice_count"],r["sales_total"],r["collected_total"],r["outstanding_balance"],"Yes" if r["is_active"] else "No"] for r in self.rows])


class CustomerDetailPage(QWidget):
    def __init__(self, database: Database, session: Session, customer_id: str, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.customer_id = customer_id
        self.navigate = navigate
        self.service = CustomerService(database)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(13)
        customer = self.service.get_customer(session.business_id, customer_id)
        if not customer:
            _header(root, "Contacts / customer", "Customer not found",
                    "The customer may have been archived or belong to another business.")
            back = HoverButton("Back to customers")
            back.clicked.connect(lambda: navigate("contacts"))
            root.addWidget(back)
            root.addStretch(1)
            return

        self.customer = customer
        _header(
            root,
            "Contacts / customer profile",
            customer["name"],
            f"{customer['customer_code']} · {customer.get('phone') or 'No phone'} · {customer.get('email') or 'No email'}",
        )
        metrics = QGridLayout()
        metrics.setSpacing(12)
        metric_specs = [
            ("Total sales", money(customer["sales_total"]), "receipt"),
            ("Collected", money(customer["collected_total"]), "wallet"),
            ("Outstanding", money(customer["outstanding_balance"]), "clock"),
            ("Invoices", str(customer["invoice_count"]), "files"),
        ]
        for index, (label, value, icon) in enumerate(metric_specs):
            metrics.addWidget(_metric(label, value, icon), 0, index)
        root.addLayout(metrics)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(13)

        details = QFrame()
        details.setObjectName("contentCard")
        details_grid = QGridLayout(details)
        details_grid.setContentsMargins(18, 15, 18, 15)
        details_grid.setHorizontalSpacing(20)
        details_grid.setVerticalSpacing(10)
        fields = [
            ("Customer code", customer["customer_code"]),
            ("Type", customer["customer_type"].title()),
            ("Contact person", customer.get("contact_person", "")),
            ("Phone", customer.get("phone", "")),
            ("Alternate phone", customer.get("alternate_phone", "")),
            ("Email", customer.get("email", "")),
            ("GSTIN", customer.get("gstin", "")),
            ("PAN", customer.get("pan", "")),
            ("Address", customer.get("address", "")),
            ("City / State", f"{customer.get('city', '')} {customer.get('state', '')}".strip()),
            ("PIN", customer.get("pincode", "")),
            ("Terms", f"{customer.get('payment_terms_days', 0)} days"),
            ("Credit limit", money(customer.get("credit_limit", "0"))),
            ("Notes", customer.get("notes", "")),
        ]
        for index, (label, value) in enumerate(fields):
            item = QLabel(f"<b>{escape(str(label))}</b><br>{escape(str(value or '—'))}")
            item.setTextFormat(Qt.TextFormat.RichText)
            item.setWordWrap(True)
            details_grid.addWidget(item, index // 3, index % 3)
        content_layout.addWidget(details)

        history_card = QFrame()
        history_card.setObjectName("contentCard")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(10, 10, 10, 10)
        history_title = QLabel("Sales and invoice history")
        history_title.setObjectName("sectionTitle")
        history_layout.addWidget(history_title)
        self.table = _make_table(["Invoice", "Date", "Customer", "Status", "Total", "Paid", "Balance"], 250)
        self.activity = self.service.customer_activity(session.business_id, customer_id)
        for bill in self.activity["bills"]:
            balance = max(Decimal("0"), Decimal(bill["grand_total"]) - Decimal(bill["amount_paid"]))
            _put_row(
                self.table,
                [bill["bill_number"], bill["invoice_date"], bill["customer_name"],
                 bill["status"].replace("_", " ").title(), money(bill["grand_total"]),
                 money(bill["amount_paid"]), money(balance)],
                bill["bill_id"],
                {4, 5, 6},
            )
        self.table.cellDoubleClicked.connect(lambda *_: self._open_bill())
        history_layout.addWidget(self.table)
        content_layout.addWidget(history_card)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        quick = HoverButton("Quick bill this customer")
        quick.setObjectName("primaryButton")
        quick.clicked.connect(lambda: navigate(f"quick_billing:{customer_id}"))
        edit = HoverButton("Edit profile")
        edit.setEnabled(has_permission(session.role, "contacts.manage"))
        edit.clicked.connect(self._edit_profile)
        manage_bills = HoverButton("Manage bills")
        manage_bills.clicked.connect(lambda: navigate("billing_manage"))
        back = HoverButton("Customers")
        back.clicked.connect(lambda: navigate("contacts"))
        for button in (quick, edit, manage_bills, back):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

    def _edit_profile(self) -> None:
        if not has_permission(self.session.role, "contacts.manage"):
            return QMessageBox.warning(self, "Permission required", "Your role cannot edit customer records.")
        current = self.service.get_customer(self.session.business_id, self.customer_id)
        if not current:
            return QMessageBox.warning(self, "Customer unavailable", "This customer no longer exists in the active business.")
        dialog = CustomerDialog(self.service, self.session.business_id, current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.update_customer(
                self.session.business_id, self.session.user_id, self.customer_id, dialog.values()
            )
            QMessageBox.information(self, "Customer updated", "The customer profile has been saved.")
            self.navigate("contacts")
        except CustomerError as exc:
            QMessageBox.warning(self, "Customer not updated", str(exc))

    def _open_bill(self) -> None:
        selected = _selected_id(self.table)
        if selected:
            self.navigate(f"bill_view:{selected}")


class SupplierDetailPage(QWidget):
    def __init__(self, database: Database, session: Session, supplier_id: str, navigate, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.supplier_id = supplier_id
        self.navigate = navigate
        self.service = InventoryService(database)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(13)
        supplier = self.service.get_supplier(session.business_id, supplier_id)
        if not supplier:
            _header(root, "Purchasing / supplier", "Supplier not found",
                    "The supplier may have been archived or belong to another business.")
            back = HoverButton("Back to suppliers")
            back.clicked.connect(lambda: navigate("suppliers"))
            root.addWidget(back)
            root.addStretch(1)
            return

        self.supplier = supplier
        _header(
            root,
            "Purchasing / supplier profile",
            supplier["name"],
            f"{supplier['supplier_code']} · {supplier.get('phone') or 'No phone'} · {supplier.get('email') or 'No email'}",
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(13)

        with database.connection() as conn:
            bills = [dict(row) for row in conn.execute(
                "SELECT purchase_number,purchase_bill_id,purchase_date,status,grand_total,amount_paid,supplier_invoice_number "
                "FROM purchase_bills WHERE business_id=? AND supplier_id=? ORDER BY purchase_date DESC,created_at DESC",
                (session.business_id, supplier_id),
            ).fetchall()]
            orders = [dict(row) for row in conn.execute(
                "SELECT order_number,purchase_order_id,order_date,status,grand_total,expected_date "
                "FROM purchase_orders WHERE business_id=? AND supplier_id=? ORDER BY order_date DESC,created_at DESC",
                (session.business_id, supplier_id),
            ).fetchall()]
            payments = [dict(row) for row in conn.execute(
                "SELECT sp.paid_at,sp.amount,sp.payment_method,sp.reference,pb.purchase_number "
                "FROM supplier_payments sp JOIN purchase_bills pb ON pb.purchase_bill_id=sp.purchase_bill_id "
                "WHERE sp.business_id=? AND sp.supplier_id=? ORDER BY sp.paid_at DESC",
                (session.business_id, supplier_id),
            ).fetchall()]
            returns = [dict(row) for row in conn.execute(
                "SELECT return_number,return_date,status,grand_total,reason FROM supplier_returns "
                "WHERE business_id=? AND supplier_id=? ORDER BY return_date DESC,created_at DESC",
                (session.business_id, supplier_id),
            ).fetchall()]

        posted_bills = [row for row in bills if row["status"] in {"posted", "part_paid", "paid"}]
        total_purchases = sum((Decimal(row["grand_total"]) for row in posted_bills), Decimal("0"))
        total_paid = sum((Decimal(row["amount_paid"]) for row in posted_bills), Decimal("0"))
        metric_row = QGridLayout()
        metric_row.setSpacing(12)
        metrics = [
            ("Posted purchases", money(total_purchases), "receipt"),
            ("Paid to supplier", money(total_paid), "wallet"),
            ("Balance / credit", money(supplier["outstanding_balance"]), "scale"),
            ("Purchase bills", str(len(bills)), "files"),
        ]
        for index, (label, value, icon) in enumerate(metrics):
            metric_row.addWidget(_metric(label, value, icon), 0, index)
        content_layout.addLayout(metric_row)

        profile = QFrame()
        profile.setObjectName("contentCard")
        profile_grid = QGridLayout(profile)
        profile_grid.setContentsMargins(18, 15, 18, 15)
        profile_grid.setHorizontalSpacing(20)
        profile_grid.setVerticalSpacing(10)
        profile_fields = [
            ("Supplier code", supplier.get("supplier_code", "")),
            ("Contact", supplier.get("contact_person", "")),
            ("Phone", supplier.get("phone", "")),
            ("Email", supplier.get("email", "")),
            ("GSTIN", supplier.get("gstin", "")),
            ("PAN", supplier.get("pan", "")),
            ("Address", supplier.get("address", "")),
            ("City / State", f"{supplier.get('city', '')} {supplier.get('state', '')}".strip()),
            ("Payment terms", f"{supplier.get('payment_terms_days', 0)} days"),
            ("Notes", supplier.get("notes", "")),
        ]
        for index, (label, value) in enumerate(profile_fields):
            cell = QLabel(f"<b>{escape(str(label))}</b><br>{escape(str(value or '—'))}")
            cell.setTextFormat(Qt.TextFormat.RichText)
            cell.setWordWrap(True)
            profile_grid.addWidget(cell, index // 3, index % 3)
        content_layout.addWidget(profile)

        self.bills_table = _make_table(
            ["Purchase no.", "Supplier invoice", "Date", "Status", "Total", "Paid", "Balance"], 180
        )
        self.orders_table = _make_table(["Order no.", "Order date", "Expected", "Status", "Total"], 150)
        self.payments_table = _make_table(["Date", "Purchase bill", "Method", "Reference", "Amount"], 150)
        self.returns_table = _make_table(["Return no.", "Date", "Status", "Credit", "Reason"], 120)
        for bill in bills:
            balance = max(Decimal("0"), Decimal(bill["grand_total"]) - Decimal(bill["amount_paid"]))
            _put_row(
                self.bills_table,
                [bill["purchase_number"], bill["supplier_invoice_number"], bill["purchase_date"],
                 bill["status"].title(), money(bill["grand_total"]), money(bill["amount_paid"]), money(balance)],
                bill["purchase_bill_id"], {4, 5, 6},
            )
        for order in orders:
            _put_row(
                self.orders_table,
                [order["order_number"], order["order_date"], order["expected_date"],
                 order["status"].replace("_", " ").title(), money(order["grand_total"])],
                order["purchase_order_id"], {4},
            )
        for payment in payments:
            _put_row(
                self.payments_table,
                [payment["paid_at"], payment["purchase_number"], payment["payment_method"],
                 payment["reference"], money(payment["amount"])],
                payment["purchase_number"], {4},
            )
        for supplier_return in returns:
            _put_row(
                self.returns_table,
                [supplier_return["return_number"], supplier_return["return_date"],
                 supplier_return["status"].title(), money(supplier_return["grand_total"]), supplier_return["reason"]],
                supplier_return["return_number"], {3},
            )
        self.bills_table.cellDoubleClicked.connect(lambda *_: self._open_selected_bill())

        for title, table in [
            ("Purchase bills · double-click to open the register", self.bills_table),
            ("Purchase orders", self.orders_table),
            ("Payments", self.payments_table),
            ("Returns / supplier credits", self.returns_table),
        ]:
            section = QFrame()
            section.setObjectName("contentCard")
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(10, 10, 10, 10)
            section_title = QLabel(title)
            section_title.setObjectName("sectionTitle")
            section_layout.addWidget(section_title)
            section_layout.addWidget(table)
            content_layout.addWidget(section)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        edit = HoverButton("Edit supplier")
        edit.setEnabled(has_permission(session.role, "purchasing.manage_suppliers"))
        edit.clicked.connect(self._edit_supplier)
        bills_button = HoverButton("Purchase bills")
        bills_button.clicked.connect(lambda: navigate("purchase_bills"))
        orders_button = HoverButton("Purchase orders")
        orders_button.clicked.connect(lambda: navigate("purchase_orders"))
        payments_button = HoverButton("Record / view payments")
        payments_button.clicked.connect(lambda: navigate("supplier_payments"))
        back = HoverButton("Suppliers")
        back.clicked.connect(lambda: navigate("suppliers"))
        for button in (edit, bills_button, orders_button, payments_button, back):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

    def _edit_supplier(self) -> None:
        if not has_permission(self.session.role, "purchasing.manage_suppliers"):
            return QMessageBox.warning(self, "Permission required", "Your role cannot edit supplier records.")
        from koshflow.ui.pages.inventory_pages import SupplierDialog

        current = self.service.get_supplier(self.session.business_id, self.supplier_id)
        if not current:
            return QMessageBox.warning(self, "Supplier unavailable", "This supplier no longer exists in the active business.")
        dialog = SupplierDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.update_supplier(self.session.business_id, self.session.user_id, self.supplier_id, dialog.values())
            QMessageBox.information(self, "Supplier updated", "The supplier profile has been saved.")
            self.navigate("suppliers")
        except InventoryError as exc:
            QMessageBox.warning(self, "Supplier not updated", str(exc))

    def _open_selected_bill(self) -> None:
        selected = _selected_id(self.bills_table)
        if selected:
            self.navigate("purchase_bills")


class QuickBillingPage(QWidget):
    """Search-first counter billing with a visible customer form and sale-only cart."""

    def __init__(self, database: Database, session: Session, navigate, selected_customer_id: str | None = None, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.navigate = navigate
        self.inventory = InventoryService(database)
        self.bill_service = BillService(database)
        self.customer_service = CustomerService(database)
        self.products = self.inventory.list_products(session.business_id)
        self.customer_rows = self.customer_service.list_customers(session.business_id)
        self.cart: dict[str, Decimal] = {}
        self.visible_products: list[dict[str, Any]] = []
        self.cart_total = Decimal("0.00")
        self._selected_customer_id = ""
        self._setting_customer_from_completion = False
        self._customer_by_suggestion: dict[str, dict[str, Any]] = {}

        self.setObjectName("quickBillingPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(10)
        _header(
            root,
            "Billing / counter mode",
            "Quick Billing",
            "Search a catalog item, add it to the current sale, and check out with your keyboard.",
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.shortcut_hint = QLabel("F2 Search  ·  Set quantity separately  ·  ↓ Select product  ·  Enter Add item  ·  F4 Checkout  ·  Delete Remove item  ·  Esc Clear search")
        self.shortcut_hint.setObjectName("muted")
        self.shortcut_hint.setWordWrap(True)
        toolbar.addWidget(self.shortcut_hint, 1)
        back = HoverButton("Back to billing")
        back.clicked.connect(lambda: self.navigate("billing"))
        toolbar.addWidget(back, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("quickBillingSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)

        # The search pane does not show the full catalog. Results only appear after a query.
        self.search_card = QFrame()
        self.search_card.setObjectName("quickBillingCard")
        self.search_card.setMinimumWidth(290)
        left = QVBoxLayout(self.search_card)
        left.setContentsMargins(16, 15, 16, 16)
        left.setSpacing(10)

        search_heading = QLabel("Find a product")
        search_heading.setObjectName("sectionTitle")
        left.addWidget(search_heading)
        search_subtitle = QLabel("Scan a barcode or search by product name or SKU.")
        search_subtitle.setObjectName("muted")
        search_subtitle.setWordWrap(True)
        left.addWidget(search_subtitle)

        self.search = make_line_edit("Search products or scan barcode…  (F2)")
        self.search.setObjectName("quickProductSearch")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(0)
        self.search.setMinimumHeight(42)
        self.search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search.textChanged.connect(self._refresh_products)
        self.search.returnPressed.connect(self._add_selected_product)
        self.search.installEventFilter(self)
        left.addWidget(self.search)

        quantity_row = QHBoxLayout()
        quantity_copy = QVBoxLayout()
        quantity_copy.setSpacing(3)
        quantity_title = QLabel("QUANTITY TO ADD")
        quantity_title.setObjectName("quickFieldLabel")
        quantity_help = QLabel("Enter how many units to add to the sale.")
        quantity_help.setObjectName("muted")
        quantity_help.setWordWrap(True)
        quantity_copy.addWidget(quantity_title)
        quantity_copy.addWidget(quantity_help)
        quantity_row.addLayout(quantity_copy, 1)
        self.quantity_to_add = QDoubleSpinBox()
        self.quantity_to_add.setObjectName("quickQuantityToAdd")
        self.quantity_to_add.setRange(0.001, 999999.0)
        self.quantity_to_add.setDecimals(3)
        self.quantity_to_add.setSingleStep(1.0)
        self.quantity_to_add.setValue(1.0)
        self.quantity_to_add.setKeyboardTracking(False)
        self.quantity_to_add.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.quantity_to_add.setMinimumWidth(112)
        self.quantity_to_add.setMinimumHeight(40)
        self.quantity_to_add.setEnabled(False)
        quantity_row.addWidget(self.quantity_to_add, 0, Qt.AlignmentFlag.AlignVCenter)
        left.addLayout(quantity_row)

        self.search_status = QLabel("START TYPING TO SEARCH")
        self.search_status.setObjectName("quickSearchCaption")
        left.addWidget(self.search_status)

        self.search_empty_state = QFrame()
        self.search_empty_state.setObjectName("quickSearchEmptyState")
        empty_layout = QVBoxLayout(self.search_empty_state)
        empty_layout.setContentsMargins(18, 22, 18, 22)
        empty_layout.setSpacing(9)
        empty_layout.addStretch(1)
        search_icon = QLabel()
        search_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        search_icon.setPixmap(svg_icon("search", ACCENT, 34).pixmap(34, 34))
        empty_layout.addWidget(search_icon)
        empty_title = QLabel("Your sale starts here")
        empty_title.setObjectName("quickSearchEmptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_text = QLabel("Matching items appear after you search. Add a result to place it in Current sale.")
        empty_text.setObjectName("muted")
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_text.setWordWrap(True)
        empty_layout.addWidget(empty_text)
        empty_layout.addStretch(1)
        left.addWidget(self.search_empty_state, 1)

        self.search_results = QListWidget()
        self.search_results.setObjectName("quickProductResults")
        self.search_results.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.search_results.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.search_results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_results.setSpacing(5)
        self.search_results.setUniformItemSizes(True)
        self.search_results.setMinimumHeight(170)
        self.search_results.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.search_results.itemActivated.connect(lambda _item: self._add_selected_product())
        self.search_results.currentRowChanged.connect(self._sync_quantity_to_add)
        self.search_results.hide()
        left.addWidget(self.search_results, 1)

        search_actions = QHBoxLayout()
        self.add_button = HoverButton("Add selected item")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setMinimumHeight(42)
        self.add_button.clicked.connect(self._add_selected_product)
        search_actions.addWidget(self.add_button)
        self.available_hint = QLabel("No product selected")
        self.available_hint.setObjectName("muted")
        self.available_hint.setWordWrap(True)
        search_actions.addWidget(self.available_hint, 1)
        left.addLayout(search_actions)

        # The current sale pane owns all selected products and customer inputs.
        self.sale_card = QFrame()
        self.sale_card.setObjectName("quickBillingCard")
        self.sale_card.setMinimumWidth(540)
        right = QVBoxLayout(self.sale_card)
        right.setContentsMargins(16, 15, 16, 16)
        right.setSpacing(9)

        sale_header = QHBoxLayout()
        cart_title = QLabel("Current sale")
        cart_title.setObjectName("sectionTitle")
        sale_header.addWidget(cart_title)
        sale_header.addStretch(1)
        self.cart_count = QLabel("0 items")
        self.cart_count.setObjectName("pill")
        sale_header.addWidget(self.cart_count)
        right.addLayout(sale_header)

        customer_box = QFrame()
        customer_box.setObjectName("quickCustomerPanel")
        customer_layout = QVBoxLayout(customer_box)
        customer_layout.setContentsMargins(12, 10, 12, 12)
        customer_layout.setSpacing(8)

        customer_intro = QLabel(
            "Type a customer name to find an existing contact, or enter a new walk-in customer. "
            "The customer record is saved automatically when the sale completes."
        )
        customer_intro.setObjectName("muted")
        customer_intro.setWordWrap(True)
        customer_layout.addWidget(customer_intro)

        customer_fields = QGridLayout()
        customer_fields.setContentsMargins(0, 0, 0, 0)
        customer_fields.setHorizontalSpacing(10)
        customer_fields.setVerticalSpacing(5)

        def make_customer_field(label_text: str, field: QLineEdit, object_name: str) -> QWidget:
            wrapper = QWidget()
            wrapper.setMinimumWidth(0)
            field_layout = QVBoxLayout(wrapper)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            label = QLabel(label_text.upper())
            label.setObjectName("quickFieldLabel")
            field.setObjectName(object_name)
            field.setMinimumWidth(0)
            field.setMinimumHeight(39)
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            field_layout.addWidget(label)
            field_layout.addWidget(field)
            return wrapper

        self.customer_name = make_line_edit("Customer name")
        self.customer_phone = make_line_edit("Phone / WhatsApp number")
        self.customer_completer = QCompleter(self)
        self.customer_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.customer_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.customer_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.customer_completer.setMaxVisibleItems(8)
        self._customer_suggestion_model = QStringListModel(self.customer_completer)
        self.customer_completer.setModel(self._customer_suggestion_model)
        self.customer_name.setCompleter(self.customer_completer)
        self.customer_completer.activated[str].connect(self._select_customer_suggestion)
        self.customer_name.textEdited.connect(self._customer_name_typed)
        self.customer_phone.textEdited.connect(self._customer_phone_typed)
        customer_fields.addWidget(make_customer_field("Customer name", self.customer_name, "quickCustomerName"), 0, 0)
        customer_fields.addWidget(make_customer_field("Phone number", self.customer_phone, "quickCustomerPhone"), 0, 1)
        customer_fields.setColumnStretch(0, 1)
        customer_fields.setColumnStretch(1, 1)
        customer_layout.addLayout(customer_fields)

        self.details_toggle = HoverButton("+ Add email / GSTIN details")
        self.details_toggle.setObjectName("quietButton")
        customer_layout.addWidget(self.details_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.optional_customer_fields = QWidget()
        optional_layout = QGridLayout(self.optional_customer_fields)
        optional_layout.setContentsMargins(0, 0, 0, 0)
        optional_layout.setHorizontalSpacing(10)
        optional_layout.setVerticalSpacing(5)
        self.customer_email = make_line_edit("Email address (optional)")
        self.customer_gstin = make_line_edit("GSTIN (optional)")
        self.customer_email.textEdited.connect(self._customer_details_typed)
        self.customer_gstin.textEdited.connect(self._customer_details_typed)
        optional_layout.addWidget(make_customer_field("Email", self.customer_email, "quickCustomerEmail"), 0, 0)
        optional_layout.addWidget(make_customer_field("GSTIN", self.customer_gstin, "quickCustomerGSTIN"), 0, 1)
        optional_layout.setColumnStretch(0, 1)
        optional_layout.setColumnStretch(1, 1)
        optional_layout.setColumnStretch(0, 1)
        optional_layout.setColumnStretch(1, 1)
        self.optional_customer_fields.hide()
        customer_layout.addWidget(self.optional_customer_fields)
        self.details_toggle.clicked.connect(self._toggle_optional_customer_fields)
        self._refresh_customer_completions()
        right.addWidget(customer_box)

        self.cart_table = _make_table(["Item", "Qty", "Rate", "Tax", "Total"], 150)
        self.cart_table.setObjectName("quickSaleTable")
        self.cart_table.setSortingEnabled(False)
        self.cart_table.setMinimumHeight(150)
        self.cart_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.cart_table.verticalHeader().setDefaultSectionSize(39)
        cart_header = self.cart_table.horizontalHeader()
        cart_header.setMinimumSectionSize(56)
        cart_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cart_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        cart_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        cart_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        cart_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.cart_table.setColumnWidth(1, 76)
        self.cart_table.setColumnWidth(2, 90)
        self.cart_table.setColumnWidth(3, 72)
        self.cart_table.setColumnWidth(4, 112)
        right.addWidget(self.cart_table, 1)

        cart_actions = QHBoxLayout()
        cart_actions.setSpacing(7)
        remove = HoverButton("Remove selected")
        remove.clicked.connect(self._remove_selected)
        clear = HoverButton("Clear sale")
        clear.clicked.connect(self._clear_cart)
        cart_actions.addWidget(remove)
        cart_actions.addWidget(clear)
        cart_actions.addStretch(1)
        right.addLayout(cart_actions)

        summary = QFrame()
        summary.setObjectName("quickSaleSummary")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(13, 10, 13, 10)
        summary_layout.setHorizontalSpacing(12)
        summary_layout.setVerticalSpacing(4)
        self.subtotal_label = QLabel("₹0.00")
        self.tax_label = QLabel("₹0.00")
        self.total_label = QLabel("₹0.00")
        self.total_label.setObjectName("quickSaleGrandTotal")
        summary_layout.addWidget(QLabel("Subtotal"), 0, 0)
        summary_layout.addWidget(self.subtotal_label, 0, 1, Qt.AlignmentFlag.AlignRight)
        summary_layout.addWidget(QLabel("Tax"), 1, 0)
        summary_layout.addWidget(self.tax_label, 1, 1, Qt.AlignmentFlag.AlignRight)
        summary_layout.addWidget(QLabel("Total due"), 2, 0)
        summary_layout.addWidget(self.total_label, 2, 1, Qt.AlignmentFlag.AlignRight)
        right.addWidget(summary)

        payment_row = QHBoxLayout()
        self.mark_paid = QCheckBox("Record payment now")
        self.mark_paid.setChecked(True)
        self.pay_method = QComboBox()
        self.pay_method.setObjectName("quickPaymentMethod")
        self.pay_method.addItems(["Cash", "UPI", "Card", "Bank transfer", "Cheque", "Other"])
        self.pay_method.setMinimumWidth(135)
        self.pay_method.setMinimumHeight(38)
        self.mark_paid.toggled.connect(self.pay_method.setEnabled)
        payment_row.addWidget(self.mark_paid)
        payment_row.addStretch(1)
        payment_row.addWidget(self.pay_method)
        right.addLayout(payment_row)

        self.checkout = HoverButton("Complete sale  ·  F4")
        self.checkout.setObjectName("primaryButton")
        self.checkout.setMinimumHeight(45)
        self.checkout.setEnabled(False)
        self.checkout.clicked.connect(self._checkout)
        right.addWidget(self.checkout)

        self.splitter.addWidget(self.search_card)
        self.splitter.addWidget(self.sale_card)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([400, 850])
        root.addWidget(self.splitter, 1)

        self._register_shortcuts()
        self._refresh_products()
        self._render_cart()
        if selected_customer_id:
            selected = next((row for row in self.customer_rows if str(row["customer_id"]) == str(selected_customer_id)), None)
            if selected:
                self._populate_customer_from_record(selected)

    def _register_shortcuts(self) -> None:
        shortcuts = [
            ("F2", self._focus_search),
            ("F4", self._checkout),
            ("Delete", self._remove_selected_if_cart_focused),
            ("Esc", self._clear_search),
        ]
        self._shortcuts = []
        for sequence, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down and self.search_results.count() > 0:
                self.search_results.setFocus()
                self.search_results.setCurrentRow(0)
                return True
        return super().eventFilter(watched, event)

    def _clear_search(self) -> None:
        self.search.clear()
        self.search.setFocus()

    def _remove_selected_if_cart_focused(self) -> None:
        focused = self.focusWidget()
        # Preserve Delete's normal text-editing behavior in search, customer fields and quantity controls.
        if focused is self.cart_table:
            self._remove_selected()

    @staticmethod
    def _format_quantity(value: Any) -> str:
        quantity = Decimal(str(value or "0"))
        return f"{quantity:,.3f}".rstrip("0").rstrip(".")

    def _refresh_products(self, *_args) -> None:
        query = self.search.text().strip().casefold()
        self.visible_products = []
        self.search_results.clear()

        if not query:
            self.search_results.hide()
            self.search_empty_state.show()
            self.search_status.setText("START TYPING TO SEARCH")
            self.available_hint.setText("No product selected")
            self.add_button.setEnabled(False)
            self.quantity_to_add.setEnabled(False)
            return

        def rank(product: dict[str, Any]) -> tuple[int, str]:
            sku = str(product.get("sku") or "").casefold()
            name = str(product.get("name") or "").casefold()
            barcode = str(product.get("barcode") or "").casefold()
            if query == sku or query == barcode:
                return 0, name
            if sku.startswith(query) or name.startswith(query) or barcode.startswith(query):
                return 1, name
            return 2, name

        matches = [
            product for product in self.products
            if query in str(product.get("name") or "").casefold()
            or query in str(product.get("sku") or "").casefold()
            or query in str(product.get("barcode") or "").casefold()
        ]
        matches.sort(key=rank)
        self.visible_products = matches[:40]

        for product in self.visible_products:
            stock = Decimal(str(product.get("quantity_on_hand") or "0"))
            stock_label = "OUT OF STOCK" if stock <= 0 else f"{self._format_quantity(stock)} {product.get('unit') or 'units'} available"
            item = QListWidgetItem(
                f"{product['name']}  ·  {product['sku']}\n{stock_label}    ·    {money(product['selling_price'])}    ·    GST {product.get('tax_rate', '0')}%"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(product["product_id"]))
            item.setSizeHint(QSize(100, 58))
            if stock <= 0:
                item.setToolTip("This product is out of stock and cannot be added to a sale.")
            self.search_results.addItem(item)

        self.search_empty_state.hide()
        self.search_results.show()
        if self.search_results.count():
            self.search_results.setCurrentRow(0)
            self.search_status.setText(f"{len(matches)} MATCHING PRODUCT(S)")
            self._sync_quantity_to_add()
        else:
            no_match = QListWidgetItem("No matching products\nTry another product name, SKU or barcode.")
            no_match.setFlags(Qt.ItemFlag.NoItemFlags)
            no_match.setSizeHint(QSize(100, 58))
            self.search_results.addItem(no_match)
            self.search_status.setText("NO MATCHES")
            self.available_hint.setText("Try a broader search")
            self.add_button.setEnabled(False)
            self.quantity_to_add.setEnabled(False)

    def _selected_product(self) -> dict[str, Any] | None:
        item = self.search_results.currentItem()
        identifier = str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
        return next((product for product in self.visible_products if str(product["product_id"]) == identifier), None)

    def _sync_quantity_to_add(self, *_args) -> None:
        product = self._selected_product()
        if not product:
            self.quantity_to_add.setEnabled(False)
            self.add_button.setEnabled(False)
            self.available_hint.setText("No product selected")
            return
        product_id = str(product["product_id"])
        stock = Decimal(str(product.get("quantity_on_hand") or "0"))
        remaining = stock - self.cart.get(product_id, Decimal("0"))
        if remaining <= 0:
            self.quantity_to_add.setEnabled(False)
            self.add_button.setEnabled(False)
            self.available_hint.setText("No remaining stock available for this sale")
            return
        self.quantity_to_add.setEnabled(True)
        self.quantity_to_add.blockSignals(True)
        self.quantity_to_add.setRange(0.001, float(remaining))
        if self.quantity_to_add.value() > float(remaining):
            self.quantity_to_add.setValue(float(remaining))
        elif self.quantity_to_add.value() <= 0:
            self.quantity_to_add.setValue(1 if remaining >= 1 else float(remaining))
        self.quantity_to_add.blockSignals(False)
        self.add_button.setEnabled(True)
        self.available_hint.setText(
            f"{self._format_quantity(remaining)} {product.get('unit') or 'units'} remaining · "
            f"{money(product['selling_price'])} each"
        )

    def _add_selected_product(self) -> None:
        product = self._selected_product()
        if product is None:
            if not self.search.text().strip():
                self.search.setFocus()
                return
            return QMessageBox.information(self, "Choose a product", "Search the catalog and select an in-stock result.")

        stock = Decimal(str(product.get("quantity_on_hand") or "0"))
        product_id = str(product["product_id"])
        current = self.cart.get(product_id, Decimal("0"))
        quantity = Decimal(str(self.quantity_to_add.value())).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if quantity <= 0:
            return QMessageBox.warning(self, "Invalid quantity", "Enter a quantity greater than zero before adding the product.")
        if stock < current + quantity:
            return QMessageBox.warning(
                self,
                "Stock limit reached",
                f"{product['name']} has {self._format_quantity(stock)} {product.get('unit') or 'units'} in stock. "
                f"{self._format_quantity(current)} are already in this sale; you can add at most {self._format_quantity(stock - current)} more.",
            )

        self.cart[product_id] = current + quantity
        self._render_cart()
        self.quantity_to_add.setValue(1.0)
        self.search.clear()
        self.search.setFocus()

    def _toggle_optional_customer_fields(self) -> None:
        show_fields = not self.optional_customer_fields.isVisible()
        self.optional_customer_fields.setVisible(show_fields)
        self.details_toggle.setText("− Hide email / GSTIN details" if show_fields else "+ Add email / GSTIN details")

    def _refresh_customer_completions(self) -> None:
        self._customer_by_suggestion.clear()
        labels = []
        for customer in self.customer_rows:
            name = str(customer.get("name") or "").strip()
            code = str(customer.get("customer_code") or "").strip()
            phone = str(customer.get("phone") or "").strip()
            display = " · ".join(part for part in (name, phone, code) if part)
            if display:
                labels.append(display)
                self._customer_by_suggestion[display] = customer
        self._customer_suggestion_model.setStringList(labels)

    def _populate_customer_from_record(self, customer: dict[str, Any]) -> None:
        self._setting_customer_from_completion = True
        try:
            self._selected_customer_id = str(customer.get("customer_id") or "")
            for field, key in (
                (self.customer_name, "name"),
                (self.customer_phone, "phone"),
                (self.customer_email, "email"),
                (self.customer_gstin, "gstin"),
            ):
                field.setText(str(customer.get(key) or ""))
            if customer.get("email") or customer.get("gstin"):
                self.optional_customer_fields.show()
                self.details_toggle.setText("− Hide email / GSTIN details")
        finally:
            self._setting_customer_from_completion = False

    def _select_customer_suggestion(self, display: str) -> None:
        customer = self._customer_by_suggestion.get(str(display))
        if customer:
            self._populate_customer_from_record(customer)

    def _customer_name_typed(self, value: str) -> None:
        if self._setting_customer_from_completion:
            return
        self._selected_customer_id = ""
        # QCompleter applies case-insensitive contains matching against the saved directory.

    def _customer_phone_typed(self, *_args) -> None:
        if not self._setting_customer_from_completion:
            self._selected_customer_id = ""

    def _customer_details_typed(self, *_args) -> None:
        # Customer details entered in Quick Billing are snapshots for the invoice.
        # Profile maintenance remains in Contacts; identity resolution still uses phone/name.
        if not self._setting_customer_from_completion:
            self._selected_customer_id = ""

    def _render_cart(self, *_args) -> None:
        self.cart_table.setSortingEnabled(False)
        self.cart_table.setRowCount(0)
        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")
        by_id = {str(product["product_id"]): product for product in self.products}

        for product_id, quantity_value in list(self.cart.items()):
            product = by_id.get(str(product_id))
            if not product:
                self.cart.pop(product_id, None)
                continue
            quantity = Decimal(str(quantity_value))
            rate = Decimal(str(product["selling_price"]))
            tax_rate = Decimal(str(product.get("tax_rate") or "0"))
            base = (quantity * rate).quantize(MONEY, rounding=ROUND_HALF_UP)
            tax = (base * tax_rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
            line_total = base + tax
            subtotal += base
            tax_total += tax

            row = self.cart_table.rowCount()
            self.cart_table.insertRow(row)
            values = [product["name"], self._format_quantity(quantity), money(rate), f"{tax_rate:g}%", money(line_total)]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole, str(product_id))
                if column in {2, 3, 4}:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.cart_table.setItem(row, column, cell)

        self.cart_count.setText(f"{len(self.cart)} item{'s' if len(self.cart) != 1 else ''}")
        self.subtotal_label.setText(money(subtotal))
        self.tax_label.setText(money(tax_total))
        self.cart_total = (subtotal + tax_total).quantize(MONEY, rounding=ROUND_HALF_UP)
        self.total_label.setText(money(self.cart_total))
        self.checkout.setEnabled(bool(self.cart))

    def _quantity_changed(self, product_id: str, value: float) -> None:
        quantity = Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if quantity <= 0:
            self.cart.pop(product_id, None)
        else:
            product = next((row for row in self.products if str(row["product_id"]) == str(product_id)), None)
            if product and quantity > Decimal(str(product.get("quantity_on_hand") or "0")):
                QMessageBox.warning(self, "Stock limit reached", "The requested quantity exceeds available stock.")
                self._render_cart()
                return
            self.cart[product_id] = quantity
        self._render_cart()

    def _remove_selected(self) -> None:
        selected = _selected_id(self.cart_table)
        if selected:
            self.cart.pop(selected, None)
            self._render_cart()

    def _clear_cart(self) -> None:
        if not self.cart:
            return
        if QMessageBox.question(self, "Clear current sale", "Remove every item from the current sale?") != QMessageBox.StandardButton.Yes:
            return
        self.cart.clear()
        self._render_cart()
        self.search.setFocus()

    def _checkout(self) -> None:
        if not has_permission(self.session.role, "billing.create") or not has_permission(self.session.role, "billing.issue"):
            return QMessageBox.warning(self, "Permission required", "Your role cannot complete a sale.")
        if not self.cart:
            self.search.setFocus()
            return QMessageBox.information(self, "Sale is empty", "Search for a product and add it to Current sale before checkout.")

        # Refresh stock and price data immediately before confirmation; the billing service
        # repeats its authoritative checks inside the issue transaction.
        self.products = self.inventory.list_products(self.session.business_id)
        catalog = {str(product["product_id"]): product for product in self.products}
        for product_id, quantity in self.cart.items():
            product = catalog.get(str(product_id))
            if not product or quantity > Decimal(str(product.get("quantity_on_hand") or "0")):
                return QMessageBox.warning(self, "Stock changed", "Available stock changed while this sale was being prepared. Review the cart and try again.")
        self._render_cart()

        items = []
        for product_id, quantity in self.cart.items():
            product = catalog[str(product_id)]
            items.append({
                "product_id": product_id,
                "description": product["name"],
                "hsn_sac": product.get("hsn_code") or "",
                "quantity": str(quantity),
                "unit": product.get("unit") or "pcs",
                "unit_price": product["selling_price"],
                "discount_percent": "0",
                "tax_rate": product.get("tax_rate") or "0",
            })

        value = self.cart_total
        if QMessageBox.question(
            self,
            "Confirm sale",
            f"Issue this sale for {money(value)}?\n\nThe customer record will be saved or matched, and stock will be deducted only when the invoice is issued.",
        ) != QMessageBox.StandardButton.Yes:
            return

        entered_name = self.customer_name.text().strip()
        entered_phone = self.customer_phone.text().strip()
        entered_email = self.customer_email.text().strip()
        entered_gstin = self.customer_gstin.text().strip()
        customer_name = entered_name or "Walk-in Customer"
        today = date.today().isoformat()

        # Every completed Quick Billing sale is linked to a persisted customer. Anonymous
        # counter sales reuse one no-phone Walk-in Customer record; named/phone customers
        # are resolved through the customer service to avoid duplicate contacts.
        try:
            if self._selected_customer_id:
                customer_id = self.customer_service.resolve_or_create_for_sale(
                    self.session.business_id, self.session.user_id, {},
                    existing_customer_id=self._selected_customer_id,
                ) or ""
            else:
                customer_id = self.customer_service.resolve_or_create_for_sale(
                    self.session.business_id,
                    self.session.user_id,
                    {
                        "name": customer_name,
                        "phone": entered_phone,
                        "email": entered_email,
                        "gstin": entered_gstin,
                        "customer_type": "business" if entered_gstin else "individual",
                    },
                ) or ""
        except CustomerError as exc:
            return QMessageBox.warning(self, "Customer could not be saved", str(exc))

        customer_record = self.customer_service.get_customer(self.session.business_id, customer_id) if customer_id else None
        if customer_record:
            customer_name = entered_name or str(customer_record.get("name") or "Walk-in Customer")
            customer_phone = entered_phone or str(customer_record.get("phone") or "")
            customer_email = entered_email or str(customer_record.get("email") or "")
            customer_gstin = entered_gstin or str(customer_record.get("gstin") or "")
        else:
            customer_phone, customer_email, customer_gstin = entered_phone, entered_email, entered_gstin

        bill_values = {
            "customer_id": customer_id or None,
            "customer_type": "B2B" if customer_gstin else "B2C",
            "document_type": "tax_invoice",
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "customer_email": customer_email,
            "customer_gstin": customer_gstin,
            "invoice_date": today,
            "due_date": today,
            "invoice_discount": "0",
            "items": items,
            "notes": "Created with KoshFlow Quick Billing.",
            "terms": "Payment due on receipt.",
        }
        bill_id = None
        try:
            bill_id = self.bill_service.create_bill(self.session.business_id, self.session.user_id, bill_values)
            self.bill_service.issue_bill(self.session.business_id, self.session.user_id, bill_id)
        except (BillError, ValueError, InventoryError) as exc:
            if bill_id:
                try:
                    self.bill_service.delete_draft(self.session.business_id, self.session.user_id, bill_id)
                except Exception:
                    pass
            return QMessageBox.warning(self, "Sale not completed", str(exc))

        if self.mark_paid.isChecked():
            try:
                self.bill_service.record_payment(
                    self.session.business_id, self.session.user_id, bill_id, value,
                    self.pay_method.currentText(), "Quick Billing", today,
                )
            except Exception as exc:
                QMessageBox.warning(
                    self, "Invoice issued; payment needs review",
                    f"Invoice issued and stock deducted, but payment could not be recorded.\n\n{exc}",
                )

        saved = self.bill_service.get_bill(self.session.business_id, bill_id)
        self.customer_rows = self.customer_service.list_customers(self.session.business_id)
        self._refresh_customer_completions()
        QMessageBox.information(
            self, "Sale completed",
            f"Invoice {saved['bill_number']} has been issued.\nTotal: {money(saved['grand_total'])}\nCustomer record saved/matched. Stock has been updated.",
        )
        self.cart.clear()
        self.products = self.inventory.list_products(self.session.business_id)
        self._render_cart()
        for field in (self.customer_name, self.customer_phone, self.customer_email, self.customer_gstin):
            field.clear()
        self._selected_customer_id = ""
        self.optional_customer_fields.hide()
        self.details_toggle.setText("+ Add email / GSTIN details")
        self._clear_search()
        self.navigate(f"bill_view:{bill_id}")
