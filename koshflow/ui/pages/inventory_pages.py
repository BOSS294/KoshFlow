"""Inventory and purchasing desktop workspaces.

Purpose: Provide production-oriented product, supplier, stock, purchasing and return screens.
Project: KoshFlow | Version: 0.5.0
Canonical path: koshflow/ui/pages/inventory_pages.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Route to the page classes from MainWindow using the shared Database and Session.
Changelog: v0.5.0 — Added generated SKU display, category picker, HSN suggestions and richer stock movement register.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QListWidget,
)

from koshflow.core.database import Database
from koshflow.core.permissions import has_permission
from koshflow.core.session import Session
from koshflow.services.inventory_service import InventoryError, InventoryService
from koshflow.ui.components import CardFrame, HoverButton, make_line_edit
from koshflow.ui.icons import svg_icon
from koshflow.ui.pages.billing_hub_page import ActionCard


SUCCESS_ACCENT = "#829B3E"


def _money(value: Any) -> str:
    try:
        return f"₹{Decimal(str(value or '0')):,.2f}"
    except Exception:
        return "₹0.00"


def _value(item: QComboBox) -> str:
    return str(item.currentData() or "")


def _set_combo_data(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _header(root: QVBoxLayout, eyebrow: str, title: str, subtitle: str, action_text: str | None = None,
            action_callback=None) -> None:
    top = QHBoxLayout()
    copy = QVBoxLayout()
    copy.setSpacing(4)
    first = QLabel(eyebrow.upper())
    first.setObjectName("eyebrow")
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    body = QLabel(subtitle)
    body.setObjectName("muted")
    body.setWordWrap(True)
    copy.addWidget(first)
    copy.addWidget(heading)
    copy.addWidget(body)
    top.addLayout(copy, 1)
    if action_text and action_callback:
        button = HoverButton(action_text)
        button.setObjectName("primaryButton")
        button.setIcon(svg_icon("plus", "#171916", 16))
        button.clicked.connect(action_callback)
        top.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
    root.addLayout(top)


def _make_table(columns: list[str], min_height: int = 330) -> QTableWidget:
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


def _selected_id(table: QTableWidget) -> str | None:
    selected = table.selectedItems()
    return str(selected[0].data(Qt.ItemDataRole.UserRole)) if selected and selected[0].data(Qt.ItemDataRole.UserRole) else None


def _put_row(table: QTableWidget, values: list[Any], identifier: str, right_columns: set[int] | None = None) -> None:
    row = table.rowCount()
    table.insertRow(row)
    right_columns = right_columns or set()
    for col, value in enumerate(values):
        item = QTableWidgetItem(str(value if value is not None else ""))
        item.setData(Qt.ItemDataRole.UserRole, identifier)
        if col in right_columns:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, col, item)


def _set_table_empty(table: QTableWidget, empty: QLabel, rows: int) -> None:
    empty.setVisible(rows == 0)
    table.setVisible(rows > 0)


def _export_csv(parent: QWidget, filename: str, headers: list[str], rows: list[list[Any]]) -> None:
    path, _ = QFileDialog.getSaveFileName(parent, "Export CSV", filename, "CSV files (*.csv)")
    if not path:
        return
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        QMessageBox.information(parent, "Export completed", f"CSV exported successfully:\n{path}")
    except OSError as exc:
        QMessageBox.critical(parent, "Export failed", f"Could not write the CSV file.\n\n{exc}")


def _spin(minimum: float = 0, maximum: float = 1_000_000_000, decimals: int = 2, value: float = 0) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMinimumHeight(38)
    return widget


class MetricCard(CardFrame):
    def __init__(self, label: str, value: str, icon: str, hint: str = ""):
        super().__init__("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(6)
        top = QHBoxLayout()
        name = QLabel(label)
        name.setObjectName("muted")
        glyph = QLabel()
        glyph.setPixmap(svg_icon(icon, SUCCESS_ACCENT, 18).pixmap(18, 18))
        top.addWidget(name, 1)
        top.addWidget(glyph)
        number = QLabel(value)
        number.setObjectName("sectionTitle")
        number.setStyleSheet("font-size:21px;font-weight:760;")
        layout.addLayout(top)
        layout.addWidget(number)
        if hint:
            text = QLabel(hint)
            text.setObjectName("muted")
            text.setWordWrap(True)
            text.setStyleSheet("font-size:10px;")
            layout.addWidget(text)


class InventoryHubPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database, self.session, self.navigate = database, session, navigate
        self.service = InventoryService(database)
        self.setObjectName("inventoryHubPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        _header(root, "Inventory workspace", "Inventory & purchasing", "Control product records, stock movements, supplier orders and purchasing costs from one workspace.", "Product catalog", lambda: navigate("product_catalog"))
        self.metrics_layout = QGridLayout()
        self.metrics_layout.setSpacing(12)
        root.addLayout(self.metrics_layout)
        title = QLabel("Inventory workflows")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        actions = [
            ("Product catalog", "Create and maintain SKUs, barcodes, HSN, prices, tax and reorder levels.", "package", "product_catalog", True),
            ("Stock movements", "Review the traceable movement ledger and product-level history.", "arrow-left-right", "stock_movements", False),
            ("Stock adjustment", "Record counted stock and controlled add/remove adjustments.", "sliders-horizontal", "stock_adjustment", False),
            ("Low-stock watch", "Find products at or below their reorder threshold.", "alert-triangle", "inventory_low_stock", False),
            ("Stock valuation", "Review on-hand quantities and moving-average inventory value.", "chart-no-axes-combined", "inventory_reports", False),
            ("Purchasing desk", "Manage suppliers, purchase orders, supplier bills, payments and returns.", "shopping-cart", "purchasing", False),
        ]
        grid = QGridLayout()
        grid.setSpacing(13)
        for i, (title_text, body, icon, target, accent) in enumerate(actions):
            card = ActionCard(title_text, body, icon, accent)
            card.clicked.connect(lambda checked=False, key=target: navigate(key))
            grid.addWidget(card, i // 3, i % 3)
        root.addLayout(grid)
        foot = QFrame()
        foot.setObjectName("softPanel")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(14, 11, 14, 11)
        glyph = QLabel()
        glyph.setPixmap(svg_icon("shield-check", SUCCESS_ACCENT, 19).pixmap(19, 19))
        fl.addWidget(glyph)
        note = QLabel("Stock changes are transactional and recorded in an immutable movement ledger. Use supplier returns rather than deleting posted purchasing records.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        fl.addWidget(note, 1)
        root.addWidget(foot)
        root.addStretch(1)
        self.refresh()

    def refresh(self, *args):
        while self.metrics_layout.count():
            item = self.metrics_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        summary = self.service.inventory_summary(self.session.business_id)
        specs = [
            ("Active products", str(summary["product_count"]), "package", "Products in this workspace"),
            ("Stock valuation", _money(summary["valuation"]), "wallet", "Moving-average cost basis"),
            ("Low-stock items", str(summary["low_stock_count"]), "alert-triangle", "At or below reorder level"),
            ("SKUs with stock", str(summary["products_with_stock"]), "boxes", f"{summary['movements_today']} movements today"),
        ]
        for i, (label, value, icon, hint) in enumerate(specs):
            self.metrics_layout.addWidget(MetricCard(label, value, icon, hint), 0, i)


class CategoryPickerDialog(QDialog):
    """Searchable category-selection modal with sensible defaults and custom values."""
    DEFAULT_CATEGORIES = [
        "General", "Food & groceries", "Beverages", "Electronics", "Mobile accessories",
        "Computer accessories", "Clothing & apparel", "Footwear", "Personal care", "Cosmetics",
        "Cleaning supplies", "Home & kitchen", "Furniture", "Stationery & books", "Hardware & tools",
        "Building materials", "Medicines & healthcare", "Packaging", "Raw materials", "Services", "Other",
    ]

    def __init__(self, categories: list[str], current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose product category")
        self.setMinimumSize(440, 500)
        self.selected_category = current
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)
        title = QLabel("Product category")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Choose an existing category or create one for your catalog.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        self.search = make_line_edit("Search categories…")
        self.list = QListWidget()
        combined = sorted({item.strip() for item in self.DEFAULT_CATEGORIES + categories if item.strip()}, key=str.casefold)
        self.list.addItems(combined)
        self.search.textChanged.connect(self._filter)
        self.list.itemDoubleClicked.connect(self._choose_item)
        if current:
            matches = self.list.findItems(current, Qt.MatchFlag.MatchFixedString)
            if matches:
                self.list.setCurrentItem(matches[0])
        custom_row = QHBoxLayout()
        self.custom = make_line_edit("Or type a new category…")
        use_custom = HoverButton("Use custom")
        use_custom.clicked.connect(self._choose_custom)
        custom_row.addWidget(self.custom, 1)
        custom_row.addWidget(use_custom)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._choose_selected)
        buttons.rejected.connect(self.reject)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(self.search)
        root.addWidget(self.list, 1)
        root.addLayout(custom_row)
        root.addWidget(buttons)

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(query not in item.text().casefold())

    def _choose_item(self, item) -> None:
        self.selected_category = item.text()
        self.accept()

    def _choose_selected(self) -> None:
        item = self.list.currentItem()
        if item and not item.isHidden():
            self.selected_category = item.text()
            self.accept()
        elif self.custom.text().strip():
            self._choose_custom()

    def _choose_custom(self) -> None:
        value = self.custom.text().strip()
        if not value:
            QMessageBox.information(self, "Category required", "Choose a category or enter a custom category.")
            return
        self.selected_category = value[:80]
        self.accept()


class ProductDialog(QDialog):
    def __init__(self, service: InventoryService, business_id: str, product: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.service, self.business_id, self.product = service, business_id, product
        self.setWindowTitle("Edit product" if product else "Add product")
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.sku = make_line_edit("Auto-generated SKU")
        self.sku.setReadOnly(True)
        self.sku.setText(str(product["sku"]) if product else service.next_sku(business_id))
        self.name = make_line_edit("Product name")
        self.barcode = make_line_edit("Optional barcode")
        self.category = make_line_edit("Choose a category")
        self.category.setReadOnly(True)
        category_row = QHBoxLayout()
        category_row.addWidget(self.category, 1)
        self.category_button = HoverButton("Choose…")
        self.category_button.clicked.connect(self._choose_category)
        category_row.addWidget(self.category_button)
        category_wrap = QWidget()
        category_wrap.setLayout(category_row)
        self.hsn = make_line_edit("Suggested when product details match")
        self.hsn_hint = QLabel("HSN suggestions are assistive only. Verify the classification for the exact product before issuing tax invoices.")
        self.hsn_hint.setObjectName("muted")
        self.hsn_hint.setWordWrap(True)
        self.unit = QComboBox()
        self.unit.setEditable(True)
        self.unit.addItems(["pcs", "box", "kg", "g", "ltr", "ml", "m", "cm", "pair", "set", "pack", "dozen", "hour"])
        self.purchase_price = _spin()
        self.selling_price = _spin()
        self.tax = _spin(0, 100, 2)
        self.reorder = _spin(0, 1_000_000_000, 3)
        self.opening = _spin(0, 1_000_000_000, 3)
        self.description = QTextEdit()
        self.description.setMaximumHeight(70)
        fields = [
            ("SKU / code · automatic", self.sku), ("Product name *", self.name), ("Barcode", self.barcode),
            ("Category *", category_wrap), ("HSN code", self.hsn), ("Unit", self.unit),
            ("Last purchase price (₹)", self.purchase_price), ("Selling price (₹)", self.selling_price),
            ("Tax rate (%)", self.tax), ("Reorder level", self.reorder),
        ]
        for label, widget in fields:
            form.addRow(label, widget)
            if label == "HSN code":
                form.addRow("HSN guidance", self.hsn_hint)
        if not product:
            form.addRow("Opening stock", self.opening)
        form.addRow("Description", self.description)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        if product:
            for widget, key in [(self.name,"name"),(self.barcode,"barcode"),(self.category,"category"),(self.hsn,"hsn_code"),(self.unit,"unit")]:
                value = str(product.get(key) or "")
                if isinstance(widget, QComboBox):
                    widget.setCurrentText(value)
                else:
                    widget.setText(value)
            self.description.setPlainText(str(product.get("description", "")))
            self.purchase_price.setValue(float(product.get("last_purchase_price", 0)))
            self.selling_price.setValue(float(product.get("selling_price", 0)))
            self.tax.setValue(float(product.get("tax_rate", 0)))
            self.reorder.setValue(float(product.get("reorder_level", 0)))
            self.hsn_hint.setText("Saved HSN code. If the item changed, verify its classification against an official/current source.")
        self._auto_hsn_value = ""
        self.name.editingFinished.connect(self._suggest_hsn)
        self.hsn.editingFinished.connect(self._manual_hsn_changed)

    def _choose_category(self) -> None:
        dialog = CategoryPickerDialog(self.service.product_categories(self.business_id), self.category.text(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.category.setText(dialog.selected_category)
            self._suggest_hsn()

    def _suggest_hsn(self) -> None:
        suggestion = self.service.suggest_hsn_code(self.name.text(), self.category.text())
        if not suggestion:
            if not self.hsn.text().strip():
                self.hsn_hint.setText("No high-confidence suggestion for this item. Enter the verified HSN code manually.")
            return
        code = suggestion["code"]
        if not self.product and (not self.hsn.text().strip() or self.hsn.text().strip() == self._auto_hsn_value):
            self.hsn.setText(code)
            self._auto_hsn_value = code
        self.hsn_hint.setText(f"Suggested HSN {code}: {suggestion['reason']} Verify the exact goods and tax treatment before use.")

    def _manual_hsn_changed(self) -> None:
        if self.hsn.text().strip() != self._auto_hsn_value:
            self._auto_hsn_value = ""

    def _validate_and_accept(self) -> None:
        if not self.name.text().strip():
            return QMessageBox.warning(self, "Product name required", "Enter a product name before saving.")
        if not self.category.text().strip():
            return QMessageBox.warning(self, "Category required", "Choose a category from the selection modal.")
        self.accept()

    def values(self) -> dict[str, Any]:
        return {"sku": "" if not self.product else self.product["sku"], "name": self.name.text(), "barcode": self.barcode.text(),
                "category": self.category.text() or "General", "hsn_code": self.hsn.text(), "unit": self.unit.currentText(),
                "purchase_price": self.purchase_price.value(), "selling_price": self.selling_price.value(),
                "tax_rate": self.tax.value(), "reorder_level": self.reorder.value(),
                "opening_quantity": self.opening.value(), "description": self.description.toPlainText()}


class ProductCatalogPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, *, low_stock_only: bool = False, parent=None):
        super().__init__(parent)
        self.database, self.session, self.navigate = database, session, navigate
        self.service = InventoryService(database)
        self.low_stock_only = low_stock_only
        self._rows: list[dict[str, Any]] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(13)
        _header(root, "Inventory / products", "Low-stock watch" if low_stock_only else "Product catalog",
                "Review products at their reorder threshold." if low_stock_only else "Manage catalog identity, tax, pricing and reorder thresholds without editing stock behind the ledger.",
                "Add product", self._add)
        tools = QFrame()
        tools.setObjectName("sectionToolbar")
        tl = QHBoxLayout(tools)
        tl.setContentsMargins(10, 7, 10, 7)
        self.search = make_line_edit("Search name, SKU, barcode or HSN…")
        self.search.textChanged.connect(self.refresh)
        self.category = QComboBox()
        self.category.addItem("All categories", "All")
        self.category.currentIndexChanged.connect(self.refresh)
        tl.addWidget(self.search, 1)
        tl.addWidget(QLabel("Category"))
        tl.addWidget(self.category)
        export = HoverButton("Export CSV")
        export.clicked.connect(self._export)
        tl.addWidget(export)
        refresh = HoverButton("Refresh")
        refresh.clicked.connect(self.refresh)
        tl.addWidget(refresh)
        root.addWidget(tools)
        frame = QFrame()
        frame.setObjectName("contentCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(10, 10, 10, 10)
        self.table = _make_table(["SKU", "Product", "Category", "On hand", "Reorder at", "Avg. cost", "Sell price", "Tax", "Status"])
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        box.addWidget(self.table)
        self.empty = QLabel("No matching products. Add a product to start tracking stock.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty)
        root.addWidget(frame, 1)
        actions = QHBoxLayout()
        self.edit_button = HoverButton("Edit product")
        self.edit_button.clicked.connect(self._edit)
        self.adjust_button = HoverButton("Adjust stock")
        self.adjust_button.clicked.connect(self._adjust)
        self.archive_button = HoverButton("Archive product")
        self.archive_button.clicked.connect(self._archive)
        back = HoverButton("Inventory home")
        back.clicked.connect(lambda: navigate("inventory"))
        for button in [self.edit_button, self.adjust_button, self.archive_button, back]:
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)
        self.refresh()

    def refresh(self, *args):
        categories = self.service.product_categories(self.session.business_id)
        old = self.category.currentData() or "All"
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", "All")
        for category in categories:
            self.category.addItem(category, category)
        _set_combo_data(self.category, str(old))
        self.category.blockSignals(False)
        self._rows = self.service.list_products(self.session.business_id, self.search.text(), str(self.category.currentData() or "All"), low_stock_only=self.low_stock_only)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for product in self._rows:
            _put_row(self.table, [product["sku"], product["name"], product["category"], product["quantity_on_hand"],
                                  product["reorder_level"], _money(product["average_cost"]), _money(product["selling_price"]),
                                  f"{product['tax_rate']}%", "Active" if product["is_active"] else "Archived"], str(product["product_id"]), {3,4,5,6,7})
        self.table.setSortingEnabled(True)
        _set_table_empty(self.table, self.empty, len(self._rows))
        self._selection_changed()

    def _product(self):
        identifier = _selected_id(self.table)
        return self.service.get_product(self.session.business_id, identifier) if identifier else None

    def _selection_changed(self):
        product = self._product()
        self.edit_button.setEnabled(bool(product and product["is_active"] and has_permission(self.session.role, "inventory.manage")))
        self.adjust_button.setEnabled(bool(product and product["is_active"] and has_permission(self.session.role, "inventory.adjust")))
        self.archive_button.setEnabled(bool(product and product["is_active"] and has_permission(self.session.role, "inventory.manage")))

    def _add(self):
        if not has_permission(self.session.role, "inventory.manage"):
            return QMessageBox.warning(self, "Permission required", "Your role cannot create products.")
        dialog = ProductDialog(self.service, self.session.business_id, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.create_product(self.session.business_id, self.session.user_id, dialog.values())
            self.refresh()
        except InventoryError as exc:
            QMessageBox.warning(self, "Could not add product", str(exc))

    def _edit(self):
        product = self._product()
        if not product:
            return QMessageBox.information(self, "Select a product", "Select a product first.")
        dialog = ProductDialog(self.service, self.session.business_id, product, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.update_product(self.session.business_id, self.session.user_id, product["product_id"], dialog.values())
            self.refresh()
        except InventoryError as exc:
            QMessageBox.warning(self, "Could not update product", str(exc))

    def _adjust(self):
        product = self._product()
        if product:
            self.navigate(f"stock_adjustment:{product['product_id']}")

    def _archive(self):
        product = self._product()
        if not product:
            return
        result = QMessageBox.question(self, "Archive product", f"Archive {product['name']}? It can no longer be selected for new transactions.")
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.archive_product(self.session.business_id, self.session.user_id, product["product_id"])
            self.refresh()
        except InventoryError as exc:
            QMessageBox.warning(self, "Could not archive product", str(exc))

    def _export(self):
        data = self.service.export_products_csv(self.session.business_id)
        path, _ = QFileDialog.getSaveFileName(self, "Export product catalog", "koshflow-products.csv", "CSV files (*.csv)")
        if path:
            try:
                Path(path).write_text(data, encoding="utf-8-sig")
                QMessageBox.information(self, "Export completed", "Product catalog exported.")
            except OSError as exc:
                QMessageBox.critical(self, "Export failed", str(exc))


class SupplierDialog(QDialog):
    def __init__(self, supplier: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.supplier = supplier
        self.setWindowTitle("Edit supplier" if supplier else "Add supplier")
        self.setMinimumWidth(540)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(9)
        self.code = make_line_edit("e.g. SUP-0001")
        self.name = make_line_edit("Supplier or legal business name")
        self.contact = make_line_edit("Contact person")
        self.phone = make_line_edit("Phone")
        self.email = make_line_edit("Email")
        self.gstin = make_line_edit("GSTIN (optional)")
        self.pan = make_line_edit("PAN (optional)")
        self.address = make_line_edit("Address")
        self.city = make_line_edit("City")
        self.state = make_line_edit("State")
        self.pin = make_line_edit("PIN code")
        self.terms = QSpinBox(); self.terms.setRange(0, 365); self.terms.setSuffix(" days")
        self.notes = QTextEdit(); self.notes.setMaximumHeight(66)
        fields = [("Supplier code *",self.code),("Supplier name *",self.name),("Contact person",self.contact),("Phone",self.phone),("Email",self.email),("GSTIN",self.gstin),("PAN",self.pan),("Address",self.address),("City",self.city),("State",self.state),("PIN code",self.pin),("Payment terms",self.terms),("Notes",self.notes)]
        for label, widget in fields: form.addRow(label, widget)
        root.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)
        if supplier:
            for widget,key in [(self.code,"supplier_code"),(self.name,"name"),(self.contact,"contact_person"),(self.phone,"phone"),(self.email,"email"),(self.gstin,"gstin"),(self.pan,"pan"),(self.address,"address"),(self.city,"city"),(self.state,"state"),(self.pin,"pincode")]: widget.setText(str(supplier.get(key,"")))
            self.terms.setValue(int(supplier.get("payment_terms_days",0))); self.notes.setPlainText(str(supplier.get("notes","")))

    def values(self):
        return {"supplier_code":self.code.text(),"name":self.name.text(),"contact_person":self.contact.text(),"phone":self.phone.text(),"email":self.email.text(),"gstin":self.gstin.text(),"pan":self.pan.text(),"address":self.address.text(),"city":self.city.text(),"state":self.state.text(),"pincode":self.pin.text(),"payment_terms_days":self.terms.value(),"notes":self.notes.toPlainText()}


class SupplierCatalogPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None):
        super().__init__(parent)
        self.database,self.session,self.navigate=database,session,navigate
        self.service=InventoryService(database)
        root=QVBoxLayout(self); root.setContentsMargins(28,22,28,20); root.setSpacing(13)
        _header(root,"Purchasing / directory","Suppliers","Maintain supplier identity, GST registration, contacts, payment terms and open payables.","Add supplier",self._add)
        tools=QFrame(); tools.setObjectName("sectionToolbar"); tl=QHBoxLayout(tools); tl.setContentsMargins(10,7,10,7)
        self.search=make_line_edit("Search supplier, code, phone or GSTIN…"); self.search.textChanged.connect(self.refresh)
        export=HoverButton("Export CSV"); export.clicked.connect(self._export)
        refresh=HoverButton("Refresh"); refresh.clicked.connect(self.refresh)
        tl.addWidget(self.search,1); tl.addWidget(export); tl.addWidget(refresh); root.addWidget(tools)
        frame=QFrame(); frame.setObjectName("contentCard"); box=QVBoxLayout(frame); box.setContentsMargins(10,10,10,10)
        self.table=_make_table(["Code","Supplier","Contact","Phone","GSTIN","Terms","Outstanding"]); self.table.itemSelectionChanged.connect(self._selection_changed); self.table.cellDoubleClicked.connect(lambda *_:self._details()); box.addWidget(self.table)
        self.empty=QLabel("No suppliers saved yet. Add your first supplier to start purchasing."); self.empty.setObjectName("muted"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); box.addWidget(self.empty); root.addWidget(frame,1)
        actions=QHBoxLayout(); self.details_btn=HoverButton("View supplier account"); self.details_btn.clicked.connect(self._details); self.edit_btn=HoverButton("Edit supplier"); self.edit_btn.clicked.connect(self._edit); self.archive_btn=HoverButton("Archive supplier"); self.archive_btn.clicked.connect(self._archive); orders=HoverButton("Purchase orders"); orders.clicked.connect(lambda:navigate("purchase_orders")); bills=HoverButton("Purchase bills"); bills.clicked.connect(lambda:navigate("purchase_bills")); back=HoverButton("Purchasing home"); back.clicked.connect(lambda:navigate("purchasing"))
        for button in [self.details_btn,self.edit_btn,self.archive_btn,orders,bills,back]: actions.addWidget(button)
        actions.addStretch(1); root.addLayout(actions); self.refresh()

    def refresh(self,*args):
        self.rows=self.service.list_suppliers(self.session.business_id,self.search.text())
        self.table.setSortingEnabled(False); self.table.setRowCount(0)
        for r in self.rows: _put_row(self.table,[r["supplier_code"],r["name"],r["contact_person"],r["phone"],r["gstin"],f"{r['payment_terms_days']} days",_money(r["outstanding_balance"])],str(r["supplier_id"]),{5,6})
        self.table.setSortingEnabled(True); _set_table_empty(self.table,self.empty,len(self.rows)); self._selection_changed()

    def _supplier(self):
        identifier=_selected_id(self.table); return next((row for row in self.rows if row["supplier_id"]==identifier),None)

    def _selection_changed(self):
        supplier=self._supplier(); permitted=has_permission(self.session.role,"purchasing.manage_suppliers")
        self.details_btn.setEnabled(bool(supplier)); self.edit_btn.setEnabled(bool(supplier and permitted)); self.archive_btn.setEnabled(bool(supplier and permitted))

    def _details(self):
        supplier=self._supplier()
        if supplier:self.navigate(f"supplier_view:{supplier['supplier_id']}")

    def _add(self):
        if not has_permission(self.session.role,"purchasing.manage_suppliers"): return QMessageBox.warning(self,"Permission required","Your role cannot create suppliers.")
        dialog=SupplierDialog(parent=self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.create_supplier(self.session.business_id,self.session.user_id,dialog.values()); self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Could not add supplier",str(exc))

    def _edit(self):
        supplier=self._supplier()
        if not supplier:return QMessageBox.information(self,"Select a supplier","Select a supplier first.")
        dialog=SupplierDialog(supplier,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.update_supplier(self.session.business_id,self.session.user_id,supplier["supplier_id"],dialog.values()); self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Could not update supplier",str(exc))

    def _archive(self):
        supplier=self._supplier()
        if not supplier:return
        if QMessageBox.question(self,"Archive supplier",f"Archive {supplier['name']}?")!=QMessageBox.StandardButton.Yes:return
        try:self.service.archive_supplier(self.session.business_id,self.session.user_id,supplier["supplier_id"]); self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Could not archive supplier",str(exc))

    def _export(self):
        rows=[[r["supplier_code"],r["name"],r["contact_person"],r["phone"],r["email"],r["gstin"],r["payment_terms_days"],r["outstanding_balance"]] for r in self.rows]
        _export_csv(self,"koshflow-suppliers.csv",["Code","Supplier","Contact","Phone","Email","GSTIN","Payment terms days","Outstanding"],rows)


class StockAdjustmentPage(QWidget):
    def __init__(self,database:Database,session:Session,navigate,product_id:str|None=None,parent=None):
        super().__init__(parent); self.database,self.session,self.navigate=database,session,navigate; self.service=InventoryService(database)
        root=QVBoxLayout(self); root.setContentsMargins(30,24,30,20); root.setSpacing(15)
        _header(root,"Inventory / stock control","Stock adjustment","Record physical stock counts, breakage, opening corrections or found stock with a mandatory reason.")
        card=QFrame(); card.setObjectName("contentCard"); card.setMaximumWidth(760); form=QFormLayout(card); form.setContentsMargins(24,22,24,22); form.setSpacing(13)
        self.product=QComboBox()
        self.products=self.service.list_products(session.business_id)
        for p in self.products:self.product.addItem(f"{p['sku']} · {p['name']}  (on hand: {p['quantity_on_hand']} {p['unit']})",p["product_id"])
        if product_id:_set_combo_data(self.product,product_id)
        self.mode=QComboBox(); self.mode.addItem("Set counted quantity", "set"); self.mode.addItem("Add stock", "add"); self.mode.addItem("Remove stock", "remove")
        self.quantity=_spin(0,1_000_000_000,3); self.cost=_spin(0,1_000_000_000,2)
        self.reason=QTextEdit(); self.reason.setPlaceholderText("Required: e.g. Physical stock count on 14 Oct 2026"); self.reason.setMaximumHeight(90)
        self.current=QLabel("Current stock is displayed beside each product."); self.current.setObjectName("muted")
        form.addRow("Product *",self.product); form.addRow("Adjustment type *",self.mode); form.addRow("Quantity / counted total *",self.quantity); form.addRow("Unit cost (₹, optional)",self.cost); form.addRow("Reason *",self.reason); form.addRow("Current count",self.current)
        self.mode.currentIndexChanged.connect(self._mode_changed); self.product.currentIndexChanged.connect(self._product_changed)
        root.addWidget(card,0,Qt.AlignmentFlag.AlignLeft); row=QHBoxLayout(); save=HoverButton("Save adjustment"); save.setObjectName("primaryButton"); save.clicked.connect(self._save); back=HoverButton("Back to inventory"); back.clicked.connect(lambda:navigate("inventory")); row.addWidget(save); row.addWidget(back); row.addStretch(1); root.addLayout(row); root.addStretch(1); self._product_changed()

    def _mode_changed(self):self.quantity.setMinimum(0 if self.mode.currentData()=="set" else 0.001)
    def _product_changed(self):
        product=next((p for p in self.products if p["product_id"]==_value(self.product)),None)
        if product:self.current.setText(f"On hand: {product['quantity_on_hand']} {product['unit']}  ·  Average cost: {_money(product['average_cost'])}"); self.cost.setValue(float(product["average_cost"]))

    def _save(self):
        if not _value(self.product):return QMessageBox.warning(self,"Choose a product","Create a product before adjusting stock.")
        try:
            movement=self.service.adjust_stock(self.session.business_id,self.session.user_id,_value(self.product),str(self.mode.currentData()),self.quantity.value(),self.reason.toPlainText(),self.cost.value())
            QMessageBox.information(self,"Stock adjusted","The adjustment and its audit entry were saved.")
            self.navigate("stock_movements")
        except InventoryError as exc:QMessageBox.warning(self,"Adjustment rejected",str(exc))


class StockMovementsPage(QWidget):
    def __init__(self,database:Database,session:Session,navigate,parent=None):
        super().__init__(parent); self.database,self.session,self.navigate=database,session,navigate; self.service=InventoryService(database)
        root=QVBoxLayout(self); root.setContentsMargins(28,22,28,20); root.setSpacing(13)
        _header(root,"Inventory / stock ledger","Stock movements","Every opening balance, purchase receipt, supplier return and manual adjustment with source and audit context.","Adjust stock",lambda:navigate("stock_adjustment"))
        tools=QFrame(); tools.setObjectName("sectionToolbar"); tl=QHBoxLayout(tools); tl.setContentsMargins(10,7,10,7)
        self.search=make_line_edit("Filter product, SKU, source or reason…"); self.search.textChanged.connect(self.refresh); export=HoverButton("Export CSV"); export.clicked.connect(self._export); refresh=HoverButton("Refresh"); refresh.clicked.connect(self.refresh); tl.addWidget(self.search,1); tl.addWidget(export); tl.addWidget(refresh); root.addWidget(tools)
        frame=QFrame(); frame.setObjectName("contentCard"); box=QVBoxLayout(frame); box.setContentsMargins(10,10,10,10); self.table=_make_table(["Date / time","Product","SKU","Movement","Before","Change","After","Unit cost","Movement value","Source type","Document ref.","Created by","Reason"],420); self.table.setWordWrap(False); self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel); box.addWidget(self.table); self.empty=QLabel("No stock movements yet. Add product opening stock, receive a purchase, or record an adjustment."); self.empty.setObjectName("muted"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); box.addWidget(self.empty); root.addWidget(frame,1); back=HoverButton("Inventory home"); back.clicked.connect(lambda:navigate("inventory")); root.addWidget(back,0,Qt.AlignmentFlag.AlignLeft); self.refresh()

    def refresh(self,*args):
        self.rows=self.service.list_stock_movements(self.session.business_id,self.search.text()); self.table.setSortingEnabled(False); self.table.setRowCount(0)
        for r in self.rows:
            _put_row(self.table,[str(r["created_at"]).replace("T"," ")[:19],r["product_name"],r["sku"],r["movement_type"].replace("_"," ").title(),r.get("quantity_before","0.000"),r["quantity_delta"],r.get("quantity_after","0.000"),_money(r["unit_cost"]),_money(r.get("movement_value","0.00")),r["source_type"],r.get("source_reference") or r["source_id"],r.get("actor_name") or "System / former user",r["reason"]],str(r["stock_movement_id"]),{4,5,6,7,8})
        self.table.setSortingEnabled(True); _set_table_empty(self.table,self.empty,len(self.rows))

    def _export(self):
        rows=[[r["created_at"],r["product_name"],r["sku"],r["movement_type"],r.get("quantity_before","0.000"),r["quantity_delta"],r.get("quantity_after","0.000"),r["unit_cost"],r.get("movement_value","0.00"),r["source_type"],r.get("source_reference") or r["source_id"],r.get("actor_name") or "",r["source_id"],r["reason"]] for r in self.rows]
        _export_csv(self,"koshflow-stock-movements.csv",["Created at","Product","SKU","Movement","Quantity before","Quantity delta","Quantity after","Unit cost","Movement value","Source type","Source reference","Created by","Source ID","Reason"],rows)


class PurchasingHubPage(QWidget):
    def __init__(self,database:Database,session:Session,navigate,parent=None):
        super().__init__(parent); self.database,self.session,self.navigate=database,session,navigate; self.service=InventoryService(database)
        root=QVBoxLayout(self); root.setContentsMargins(28,24,28,24); root.setSpacing(16)
        _header(root,"Purchasing workspace","Purchasing desk","Purchase planning, supplier invoices, goods receipt, supplier payments and returns with stock reconciliation.","Open purchase bills",lambda:navigate("purchase_bills"))
        self.metrics=QGridLayout(); self.metrics.setSpacing(12); root.addLayout(self.metrics)
        title=QLabel("Purchasing workflows"); title.setObjectName("sectionTitle"); root.addWidget(title)
        actions=[
            ("Suppliers","Supplier directory, GSTIN, contacts and payment terms.","truck","suppliers",True),
            ("Purchase orders","Draft, order, receive stock in parts and track completion.","clipboard-list","purchase_orders",False),
            ("Purchase bills","Capture supplier invoice, post stock and track payable balances.","file-text","purchase_bills",False),
            ("Supplier payments","Record UPI, bank, cash and other supplier payments.","wallet","supplier_payments",False),
            ("Supplier returns","Return damaged or excess goods and credit supplier balances.","corner-up-left","supplier_returns",False),
            ("Purchasing reports","Open orders, payables, supplier activity and stock value.","chart-no-axes-combined","purchasing_reports",False),
        ]
        grid=QGridLayout(); grid.setSpacing(13)
        for i,(t,d,ic,key,a) in enumerate(actions):
            card=ActionCard(t,d,ic,a); card.clicked.connect(lambda checked=False,k=key:navigate(k)); grid.addWidget(card,i//3,i%3)
        root.addLayout(grid)
        note=QLabel("Posting a supplier bill records stock only when it is not linked to a purchase order whose receipts have already moved stock. This avoids duplicate inventory."); note.setObjectName("muted"); note.setWordWrap(True); root.addWidget(note); root.addStretch(1); self.refresh()

    def refresh(self,*args):
        while self.metrics.count():
            item=self.metrics.takeAt(0)
            if item.widget():item.widget().deleteLater()
        d=self.service.purchasing_summary(self.session.business_id)
        specs=[("Active suppliers",str(d["supplier_count"]),"truck"),("Open orders",str(d["orders_open"]),"clipboard-list"),("Unpaid bills",str(d["bills_unpaid"]),"file-text"),("Supplier payables",_money(d["supplier_payables"]),"wallet"),("Supplier credits",_money(d["supplier_credits"]),"badge-check")]
        for i,(label,val,icon) in enumerate(specs):self.metrics.addWidget(MetricCard(label,val,icon),0,i)


class PurchaseDocumentDialog(QDialog):
    """Shared line editor for a purchase order or purchase bill."""
    def __init__(self,service:InventoryService,business_id:str,document_type:str,document:dict[str,Any]|None=None,parent=None):
        super().__init__(parent); self.service,self.business_id,self.document_type,self.document=service,business_id,document_type,document; self.line_rows=[]
        is_order=document_type=="order"; self.setWindowTitle(("Edit " if document else "Create ")+ ("purchase order" if is_order else "purchase bill")); self.setMinimumSize(950,680)
        root=QVBoxLayout(self); scroll=QScrollArea(); scroll.setWidgetResizable(True); inner=QWidget(); body=QVBoxLayout(inner); body.setSpacing(13)
        form=QFormLayout(); form.setSpacing(8); self.supplier=QComboBox()
        for s in service.list_suppliers(business_id):self.supplier.addItem(f"{s['supplier_code']} · {s['name']}",s["supplier_id"])
        self.document_date=QDateEdit(); self.document_date.setCalendarPopup(True); self.document_date.setDate(QDate.currentDate()); self.document_date.setDisplayFormat("dd MMM yyyy")
        self.due_date=QDateEdit(); self.due_date.setCalendarPopup(True); self.due_date.setDate(QDate.currentDate().addDays(14)); self.due_date.setDisplayFormat("dd MMM yyyy")
        self.supplier_invoice=make_line_edit("Supplier's invoice number (optional)")
        self.source_po=QComboBox(); self.source_po.addItem("No linked order — stock will be received on posting", "")
        self.received_orders = service.list_purchase_orders(business_id, status="received")
        for order in self.received_orders:
            self.source_po.addItem(f"{order['order_number']} · {order['supplier_name']}",order["purchase_order_id"])
        self.notes=make_line_edit("Internal note")
        form.addRow("Supplier *",self.supplier); form.addRow("Order date" if is_order else "Supplier invoice date",self.document_date); form.addRow("Expected receipt" if is_order else "Due date",self.due_date)
        if not is_order:form.addRow("Supplier invoice no.",self.supplier_invoice); form.addRow("Link fully received PO",self.source_po)
        form.addRow("Notes",self.notes); body.addLayout(form)
        title=QLabel("Items"); title.setObjectName("sectionTitle"); body.addWidget(title)
        header=QHBoxLayout()
        for label,width in [("Product",3),("Quantity",1),("Unit cost ₹",1),("Discount %",1),("Tax %",1),("",0)]:
            lbl=QLabel(label); lbl.setObjectName("muted"); header.addWidget(lbl,width)
        body.addLayout(header)
        self.lines_layout=QVBoxLayout(); self.lines_layout.setSpacing(7); body.addLayout(self.lines_layout)
        add=HoverButton("Add product line"); add.setIcon(svg_icon("plus",SUCCESS_ACCENT,15)); add.clicked.connect(self._add_line); body.addWidget(add,0,Qt.AlignmentFlag.AlignLeft)
        self.total_label=QLabel("Estimated total: ₹0.00"); self.total_label.setObjectName("sectionTitle"); body.addWidget(self.total_label)
        scroll.setWidget(inner); root.addWidget(scroll,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self._validate_and_accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)
        self.products=service.list_products(business_id)
        if document:
            _set_combo_data(self.supplier,str(document["supplier_id"])); self.document_date.setDate(QDate.fromString(str(document["order_date"] if is_order else document["purchase_date"]),"yyyy-MM-dd")); self.due_date.setDate(QDate.fromString(str(document["expected_date"] if is_order else document["due_date"] or date.today().isoformat()),"yyyy-MM-dd")); self.notes.setText(str(document.get("notes","")))
            if not is_order:
                self.supplier_invoice.setText(str(document.get("supplier_invoice_number",""))); _set_combo_data(self.source_po,str(document.get("source_purchase_order_id") or ""))
            for item in document.get("items",[]):self._add_line(item)
        else:self._add_line()
        if not is_order:
            linked_id = _value(self.source_po)
            self.supplier.currentIndexChanged.connect(self._filter_source_orders)
            self.source_po.currentIndexChanged.connect(self._load_selected_purchase_order)
            self._filter_source_orders(selected_id=linked_id)

    def _filter_source_orders(self, *_args, selected_id: str = ""):
        selected_id = selected_id or _value(self.source_po)
        supplier_id = _value(self.supplier)
        self.source_po.blockSignals(True)
        self.source_po.clear()
        self.source_po.addItem("No linked order — stock will be received on posting", "")
        for order in self.received_orders:
            if order["supplier_id"] == supplier_id:
                self.source_po.addItem(f"{order['order_number']} · {order['supplier_name']}", order["purchase_order_id"])
        _set_combo_data(self.source_po, selected_id)
        self.source_po.blockSignals(False)

    def _load_selected_purchase_order(self, *_args):
        order_id = _value(self.source_po)
        if not order_id:
            return
        order = self.service.get_purchase_order(self.business_id, order_id)
        if not order or order["status"] != "received":
            QMessageBox.warning(self, "Purchase order unavailable", "Only fully received purchase orders can be linked to a purchase bill.")
            return
        for line in self.line_rows:
            line["widget"].deleteLater()
        self.line_rows.clear()
        for item in order["items"]:
            if Decimal(str(item["received_quantity"])) <= 0:
                continue
            line_data = dict(item)
            line_data["quantity"] = item["received_quantity"]
            self._add_line(line_data)
        self._update_total()

    def _add_line(self,item:dict[str,Any]|None=None):
        row=QWidget(); layout=QHBoxLayout(row); layout.setContentsMargins(0,0,0,0); layout.setSpacing(6)
        product=QComboBox(); product.addItem("Select product…","")
        for p in self.products:product.addItem(f"{p['sku']} · {p['name']}",p["product_id"])
        qty=_spin(0.001,1_000_000_000,3,1); cost=_spin(0,1_000_000_000,2,0); discount=_spin(0,100,2,0); tax=_spin(0,100,2,0)
        remove=HoverButton("×"); remove.setFixedWidth(34); remove.setToolTip("Remove line")
        product.setMinimumWidth(270); qty.setMinimumWidth(95); cost.setMinimumWidth(110); discount.setMinimumWidth(92); tax.setMinimumWidth(82)
        for widget,stretch in [(product,3),(qty,1),(cost,1),(discount,1),(tax,1),(remove,0)]:layout.addWidget(widget,stretch)
        line={"widget":row,"product":product,"quantity":qty,"unit_cost":cost,"discount":discount,"tax":tax}
        self.line_rows.append(line); self.lines_layout.addWidget(row)
        product.currentIndexChanged.connect(lambda *_args,line=line:self._product_changed(line)); remove.clicked.connect(lambda _checked=False,line=line:self._remove_line(line))
        for widget in (qty,cost,discount,tax):widget.valueChanged.connect(self._update_total)
        if item:
            _set_combo_data(product,str(item.get("product_id",""))); qty.setValue(float(item.get("quantity",1))); cost.setValue(float(item.get("unit_cost",0))); discount.setValue(float(item.get("discount_percent",0))); tax.setValue(float(item.get("tax_rate",0)))
        elif product.count()>1:
            product.setCurrentIndex(1); self._product_changed(line)

    def _remove_line(self,line):
        if len(self.line_rows)<=1:return QMessageBox.information(self,"Keep one line","A purchase document needs at least one item line.")
        self.line_rows.remove(line); line["widget"].deleteLater(); self._update_total()

    def _product_changed(self,line):
        product=next((p for p in self.products if p["product_id"]==_value(line["product"])),None)
        if product:
            if line["unit_cost"].value()==0:line["unit_cost"].setValue(float(product["last_purchase_price"]))
            line["tax"].setValue(float(product["tax_rate"]))
        self._update_total()

    def _line_values(self):
        values=[]
        for line in self.line_rows:
            if not _value(line["product"]):continue
            values.append({"product_id":_value(line["product"]),"quantity":line["quantity"].value(),"unit_cost":line["unit_cost"].value(),"discount_percent":line["discount"].value(),"tax_rate":line["tax"].value()})
        return values

    def _update_total(self,*args):
        total=Decimal("0.00")
        for line in self.line_rows:
            if _value(line["product"]):
                base=Decimal(str(line["quantity"].value()))*Decimal(str(line["unit_cost"].value()))
                base-=base*Decimal(str(line["discount"].value()))/Decimal(100)
                total+=base+base*Decimal(str(line["tax"].value()))/Decimal(100)
        self.total_label.setText(f"Estimated total: ₹{total.quantize(Decimal('0.01')):,.2f}  ·  Final totals are recalculated by the validated service.")

    def _validate_and_accept(self):
        if not _value(self.supplier):return QMessageBox.warning(self,"Supplier required","Select an active supplier.")
        if not self._line_values():return QMessageBox.warning(self,"Items required","Add at least one product line.")
        if not self.document_date.date().isValid() or not self.due_date.date().isValid():return QMessageBox.warning(self,"Date required","Choose valid document dates.")
        if self.due_date.date()<self.document_date.date():return QMessageBox.warning(self,"Invalid dates","Expected/due date cannot be before the document date.")
        self.accept()

    def values(self):
        d={"supplier_id":_value(self.supplier),"document_date":self.document_date.date().toString("yyyy-MM-dd"),"due_date":self.due_date.date().toString("yyyy-MM-dd"),"notes":self.notes.text(),"items":self._line_values()}
        if self.document_type=="bill":d.update({"supplier_invoice_number":self.supplier_invoice.text(),"source_purchase_order_id":_value(self.source_po)})
        return d


class PurchaseOrderPage(QWidget):
    def __init__(self,database:Database,session:Session,navigate,parent=None):
        super().__init__(parent); self.database,self.session,self.navigate=database,session,navigate; self.service=InventoryService(database)
        root=QVBoxLayout(self); root.setContentsMargins(28,22,28,20); root.setSpacing(12)
        _header(root,"Purchasing / orders","Purchase orders","Prepare supplier orders, mark them ordered, receive stock fully or in parts, and preserve the received quantity history.","New purchase order",self._create)
        tools=QFrame(); tools.setObjectName("sectionToolbar"); tl=QHBoxLayout(tools); tl.setContentsMargins(10,7,10,7)
        self.search=make_line_edit("Search order or supplier…"); self.search.textChanged.connect(self.refresh); self.status=QComboBox(); self.status.addItems(["All","draft","ordered","partially_received","received","cancelled"]); self.status.currentTextChanged.connect(self.refresh); tl.addWidget(self.search,1); tl.addWidget(QLabel("Status")); tl.addWidget(self.status); ref=HoverButton("Refresh"); ref.clicked.connect(self.refresh); tl.addWidget(ref); root.addWidget(tools)
        frame=QFrame(); frame.setObjectName("contentCard"); box=QVBoxLayout(frame); box.setContentsMargins(10,10,10,10); self.table=_make_table(["PO number","Supplier","Order date","Expected","Status","Lines","Order total"]); self.table.itemSelectionChanged.connect(self._selection_changed); self.table.cellDoubleClicked.connect(lambda *_:self._details()); box.addWidget(self.table); self.empty=QLabel("No purchase orders match your filters."); self.empty.setObjectName("muted"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); box.addWidget(self.empty); root.addWidget(frame,1)
        actions=QHBoxLayout(); self.edit=HoverButton("Edit draft"); self.edit.clicked.connect(self._edit); self.order=HoverButton("Mark ordered"); self.order.setObjectName("primaryButton"); self.order.clicked.connect(self._order); self.receive=HoverButton("Receive stock"); self.receive.clicked.connect(self._receive); self.cancel=HoverButton("Cancel order"); self.cancel.clicked.connect(self._cancel); self.details=HoverButton("View details"); self.details.clicked.connect(self._details); bills=HoverButton("Purchase bills"); bills.clicked.connect(lambda:navigate("purchase_bills")); back=HoverButton("Purchasing home"); back.clicked.connect(lambda:navigate("purchasing"));
        for b in [self.edit,self.order,self.receive,self.cancel,self.details,bills,back]:actions.addWidget(b)
        actions.addStretch(1); root.addLayout(actions); self.refresh()

    def refresh(self,*args):
        self.rows=self.service.list_purchase_orders(self.session.business_id,self.search.text(),self.status.currentText()); self.table.setSortingEnabled(False); self.table.setRowCount(0)
        for r in self.rows:_put_row(self.table,[r["order_number"],r["supplier_name"],r["order_date"],r["expected_date"],r["status"].replace("_"," ").title(),r["line_count"],_money(r["grand_total"])],str(r["purchase_order_id"]),{5,6})
        self.table.setSortingEnabled(True); _set_table_empty(self.table,self.empty,len(self.rows)); self._selection_changed()

    def _selected(self):
        i=_selected_id(self.table); return self.service.get_purchase_order(self.session.business_id,i) if i else None
    def _selection_changed(self):
        r=self._selected(); status=r["status"] if r else ""; self.edit.setEnabled(status=="draft" and has_permission(self.session.role,"purchasing.create")); self.order.setEnabled(status=="draft" and has_permission(self.session.role,"purchasing.post")); self.receive.setEnabled(status in {"ordered","partially_received"} and has_permission(self.session.role,"purchasing.receive")); self.cancel.setEnabled(status in {"draft","ordered"} and has_permission(self.session.role,"purchasing.post") and not (r and any(Decimal(i["received_quantity"])>0 for i in r["items"]))); self.details.setEnabled(bool(r))
    def _dialog(self,doc=None):
        dialog=PurchaseDocumentDialog(self.service,self.session.business_id,"order",doc,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:
            if doc:self.service.update_purchase_order(self.session.business_id,self.session.user_id,doc["purchase_order_id"],dialog.values())
            else:self.service.create_purchase_order(self.session.business_id,self.session.user_id,dialog.values())
            self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Purchase order not saved",str(exc))
    def _create(self):self._dialog()
    def _edit(self):
        d=self._selected()
        if d:self._dialog(d)
    def _order(self):
        d=self._selected()
        if not d:return
        if QMessageBox.question(self,"Mark purchase order ordered",f"Mark {d['order_number']} as ordered? This starts the receiving lifecycle.")!=QMessageBox.StandardButton.Yes:return
        try:self.service.order_purchase_order(self.session.business_id,self.session.user_id,d["purchase_order_id"]);self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Cannot order",str(exc))
    def _receive(self):
        d=self._selected()
        if not d:return
        dialog=ReceivePurchaseDialog(d,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:
            generated_bill_id=self.service.receive_purchase_order(self.session.business_id,self.session.user_id,d["purchase_order_id"],dialog.receipts())
            self.refresh()
            if generated_bill_id:
                generated=self.service.get_purchase_bill(self.session.business_id,generated_bill_id)
                QMessageBox.information(self,"Stock received · Purchase bill generated",
                    f"Stock receipt is saved. KoshFlow created or updated draft purchase bill {generated['purchase_number']} automatically.\n\n"
                    "The draft follows received quantities, cannot be posted until the order is fully received, and does not add stock a second time. "
                    "Enter the supplier's invoice number and verify the supplier document before posting.")
            else:
                QMessageBox.information(self,"Stock receipt saved","Received quantities and stock movements were saved. The linked purchase bill is generated automatically when stock is received unless a bill already exists or was deliberately managed separately.")
        except InventoryError as exc:QMessageBox.warning(self,"Receipt rejected",str(exc))
    def _cancel(self):
        d=self._selected()
        if not d:return
        reason,ok=QInputDialog.getText(self,"Cancel purchase order","Reason (required):")
        if not ok:return
        try:self.service.cancel_purchase_order(self.session.business_id,self.session.user_id,d["purchase_order_id"],reason);self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Cannot cancel order",str(exc))
    def _details(self):
        d=self._selected()
        if not d:return
        lines="\n".join(f"• {x['sku']} · {x['product_name']} — ordered {x['quantity']} {x['unit']}, received {x['received_quantity']} {x['unit']}" for x in d["items"])
        QMessageBox.information(self,d["order_number"],f"Supplier: {d['supplier_name']}\nStatus: {d['status']}\nOrder total: {_money(d['grand_total'])}\n\n{lines}\n\n{d['notes']}")


class ReceivePurchaseDialog(QDialog):
    def __init__(self,order:dict[str,Any],parent=None):
        super().__init__(parent); self.order=order; self.widgets={}; self.setWindowTitle(f"Receive stock — {order['order_number']}"); self.setMinimumWidth(680); root=QVBoxLayout(self); title=QLabel("Enter the quantity received now. Leave other lines at zero; received quantities cannot exceed outstanding quantities."); title.setObjectName("muted"); title.setWordWrap(True); root.addWidget(title); table=QTableWidget(0,5); table.setHorizontalHeaderLabels(["Product","Ordered","Received","Remaining","Receive now"]); table.verticalHeader().setVisible(False); table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); table.setAlternatingRowColors(True); table.horizontalHeader().setStretchLastSection(True)
        for item in order["items"]:
            ordered=Decimal(item["quantity"]); received=Decimal(item["received_quantity"]); remaining=ordered-received; row=table.rowCount(); table.insertRow(row)
            for col,text in enumerate([f"{item['sku']} · {item['product_name']}",str(ordered),str(received),str(remaining)]):table.setItem(row,col,QTableWidgetItem(text))
            qty=_spin(0,float(remaining),3,0); table.setCellWidget(row,4,qty); self.widgets[item["purchase_order_item_id"]]=qty
        root.addWidget(table); buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)
    def receipts(self):return [{"purchase_order_item_id":key,"quantity":widget.value()} for key,widget in self.widgets.items() if widget.value()>0]
    def accept(self):
        if not self.receipts():QMessageBox.warning(self,"No quantity entered","Enter a positive received quantity for at least one line.");return
        super().accept()


class PurchaseBillPage(QWidget):
    def __init__(self,database:Database,session:Session,navigate,parent=None):
        super().__init__(parent); self.database,self.session,self.navigate=database,session,navigate; self.service=InventoryService(database)
        root=QVBoxLayout(self); root.setContentsMargins(28,22,28,20); root.setSpacing(12)
        _header(root,"Purchasing / supplier invoices","Purchase bills","Capture supplier invoices, post inventory receipts, track outstanding balances and use documented return credits.","New purchase bill",self._create)
        tools=QFrame(); tools.setObjectName("sectionToolbar"); tl=QHBoxLayout(tools); tl.setContentsMargins(10,7,10,7); self.search=make_line_edit("Search purchase number, supplier or invoice number…"); self.search.textChanged.connect(self.refresh); self.status=QComboBox(); self.status.addItems(["All","draft","posted","part_paid","paid","cancelled"]); self.status.currentTextChanged.connect(self.refresh); tl.addWidget(self.search,1);tl.addWidget(QLabel("Status"));tl.addWidget(self.status);ref=HoverButton("Refresh");ref.clicked.connect(self.refresh);tl.addWidget(ref);root.addWidget(tools)
        frame=QFrame();frame.setObjectName("contentCard");box=QVBoxLayout(frame);box.setContentsMargins(10,10,10,10);self.table=_make_table(["Purchase no.","Supplier","Supplier invoice","Date","Status","Total","Paid","Balance"]);self.table.itemSelectionChanged.connect(self._selection_changed);self.table.cellDoubleClicked.connect(lambda *_:self._details());box.addWidget(self.table);self.empty=QLabel("No purchase bills found. Capture your first supplier invoice to establish purchasing costs and payable balances.");self.empty.setObjectName("muted");self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);box.addWidget(self.empty);root.addWidget(frame,1)
        actions=QHBoxLayout();self.details=HoverButton("View details");self.details.clicked.connect(self._details);self.edit=HoverButton("Edit draft");self.edit.clicked.connect(self._edit);self.post=HoverButton("Post bill & stock");self.post.setObjectName("primaryButton");self.post.clicked.connect(self._post);self.pay=HoverButton("Record payment");self.pay.clicked.connect(self._pay);self.ret=HoverButton("Create supplier return");self.ret.clicked.connect(lambda:navigate("supplier_returns"));self.delete=HoverButton("Delete draft");self.delete.clicked.connect(self._delete);suppliers=HoverButton("Suppliers");suppliers.clicked.connect(lambda:navigate("suppliers"));back=HoverButton("Purchasing home");back.clicked.connect(lambda:navigate("purchasing"))
        for b in [self.details,self.edit,self.post,self.pay,self.ret,self.delete,suppliers,back]:actions.addWidget(b)
        actions.addStretch(1);root.addLayout(actions);self.refresh()
    def refresh(self,*args):
        self.rows=self.service.list_purchase_bills(self.session.business_id,self.search.text(),self.status.currentText());self.table.setSortingEnabled(False);self.table.setRowCount(0)
        for r in self.rows:_put_row(self.table,[r["purchase_number"],r["supplier_name"],r["supplier_invoice_number"],r["purchase_date"],r["status"].replace("_"," ").title(),_money(r["grand_total"]),_money(r["amount_paid"]),_money(r["balance_due"])],str(r["purchase_bill_id"]),{5,6,7})
        self.table.setSortingEnabled(True);_set_table_empty(self.table,self.empty,len(self.rows));self._selection_changed()
    def _selected(self):
        i=_selected_id(self.table);return self.service.get_purchase_bill(self.session.business_id,i) if i else None
    def _selection_changed(self):
        b=self._selected();s=b["status"] if b else "";self.details.setEnabled(bool(b));self.edit.setEnabled(s=="draft" and has_permission(self.session.role,"purchasing.create"));self.post.setEnabled(s=="draft" and has_permission(self.session.role,"purchasing.post"));self.pay.setEnabled(s in {"posted","part_paid"} and Decimal(str(b["balance_due"]))>0 and has_permission(self.session.role,"purchasing.pay"));self.ret.setEnabled(s in {"posted","part_paid","paid"} and has_permission(self.session.role,"purchasing.return"));self.delete.setEnabled(s=="draft" and has_permission(self.session.role,"purchasing.create"))
    def _dialog(self,bill=None):
        dialog=PurchaseDocumentDialog(self.service,self.session.business_id,"bill",bill,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:
            if bill:self.service.update_purchase_bill(self.session.business_id,self.session.user_id,bill["purchase_bill_id"],dialog.values())
            else:self.service.create_purchase_bill(self.session.business_id,self.session.user_id,dialog.values())
            self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Purchase bill not saved",str(exc))
    def _create(self):self._dialog()
    def _edit(self):
        b=self._selected()
        if b:self._dialog(b)
    def _post(self):
        b=self._selected()
        if not b:return
        phrase="post this purchase bill and update inventory?"
        if QMessageBox.question(self,"Post purchase bill",f"Are you sure you want to {phrase}\n\n{b['purchase_number']} · {_money(b['grand_total'])}")!=QMessageBox.StandardButton.Yes:return
        try:self.service.post_purchase_bill(self.session.business_id,self.session.user_id,b["purchase_bill_id"]);self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Purchase bill not posted",str(exc))
    def _pay(self):
        b=self._selected()
        if not b:return
        dialog=SupplierPaymentDialog(self.service,self.session.business_id,b,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.record_supplier_payment(self.session.business_id,self.session.user_id,b["purchase_bill_id"],dialog.amount.value(),dialog.method.currentText(),dialog.reference.text(),dialog.date.date().toString("yyyy-MM-dd"));self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Payment not saved",str(exc))
    def _delete(self):
        b=self._selected()
        if not b:return
        if QMessageBox.question(self,"Delete draft",f"Permanently delete unposted draft {b['purchase_number']}?")!=QMessageBox.StandardButton.Yes:return
        try:self.service.delete_purchase_bill_draft(self.session.business_id,self.session.user_id,b["purchase_bill_id"]);self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Draft not deleted",str(exc))
    def _details(self):
        b=self._selected()
        if not b:return
        lines="\n".join(f"• {x['sku']} · {x['product_name']} — {x['quantity']} {x['unit']} × {_money(x['unit_cost'])} = {_money(x['line_total'])}" for x in b["items"])
        pays="\n".join(f"• {p['paid_at']} · {p['payment_method']} · {_money(p['amount'])} {p['reference']}" for p in b["payments"]) or "No payments recorded."
        rets="\n".join(f"• {r['return_number']} · {r['status']} · {_money(r['grand_total'])}" for r in b["returns"]) or "No supplier returns recorded."
        QMessageBox.information(self,b["purchase_number"],f"Supplier: {b['supplier_name']}\nSupplier invoice: {b['supplier_invoice_number']}\nDate: {b['purchase_date']}\nStatus: {b['status']}\nSubtotal: {_money(b['subtotal'])}\nTax: {_money(b['tax_total'])}\nTotal: {_money(b['grand_total'])}\nPaid: {_money(b['amount_paid'])}\nBalance / credit: {_money(b['balance_due'])}\n\nITEMS\n{lines}\n\nPAYMENTS\n{pays}\n\nRETURNS\n{rets}\n\n{b['notes']}")


class SupplierPaymentDialog(QDialog):
    def __init__(self,service:InventoryService,business_id:str,bill:dict[str,Any]|None=None,parent=None):
        super().__init__(parent);self.setWindowTitle("Record supplier payment");self.setMinimumWidth(460);self.service=service;self.business_id=business_id
        root=QVBoxLayout(self);form=QFormLayout();form.setSpacing(10);self.bill=QComboBox();self.eligible=[b for b in service.list_purchase_bills(business_id) if b["status"] in {"posted","part_paid"} and Decimal(str(b["balance_due"]))>0]
        for b in self.eligible:self.bill.addItem(f"{b['purchase_number']} · {b['supplier_name']} · Due {_money(b['balance_due'])}",b["purchase_bill_id"])
        self.amount=_spin(0.01,1_000_000_000,2);self.method=QComboBox();self.method.addItems(["Bank transfer","UPI","Cash","Card","Cheque","Other"]);self.reference=make_line_edit("UTR / cheque / reference");self.date=QDateEdit();self.date.setCalendarPopup(True);self.date.setDate(QDate.currentDate());self.date.setDisplayFormat("dd MMM yyyy")
        form.addRow("Purchase bill *",self.bill);form.addRow("Amount (₹) *",self.amount);form.addRow("Method",self.method);form.addRow("Reference",self.reference);form.addRow("Payment date",self.date);root.addLayout(form)
        if bill:_set_combo_data(self.bill,str(bill["purchase_bill_id"]));self.amount.setMaximum(max(0.01,float(bill["balance_due"])))
        self.bill.currentIndexChanged.connect(self._update_max);self._update_max()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self._accept);buttons.rejected.connect(self.reject);root.addWidget(buttons)
    def _update_max(self):
        row=next((b for b in self.eligible if b["purchase_bill_id"]==_value(self.bill)),None)
        if row:self.amount.setMaximum(max(0.01,float(row["balance_due"])))
    def _accept(self):
        if not _value(self.bill):return QMessageBox.warning(self,"Bill required","Create and post a purchase bill before recording payment.")
        if self.amount.value()<=0:return QMessageBox.warning(self,"Amount required","Payment must be greater than zero.")
        super().accept()


class SupplierPaymentsPage(QWidget):
    def __init__(self,database:Database,session:Session,navigate,parent=None):
        super().__init__(parent);self.database,self.session,self.navigate=database,session,navigate;self.service=InventoryService(database)
        root=QVBoxLayout(self);root.setContentsMargins(28,22,28,20);root.setSpacing(13);_header(root,"Purchasing / payments","Supplier payments","Record and review payments made against posted purchase bills.","Record payment",self._record)
        tools=QFrame();tools.setObjectName("sectionToolbar");tl=QHBoxLayout(tools);tl.setContentsMargins(10,7,10,7);self.search=make_line_edit("Search supplier, purchase no. or payment reference…");self.search.textChanged.connect(self.refresh);export=HoverButton("Export CSV");export.clicked.connect(self._export);refresh=HoverButton("Refresh");refresh.clicked.connect(self.refresh);tl.addWidget(self.search,1);tl.addWidget(export);tl.addWidget(refresh);root.addWidget(tools)
        frame=QFrame();frame.setObjectName("contentCard");box=QVBoxLayout(frame);box.setContentsMargins(10,10,10,10);self.table=_make_table(["Date","Supplier","Purchase bill","Method","Reference","Amount"]);box.addWidget(self.table);self.empty=QLabel("No supplier payments recorded yet.");self.empty.setObjectName("muted");self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);box.addWidget(self.empty);root.addWidget(frame,1);back=HoverButton("Purchasing home");back.clicked.connect(lambda:navigate("purchasing"));root.addWidget(back,0,Qt.AlignmentFlag.AlignLeft);self.refresh()
    def refresh(self,*args):
        self.rows=self.service.list_supplier_payments(self.session.business_id,self.search.text());self.table.setSortingEnabled(False);self.table.setRowCount(0)
        for r in self.rows:_put_row(self.table,[r["paid_at"],r["supplier_name"],r["purchase_number"],r["payment_method"],r["reference"],_money(r["amount"])],str(r["supplier_payment_id"]),{5})
        self.table.setSortingEnabled(True);_set_table_empty(self.table,self.empty,len(self.rows))
    def _record(self):
        if not has_permission(self.session.role,"purchasing.pay"):return QMessageBox.warning(self,"Permission required","Your role cannot record supplier payments.")
        dialog=SupplierPaymentDialog(self.service,self.session.business_id,parent=self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.record_supplier_payment(self.session.business_id,self.session.user_id,_value(dialog.bill),dialog.amount.value(),dialog.method.currentText(),dialog.reference.text(),dialog.date.date().toString("yyyy-MM-dd"));self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Payment not saved",str(exc))
    def _export(self):_export_csv(self,"koshflow-supplier-payments.csv",["Date","Supplier","Purchase bill","Method","Reference","Amount"],[[r["paid_at"],r["supplier_name"],r["purchase_number"],r["payment_method"],r["reference"],r["amount"]] for r in self.rows])


class SupplierReturnsPage(QWidget):
    def __init__(self,database:Database,session:Session,navigate,parent=None):
        super().__init__(parent);self.database,self.session,self.navigate=database,session,navigate;self.service=InventoryService(database)
        root=QVBoxLayout(self);root.setContentsMargins(28,22,28,20);root.setSpacing(13);_header(root,"Purchasing / supplier credits","Supplier returns","Record returned goods against a posted supplier bill. Posting reduces stock and credits the supplier account.","Create return",self._create)
        tools=QFrame();tools.setObjectName("sectionToolbar");tl=QHBoxLayout(tools);tl.setContentsMargins(10,7,10,7);self.search=make_line_edit("Search return, supplier or purchase number…");self.search.textChanged.connect(self.refresh);self.status=QComboBox();self.status.addItems(["All","draft","posted","cancelled"]);self.status.currentTextChanged.connect(self.refresh);tl.addWidget(self.search,1);tl.addWidget(QLabel("Status"));tl.addWidget(self.status);rf=HoverButton("Refresh");rf.clicked.connect(self.refresh);tl.addWidget(rf);root.addWidget(tools)
        frame=QFrame();frame.setObjectName("contentCard");box=QVBoxLayout(frame);box.setContentsMargins(10,10,10,10);self.table=_make_table(["Return no.","Supplier","Purchase bill","Date","Status","Reason","Credit total"]);self.table.itemSelectionChanged.connect(self._selection_changed);box.addWidget(self.table);self.empty=QLabel("No supplier returns found.");self.empty.setObjectName("muted");self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);box.addWidget(self.empty);root.addWidget(frame,1)
        actions=QHBoxLayout();self.post=HoverButton("Post return & update stock");self.post.setObjectName("primaryButton");self.post.clicked.connect(self._post);self.cancel=HoverButton("Cancel draft");self.cancel.clicked.connect(self._cancel);bills=HoverButton("Purchase bills");bills.clicked.connect(lambda:navigate("purchase_bills"));back=HoverButton("Purchasing home");back.clicked.connect(lambda:navigate("purchasing"));
        for b in [self.post,self.cancel,bills,back]:actions.addWidget(b)
        actions.addStretch(1);root.addLayout(actions);self.refresh()
    def refresh(self,*args):
        self.rows=self.service.list_supplier_returns(self.session.business_id,self.search.text(),self.status.currentText());self.table.setSortingEnabled(False);self.table.setRowCount(0)
        for r in self.rows:_put_row(self.table,[r["return_number"],r["supplier_name"],r["purchase_number"],r["return_date"],r["status"].title(),r["reason"],_money(r["grand_total"])],str(r["supplier_return_id"]),{6})
        self.table.setSortingEnabled(True);_set_table_empty(self.table,self.empty,len(self.rows));self._selection_changed()
    def _selected(self):
        identifier=_selected_id(self.table);return next((r for r in self.rows if r["supplier_return_id"]==identifier),None)
    def _selection_changed(self):
        r=self._selected();draft=bool(r and r["status"]=="draft");p=has_permission(self.session.role,"purchasing.return");self.post.setEnabled(draft and p);self.cancel.setEnabled(draft and p)
    def _create(self):
        if not has_permission(self.session.role,"purchasing.return"):return QMessageBox.warning(self,"Permission required","Your role cannot create supplier returns.")
        dialog=SupplierReturnDialog(self.service,self.session.business_id,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.create_supplier_return(self.session.business_id,self.session.user_id,dialog.purchase_bill_id,dialog.purchase_item_id,dialog.quantity.value(),dialog.reason.toPlainText(),dialog.date.date().toString("yyyy-MM-dd"));self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Return not saved",str(exc))
    def _post(self):
        r=self._selected()
        if not r:return
        if QMessageBox.question(self,"Post supplier return",f"Post {r['return_number']} and reduce stock by the returned quantity?")!=QMessageBox.StandardButton.Yes:return
        try:self.service.post_supplier_return(self.session.business_id,self.session.user_id,r["supplier_return_id"]);self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Return not posted",str(exc))
    def _cancel(self):
        r=self._selected()
        if not r:return
        try:self.service.cancel_supplier_return_draft(self.session.business_id,self.session.user_id,r["supplier_return_id"]);self.refresh()
        except InventoryError as exc:QMessageBox.warning(self,"Return not cancelled",str(exc))


class SupplierReturnDialog(QDialog):
    def __init__(self,service:InventoryService,business_id:str,parent=None):
        super().__init__(parent);self.service,self.business_id=service,business_id;self.purchase_bill_id="";self.purchase_item_id="";self.setWindowTitle("Create supplier return");self.setMinimumWidth(550);root=QVBoxLayout(self);form=QFormLayout();form.setSpacing(11)
        self.bill=QComboBox();self.bills=[b for b in service.list_purchase_bills(business_id) if b["status"] in {"posted","part_paid","paid"}]
        for bill in self.bills:self.bill.addItem(f"{bill['purchase_number']} · {bill['supplier_name']}",bill["purchase_bill_id"])
        self.item=QComboBox();self.quantity=_spin(0.001,1_000_000_000,3,1);self.reason=QTextEdit();self.reason.setMaximumHeight(90);self.reason.setPlaceholderText("Required reason for return");self.date=QDateEdit();self.date.setCalendarPopup(True);self.date.setDate(QDate.currentDate());self.date.setDisplayFormat("dd MMM yyyy")
        form.addRow("Posted purchase bill *",self.bill);form.addRow("Item *",self.item);form.addRow("Return quantity *",self.quantity);form.addRow("Reason *",self.reason);form.addRow("Return date",self.date);root.addLayout(form);self.bill.currentIndexChanged.connect(self._load_items);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self._accept);buttons.rejected.connect(self.reject);root.addWidget(buttons);self._load_items()
    def _load_items(self):
        self.item.clear();bill_id=_value(self.bill);bill=self.service.get_purchase_bill(self.business_id,bill_id) if bill_id else None
        if bill:
            for item in bill["items"]:self.item.addItem(f"{item['sku']} · {item['product_name']} — {item['quantity']} {item['unit']}",item["purchase_item_id"])
    def _accept(self):
        if not _value(self.bill):return QMessageBox.warning(self,"Purchase bill required","Select a posted purchase bill first.")
        if not _value(self.item):return QMessageBox.warning(self,"Item required","Select a purchased item to return.")
        if not self.reason.toPlainText().strip():return QMessageBox.warning(self,"Reason required","Enter a reason for the return.")
        self.purchase_bill_id=_value(self.bill);self.purchase_item_id=_value(self.item);super().accept()


class InventoryReportsPage(QWidget):
    def __init__(self, database: Database, session: Session, navigate, parent=None,
                 initial_report: str = "Stock valuation"):
        super().__init__(parent)
        self.database = database
        self.session = session
        self.navigate = navigate
        self.service = InventoryService(database)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(13)
        _header(
            root,
            "Inventory / analytics",
            "Stock valuation & reports",
            "Review live quantity, moving-average cost, reorder risk and supplier balances. "
            "Export the current report for reconciliation.",
        )

        self.metrics = QGridLayout()
        self.metrics.setSpacing(12)
        root.addLayout(self.metrics)

        tools = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(["Stock valuation", "Low stock", "Purchasing summary", "Purchase orders"])
        self.kind.setCurrentText(initial_report)
        self.kind.currentTextChanged.connect(self.refresh)
        tools.addWidget(QLabel("Report"))
        tools.addWidget(self.kind)
        tools.addStretch(1)
        export = HoverButton("Export current report")
        export.clicked.connect(self._export)
        movements = HoverButton("Movement ledger")
        movements.clicked.connect(lambda: navigate("stock_movements"))
        tools.addWidget(export)
        tools.addWidget(movements)
        root.addLayout(tools)

        frame = QFrame()
        frame.setObjectName("contentCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(10, 10, 10, 10)
        self.table = _make_table(["SKU", "Product", "Category", "On hand", "Average cost", "Stock value", "Reorder at", "Status"])
        box.addWidget(self.table)
        self.empty = QLabel("No records are available for this report.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty)
        root.addWidget(frame, 1)

        back = HoverButton("Inventory home")
        back.clicked.connect(lambda: navigate("inventory"))
        root.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        self.refresh()

    def refresh(self, *args):
        while self.metrics.count():
            item = self.metrics.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        inventory = self.service.inventory_summary(self.session.business_id)
        purchasing = self.service.purchasing_summary(self.session.business_id)
        metric_specs = [
            ("Products", str(inventory["product_count"]), "package"),
            ("Stock valuation", _money(inventory["valuation"]), "wallet"),
            ("Low stock", str(inventory["low_stock_count"]), "alert-triangle"),
            ("Supplier payables", _money(purchasing["supplier_payables"]), "truck"),
            ("Supplier credits", _money(purchasing["supplier_credits"]), "badge-check"),
        ]
        for column, (label, value, icon) in enumerate(metric_specs):
            self.metrics.addWidget(MetricCard(label, value, icon), 0, column)

        mode = self.kind.currentText()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        if mode == "Purchasing summary":
            rows = self.service.list_suppliers(self.session.business_id, active_only=False)
            self.table.setColumnCount(6)
            self.table.setHorizontalHeaderLabels(["Supplier code", "Supplier", "Status", "Terms", "Payable", "Credit"])
            for supplier in rows:
                balance = Decimal(str(supplier["outstanding_balance"]))
                payable = _money(balance) if balance > 0 else "—"
                credit = _money(abs(balance)) if balance < 0 else "—"
                _put_row(
                    self.table,
                    [supplier["supplier_code"], supplier["name"],
                     "Active" if supplier["is_active"] else "Archived",
                     f"{supplier['payment_terms_days']} days", payable, credit],
                    str(supplier["supplier_id"]), {3, 4, 5},
                )
            count = len(rows)
            empty_text = "No supplier balances are recorded yet."
        elif mode == "Purchase orders":
            rows = self.service.list_purchase_orders(self.session.business_id)
            self.table.setColumnCount(6)
            self.table.setHorizontalHeaderLabels(["Order", "Supplier", "Date", "Status", "Lines", "Total"])
            for order in rows:
                _put_row(
                    self.table,
                    [order["order_number"], order["supplier_name"], order["order_date"],
                     order["status"].replace("_", " ").title(), order["line_count"], _money(order["grand_total"])],
                    str(order["purchase_order_id"]), {4, 5},
                )
            count = len(rows)
            empty_text = "No purchase orders have been created yet."
        else:
            low_stock_only = mode == "Low stock"
            products = self.service.list_products(self.session.business_id, low_stock_only=low_stock_only)
            self.table.setColumnCount(8)
            self.table.setHorizontalHeaderLabels(["SKU", "Product", "Category", "On hand", "Average cost", "Stock value", "Reorder at", "Status"])
            for product in products:
                quantity = Decimal(str(product["quantity_on_hand"]))
                average_cost = Decimal(str(product["average_cost"]))
                reorder = Decimal(str(product["reorder_level"]))
                value = quantity * average_cost
                status = "LOW STOCK" if reorder > 0 and quantity <= reorder else "Healthy"
                _put_row(
                    self.table,
                    [product["sku"], product["name"], product["category"], product["quantity_on_hand"],
                     _money(average_cost), _money(value), product["reorder_level"], status],
                    str(product["product_id"]), {3, 4, 5, 6},
                )
            count = len(products)
            empty_text = (
                "No products are currently below their reorder thresholds."
                if low_stock_only else "No product records are available for stock valuation."
            )

        self.table.setSortingEnabled(True)
        self.empty.setText(empty_text)
        _set_table_empty(self.table, self.empty, count)

    def _export(self):
        data = []
        for row in range(self.table.rowCount()):
            data.append([
                self.table.item(row, column).text() if self.table.item(row, column) else ""
                for column in range(self.table.columnCount())
            ])
        headers = [self.table.horizontalHeaderItem(index).text() for index in range(self.table.columnCount())]
        _export_csv(self, "koshflow-inventory-report.csv", headers, data)
