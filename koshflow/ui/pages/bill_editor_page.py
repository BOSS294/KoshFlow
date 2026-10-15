"""Bill creation and draft-editing form.

Purpose: Capture B2B/B2C customer details, line items and tax rates for local bill CRUD.
Canonical path: koshflow/ui/pages/bill_editor_page.py
Project: KoshFlow | Version: 0.5.4
Developer: Mayank Chawdhari AKA BOSS294
Integration: Instantiate with database, authenticated session and save/cancel callbacks.
Changelog: v0.5.2 — Compact catalog-link controls, responsive bill-item columns and theme-aware totals styling.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QDate
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QHeaderView, QSizePolicy,
)

from koshflow.core.database import Database
from koshflow.core.session import Session
from koshflow.services.bill_service import BillError, BillService
from koshflow.services.inventory_service import InventoryService
from koshflow.services.customer_service import CustomerService
from koshflow.services.business_service import BusinessService
from koshflow.ui.components import HoverButton, make_combo
from koshflow.ui.icons import svg_icon
from koshflow.ui.pages.invoice_theme_preview import InvoiceThemePreview
from koshflow.services.theme_design import resolve_theme_design


class BillEditorPage(QWidget):
    def __init__(self, database: Database, session: Session, bill_id: str | None,
                 on_saved, on_cancel, parent=None):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.bill_service = BillService(database)
        self.customer_service = CustomerService(database)
        self.customer_records = self.customer_service.list_customers(session.business_id)
        self.catalog_products = InventoryService(database).list_products(session.business_id)
        self.bill_id = bill_id
        self.on_saved = on_saved
        self.on_cancel = on_cancel
        self._updating_amount_cells = False
        self._flow_animations: list[QPropertyAnimation] = []
        self.flow_buttons: dict[str, HoverButton] = {}
        self._build_ui()
        if self.bill_id:
            self._load_bill(self.bill_id)
        else:
            self.add_item_row()
            self.customer_name.setFocus()
        self._update_theme_preview()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(27, 22, 27, 20)
        outer.setSpacing(15)
        top = QHBoxLayout()
        title_box = QVBoxLayout()
        eyebrow = QLabel("BILLING  /  CREATE")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Create a bill" if not self.bill_id else "Edit draft bill")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Enter customer details and items. Totals are calculated by the billing service before saving.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        title_box.addWidget(eyebrow)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top.addLayout(title_box, 1)
        back = HoverButton("Back to billing")
        back.clicked.connect(self.on_cancel)
        top.addWidget(back, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(top)

        # A lightweight step navigator lets users move through the long form
        # without losing context or manually searching for the next section.
        flow_row = QHBoxLayout()
        flow_row.setSpacing(8)
        flow_title = QLabel("BILL FLOW")
        flow_title.setObjectName("eyebrow")
        flow_row.addWidget(flow_title)
        for step_key, step_label in (("customer", "01  Customer & document"), ("items", "02  Items & totals"), ("review", "03  Notes & review")):
            step_button = HoverButton(step_label)
            step_button.setObjectName("secondaryButton")
            step_button.clicked.connect(lambda checked=False, target=step_key: self._scroll_to_step(target))
            self.flow_buttons[step_key] = step_button
            flow_row.addWidget(step_button)
        flow_row.addStretch(1)
        outer.addLayout(flow_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(1, 1, 6, 1)
        content_layout.setSpacing(14)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)

        customer_card = QFrame()
        self.customer_card = customer_card
        customer_card.setObjectName("contentCard")
        card_layout = QVBoxLayout(customer_card)
        card_layout.setContentsMargins(20, 18, 20, 20)
        card_layout.setSpacing(12)
        section = QLabel("Customer & document")
        section.setObjectName("sectionTitle")
        card_layout.addWidget(section)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.customer_type = make_combo(["B2C", "B2B"], "Select customer type")
        self.document_type = make_combo(["Tax invoice", "Bill of supply", "Pro forma invoice", "Estimate / quotation"], "Document type")
        self.customer_record = QComboBox()
        self.customer_record.addItem("One-time / enter customer manually", "")
        for customer in self.customer_records:
            self.customer_record.addItem(f"{customer['customer_code']} · {customer['name']} · {customer['phone']}", customer["customer_id"])
        self.customer_record.currentIndexChanged.connect(self._customer_record_selected)
        self.customer_name = QLineEdit()
        self.customer_name.setPlaceholderText("Customer or business name *")
        self.customer_phone = QLineEdit()
        self.customer_phone.setPlaceholderText("WhatsApp / phone number")
        self.customer_email = QLineEdit()
        self.customer_email.setPlaceholderText("Email address")
        self.customer_gstin = QLineEdit()
        self.customer_gstin.setPlaceholderText("GSTIN (required for B2B)")
        self.customer_address = QLineEdit()
        self.customer_address.setPlaceholderText("Billing address")
        self.place_of_supply = QLineEdit()
        self.place_of_supply.setPlaceholderText("Place of supply / state")
        self.invoice_date = QDateEdit()
        self.invoice_date.setCalendarPopup(True)
        self.invoice_date.setDisplayFormat("dd MMM yyyy")
        self.invoice_date.setDate(QDate.currentDate())
        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        self.due_date.setDisplayFormat("dd MMM yyyy")
        self.due_date.setDate(QDate.currentDate().addDays(15))
        self.due_date_check = QComboBox()
        self.due_date_check.addItems(["Due date set", "No due date"])
        self.template_combo = QComboBox()
        self._templates = self.bill_service.ensure_starter_templates(self.session.business_id)
        self._templates = self.bill_service.list_templates(self.session.business_id)
        self.template_combo.addItem("Use default theme", "")
        for template in self._templates:
            self.template_combo.addItem(template["template_name"], template["template_id"])
        self.theme_preview = InvoiceThemePreview(compact=True)
        self.theme_preview.setMaximumHeight(285)
        fields = [
            ("Saved customer", self.customer_record), ("Customer type", self.customer_type),
            ("Document type", self.document_type), ("Customer / party name *", self.customer_name), ("Phone", self.customer_phone),
            ("Email", self.customer_email), ("GSTIN", self.customer_gstin),
            ("Address", self.customer_address), ("Place of supply", self.place_of_supply),
            ("Invoice date", self.invoice_date), ("Due date", self.due_date),
            ("Due date option", self.due_date_check), ("PDF theme", self.template_combo),
        ]
        for index, (label_text, widget) in enumerate(fields):
            row, col = divmod(index, 2)
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(5)
            label = QLabel(label_text)
            label.setObjectName("muted")
            label.setStyleSheet("font-size:11px;font-weight:650;")
            field_layout.addWidget(label)
            field_layout.addWidget(widget)
            if label_text == "PDF theme":
                field_layout.addWidget(self.theme_preview)
                theme_hint = QLabel("Preview updates with the selected full-page invoice design.")
                theme_hint.setObjectName("muted")
                theme_hint.setWordWrap(True)
                field_layout.addWidget(theme_hint)
            grid.addWidget(field, row, col)
        self.template_combo.currentIndexChanged.connect(self._update_theme_preview)
        self.customer_type.currentTextChanged.connect(self._customer_type_changed)
        self.due_date_check.currentTextChanged.connect(self._toggle_due_date)
        card_layout.addLayout(grid)
        content_layout.addWidget(customer_card)

        items_card = QFrame()
        self.items_card = items_card
        items_card.setObjectName("contentCard")
        items_layout = QVBoxLayout(items_card)
        items_layout.setContentsMargins(20, 18, 20, 18)
        items_layout.setSpacing(12)
        items_top = QHBoxLayout()
        items_title = QLabel("Bill items")
        items_title.setObjectName("sectionTitle")
        items_hint = QLabel("Quantity, discount and GST are stored per line.")
        items_hint.setObjectName("muted")
        items_top.addWidget(items_title)
        items_top.addStretch(1)
        items_top.addWidget(items_hint)
        items_layout.addLayout(items_top)
        self.items_table = QTableWidget(0, 9)
        self.items_table.setObjectName("billItemsTable")
        self.items_table.setHorizontalHeaderLabels(["Product", "Item / service *", "HSN/SAC", "Qty", "Unit", "Rate (₹)", "Disc %", "GST %", "Line total"])
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.verticalHeader().setDefaultSectionSize(38)
        self.items_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.setWordWrap(False)
        self.items_table.setMinimumHeight(190)
        self.items_table.setMinimumWidth(0)
        self.items_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.items_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.items_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.items_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.items_table.horizontalHeader()
        header.setMinimumSectionSize(48)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate((142, 210, 78, 54, 52, 88, 58, 58, 106)):
            self.items_table.setColumnWidth(column, width)
        self.items_table.cellChanged.connect(self._recalculate_display)
        items_layout.addWidget(self.items_table)
        item_actions = QHBoxLayout()
        add_item = HoverButton("Add item")
        add_item.setIcon(svg_icon("plus", "#829B3E", 15))
        add_item.clicked.connect(self.add_item_row)
        remove_item = HoverButton("Remove selected")
        remove_item.setIcon(svg_icon("trash-2", "#8B604A", 15))
        remove_item.clicked.connect(self.remove_selected_item)
        item_actions.addWidget(add_item)
        item_actions.addWidget(remove_item)
        item_actions.addStretch(1)
        item_actions.addWidget(QLabel("Invoice discount (₹)"))
        self.invoice_discount = QDoubleSpinBox()
        self.invoice_discount.setRange(0, 999999999)
        self.invoice_discount.setDecimals(2)
        self.invoice_discount.setMaximumWidth(170)
        self.invoice_discount.setPrefix("₹ ")
        item_actions.addWidget(self.invoice_discount)
        self.invoice_discount.valueChanged.connect(self._recalculate_display)
        items_layout.addLayout(item_actions)
        self.calculated_totals = QLabel("Subtotal ₹0.00   ·   Discount ₹0.00   ·   Tax ₹0.00   ·   Total ₹0.00")
        self.calculated_totals.setObjectName("billTotalsSummary")
        self.calculated_totals.setWordWrap(True)
        self.calculated_totals.setMinimumHeight(42)
        items_layout.addWidget(self.calculated_totals)
        content_layout.addWidget(items_card)

        notes_card = QFrame()
        self.notes_card = notes_card
        notes_card.setObjectName("contentCard")
        notes_layout = QGridLayout(notes_card)
        notes_layout.setContentsMargins(20, 18, 20, 18)
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Optional customer-facing notes…")
        self.notes.setMaximumHeight(92)
        self.terms = QTextEdit()
        self.terms.setPlaceholderText("Optional payment terms and conditions…")
        self.terms.setMaximumHeight(92)
        notes_layout.addWidget(QLabel("Notes"), 0, 0)
        notes_layout.addWidget(QLabel("Terms & conditions"), 0, 1)
        notes_layout.addWidget(self.notes, 1, 0)
        notes_layout.addWidget(self.terms, 1, 1)
        content_layout.addWidget(notes_card)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.save_button = HoverButton("Save draft")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setIcon(svg_icon("file-check", "#171916", 16))
        self.save_button.clicked.connect(lambda: self._save(False))
        self.issue_button = HoverButton("Save & issue bill")
        self.issue_button.setIcon(svg_icon("check", "#171916", 16))
        self.issue_button.setObjectName("primaryButton")
        self.issue_button.clicked.connect(lambda: self._save(True))
        footer.addWidget(self.save_button)
        footer.addWidget(self.issue_button)
        outer.addLayout(footer)

    def _scroll_to_step(self, step_key: str) -> None:
        target = {"customer": self.customer_card, "items": self.items_card, "review": self.notes_card}.get(step_key)
        if target is None:
            return
        bar = self.scroll.verticalScrollBar()
        animation = QPropertyAnimation(bar, b"value", self)
        animation.setDuration(300)
        animation.setStartValue(bar.value())
        animation.setEndValue(max(0, target.y() - 8))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._flow_animations.append(animation)
        animation.finished.connect(lambda current=animation: self._flow_animations.remove(current) if current in self._flow_animations else None)
        animation.start()

    def _update_theme_preview(self, *args) -> None:
        if not hasattr(self, "theme_preview"):
            return
        selected_id = self.template_combo.currentData() if hasattr(self, "template_combo") else None
        template = next((item for item in self.bill_service.list_templates(self.session.business_id) if item["template_id"] == selected_id), None)
        if template is None:
            template = next((item for item in self.bill_service.list_templates(self.session.business_id) if item["is_default"]), None)
        if template is None:
            template = {"template_name": "KoshFlow Classic", "accent_color": "#C9E86A", "layout_json": "{}"}
        self.theme_preview.set_template(template)

    def add_item_row(self, values: dict | None = None) -> None:
        row = self.items_table.rowCount()
        self.items_table.blockSignals(True)
        self.items_table.insertRow(row)

        product_combo = QComboBox()
        product_combo.setObjectName("catalogProductCombo")
        product_combo.setMinimumWidth(0)
        product_combo.setMaximumWidth(150)
        product_combo.setFixedHeight(26)
        product_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        product_combo.setToolTip("Link this invoice line to an inventory product. Free-text lines do not change stock.")
        product_combo.addItem("Select product…", "")
        for product in self.catalog_products:
            product_combo.addItem(f"{product['sku']} · {product['name']}", product["product_id"])
        product_combo.view().setMinimumWidth(240)
        if values and values.get("product_id"):
            index = product_combo.findData(values["product_id"])
            if index >= 0:
                product_combo.setCurrentIndex(index)
        self.items_table.setCellWidget(row, 0, product_combo)

        defaults = ["", "", "1", "pcs", "0.00", "0", "0", "0.00"]
        if values:
            defaults = [
                values.get("description", ""), values.get("hsn_sac", ""), values.get("quantity", "1"),
                values.get("unit", "pcs"), values.get("unit_price", "0.00"),
                values.get("discount_percent", "0"), values.get("tax_rate", "0"), values.get("line_total", "0.00"),
            ]
        for offset, value in enumerate(defaults, start=1):
            item = QTableWidgetItem(str(value))
            if offset == 8:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if offset in {3, 5, 6, 7, 8}:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.items_table.setItem(row, offset, item)
        self.items_table.blockSignals(False)
        product_combo.currentIndexChanged.connect(lambda _index, target_row=row: self._product_selected(target_row))
        self._recalculate_display()

    def _product_selected(self, row: int) -> None:
        combo = self.items_table.cellWidget(row, 0)
        product_id = combo.currentData() if isinstance(combo, QComboBox) else None
        product = next((item for item in self.catalog_products if item["product_id"] == product_id), None)
        if product:
            values = {
                1: product["name"], 2: product.get("hsn_code", ""), 4: product.get("unit", "pcs"),
                5: product.get("selling_price", "0.00"), 7: product.get("tax_rate", "0"),
            }
            self.items_table.blockSignals(True)
            for column, value in values.items():
                cell = self.items_table.item(row, column)
                if cell is None:
                    cell = QTableWidgetItem()
                    self.items_table.setItem(row, column, cell)
                cell.setText(str(value))
            self.items_table.blockSignals(False)
            self._recalculate_display()

    def remove_selected_item(self) -> None:
        row = self.items_table.currentRow()
        if row >= 0:
            self.items_table.removeRow(row)
            self._recalculate_display()

    def _customer_type_changed(self, value: str) -> None:
        self.customer_gstin.setPlaceholderText("GSTIN (required for B2B)" if value == "B2B" else "GSTIN (optional for B2C)")

    def _toggle_due_date(self, value: str) -> None:
        self.due_date.setEnabled(value == "Due date set")

    def _read_items(self) -> list[dict]:
        items = []
        for row in range(self.items_table.rowCount()):
            def cell(column, default=""):
                item = self.items_table.item(row, column)
                return item.text().strip() if item else default
            product_combo = self.items_table.cellWidget(row, 0)
            product_id = str(product_combo.currentData() or "") if isinstance(product_combo, QComboBox) else ""
            if not product_id and not any(cell(column) for column in range(1, 8)):
                continue
            items.append({
                "product_id": product_id or None,
                "description": cell(1), "hsn_sac": cell(2), "quantity": cell(3, "1"),
                "unit": cell(4, "pcs") or "pcs", "unit_price": cell(5, "0"),
                "discount_percent": cell(6, "0"), "tax_rate": cell(7, "0"),
            })
        return items

    def _recalculate_display(self, *args) -> None:
        if not hasattr(self, "items_table") or self._updating_amount_cells:
            return

        display_items: list[dict] = []
        valid_rows: list[int] = []
        self._updating_amount_cells = True
        try:
            for row in range(self.items_table.rowCount()):
                def cell(column: int, default: str = "") -> str:
                    item = self.items_table.item(row, column)
                    return item.text().strip() if item else default

                product_combo = self.items_table.cellWidget(row, 0)
                product_id = str(product_combo.currentData() or "") if isinstance(product_combo, QComboBox) else ""
                if not product_id and not any(cell(column) for column in range(1, 8)):
                    continue
                try:
                    quantity = Decimal(cell(3, "1") or "1")
                    unit_price = Decimal(cell(5, "0") or "0")
                    discount = Decimal(cell(6, "0") or "0")
                    tax_rate = Decimal(cell(7, "0") or "0")
                    if (
                        quantity <= 0 or unit_price < 0 or discount < 0 or discount > 100
                        or tax_rate < 0 or tax_rate > 100
                    ):
                        raise InvalidOperation
                    display_items.append({
                        "product_id": product_id or None,
                        "description": cell(1), "hsn_sac": cell(2), "quantity": quantity,
                        "unit": cell(4, "pcs") or "pcs", "unit_price": unit_price,
                        "discount_percent": discount, "tax_rate": tax_rate,
                    })
                    valid_rows.append(row)
                except (InvalidOperation, ValueError):
                    amount_item = self.items_table.item(row, 8)
                    if amount_item is None:
                        amount_item = QTableWidgetItem()
                        self.items_table.setItem(row, 8, amount_item)
                    amount_item.setText("—")

            invoice_discount = Decimal(str(self.invoice_discount.value())) if hasattr(self, "invoice_discount") else Decimal("0")
            totals, calculated_rows = self.bill_service._calculate_items(display_items, invoice_discount)
            for row, calculated in zip(valid_rows, calculated_rows):
                amount_item = self.items_table.item(row, 8)
                if amount_item is None:
                    amount_item = QTableWidgetItem()
                    self.items_table.setItem(row, 8, amount_item)
                amount_item.setText(calculated["line_total"])
                amount_item.setFlags(amount_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                amount_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        except (InvalidOperation, ValueError, ArithmeticError):
            totals = {"subtotal": "0.00", "discount_total": "0.00", "tax_total": "0.00", "grand_total": "0.00"}
        finally:
            self._updating_amount_cells = False

        self.calculated_totals.setText(
            f"Subtotal ₹{Decimal(totals['subtotal']):,.2f}   ·   "
            f"Discounts ₹{Decimal(totals['discount_total']):,.2f}   ·   "
            f"Tax ₹{Decimal(totals['tax_total']):,.2f}   ·   "
            f"Total ₹{Decimal(totals['grand_total']):,.2f}"
        )

    def _customer_record_selected(self, *_args) -> None:
        customer_id = str(self.customer_record.currentData() or "")
        customer = next((row for row in self.customer_records if row["customer_id"] == customer_id), None)
        if not customer:
            return
        self.customer_name.setText(customer["name"])
        self.customer_phone.setText(customer["phone"])
        self.customer_email.setText(customer["email"])
        self.customer_gstin.setText(customer["gstin"])
        self.customer_address.setText(customer["address"])
        self.place_of_supply.setText(customer["state"])
        self.customer_type.setCurrentText("B2B" if customer["gstin"] else "B2C")

    def _load_bill(self, bill_id: str) -> None:
        bill = self.bill_service.get_bill(self.session.business_id, bill_id)
        if not bill:
            QMessageBox.warning(self, "Bill not found", "The selected bill no longer exists.")
            self.on_cancel()
            return
        if bill["status"] != "draft":
            QMessageBox.information(self, "Draft editing only", "Issued bills cannot be edited. Use Manage Bills to view, record payments, or cancel where allowed.")
            self.on_cancel()
            return
        self.customer_type.setCurrentText(bill["customer_type"])
        record_index = self.customer_record.findData(bill.get("customer_id") or "")
        self.customer_record.setCurrentIndex(max(0, record_index))
        document_labels = {"tax_invoice": "Tax invoice", "bill_of_supply": "Bill of supply", "proforma": "Pro forma invoice", "estimate": "Estimate / quotation"}
        self.document_type.setCurrentText(document_labels.get(bill["document_type"], "Tax invoice"))
        self.customer_name.setText(bill["customer_name"])
        self.customer_phone.setText(bill["customer_phone"])
        self.customer_email.setText(bill["customer_email"])
        self.customer_gstin.setText(bill["customer_gstin"])
        self.customer_address.setText(bill["customer_address"])
        self.place_of_supply.setText(bill["place_of_supply"])
        self.invoice_date.setDate(QDate.fromString(bill["invoice_date"], "yyyy-MM-dd"))
        if bill["due_date"]:
            self.due_date.setDate(QDate.fromString(bill["due_date"], "yyyy-MM-dd"))
        else:
            self.due_date_check.setCurrentText("No due date")
        index = self.template_combo.findData(bill.get("template_id") or "")
        self.template_combo.setCurrentIndex(max(index, 0))
        self.invoice_discount.setValue(max(0.0, float(Decimal(bill.get("invoice_discount", "0.00")))))
        self.notes.setPlainText(bill["notes"])
        self.terms.setPlainText(bill["terms"])
        for item in bill["items"]:
            self.add_item_row(item)

    def _save(self, issue_after: bool) -> None:
        document_type_map = {
            "Tax invoice": "tax_invoice", "Bill of supply": "bill_of_supply",
            "Pro forma invoice": "proforma", "Estimate / quotation": "estimate",
        }
        template_id = self.template_combo.currentData()
        values = {
            "customer_id": self.customer_record.currentData() or None,
            "customer_type": self.customer_type.currentText(),
            "document_type": document_type_map.get(self.document_type.currentText(), "tax_invoice"),
            "customer_name": self.customer_name.text(), "customer_phone": self.customer_phone.text(),
            "customer_email": self.customer_email.text(), "customer_gstin": self.customer_gstin.text(),
            "customer_address": self.customer_address.text(), "place_of_supply": self.place_of_supply.text(),
            "invoice_date": self.invoice_date.date().toString("yyyy-MM-dd"),
            "due_date": self.due_date.date().toString("yyyy-MM-dd") if self.due_date_check.currentText() == "Due date set" else "",
            "notes": self.notes.toPlainText(), "terms": self.terms.toPlainText(),
            "items": self._read_items(), "invoice_discount": self.invoice_discount.value(),
            "template_id": template_id,
        }
        try:
            if self.bill_id:
                self.bill_service.update_draft(self.session.business_id, self.session.user_id, self.bill_id, values)
            else:
                self.bill_id = self.bill_service.create_bill(self.session.business_id, self.session.user_id, values)
            if issue_after:
                confirm = QMessageBox.question(
                    self, "Issue bill", "Issue this bill now? An issued bill becomes an auditable business document and can no longer be edited as a draft.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if confirm != QMessageBox.StandardButton.Yes:
                    return
                self.bill_service.issue_bill(self.session.business_id, self.session.user_id, self.bill_id)
            self.on_saved(self.bill_id)
        except (BillError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot save bill", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", f"The bill could not be saved. No success was reported.\n\n{exc}")
