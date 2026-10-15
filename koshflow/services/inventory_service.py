"""Inventory and purchasing domain service.

Purpose: Provide business-scoped product/supplier CRUD, purchase order receiving,
         purchase bill posting, supplier payments/returns, stock ledger and reports.
Project: KoshFlow | Version: 0.6.0
Canonical path: koshflow/services/inventory_service.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Use InventoryService(Database) from inventory/purchasing UI pages.
Changelog: v0.6.0 — Integrated inventory receipts, adjustments, purchasing, supplier payment and return postings with the ledger.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import StringIO
from typing import Any

from koshflow.core.database import Database
from koshflow.services.accounting_service import AccountingService
from koshflow.core.permissions import has_permission
from koshflow.core.security import new_id, normalize_gstin, validate_gstin

MONEY = Decimal("0.01")
QUANTITY = Decimal("0.001")
ZERO = Decimal("0.00")
QZERO = Decimal("0.000")
PAYMENT_METHODS = {"Cash", "UPI", "Bank transfer", "Card", "Cheque", "Other"}


class InventoryError(ValueError):
    """Expected inventory/purchasing validation error safe to display in the UI."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decimal(value: Any, label: str, *, minimum: Decimal = ZERO, allow_negative: bool = False) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InventoryError(f"{label} must be a valid number.") from exc
    if not result.is_finite():
        raise InventoryError(f"{label} must be a finite number.")
    if not allow_negative and result < minimum:
        raise InventoryError(f"{label} cannot be negative or below {minimum}.")
    return result


def _quantize(value: Decimal, quantum: Decimal, label: str | None = None) -> Decimal:
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    if label and rounded != value:
        raise InventoryError(f"{label} supports at most {3 if quantum == QUANTITY else 2} decimal places.")
    return rounded


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _money_text(value: Decimal) -> str:
    return f"{_money(value):.2f}"


def _qty(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY, rounding=ROUND_HALF_UP)


def _qty_text(value: Decimal) -> str:
    return f"{_qty(value):.3f}"


def _date(value: Any, label: str, *, optional: bool = False) -> str:
    text = str(value or "").strip()
    if not text and optional:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise InventoryError(f"{label} must use YYYY-MM-DD format.") from exc


class InventoryService:
    """All inventory/purchasing writes are validated and committed atomically."""

    def __init__(self, database: Database):
        self.database = database

    # ---------- Product catalog ----------
    def create_product(self, business_id: str, actor_user_id: str, values: dict[str, Any]) -> str:
        data = self._validate_product(values)
        opening = data.pop("opening_quantity")
        now = _now()
        product_id = new_id("PRD")
        try:
            with self.database.transaction() as conn:
                self._assert_actor(conn, business_id, actor_user_id, "inventory.manage")
                if not data["sku"]:
                    data["sku"] = self._next_sku(conn, business_id)
                conn.execute(
                    "INSERT INTO products(product_id,business_id,sku,barcode,name,description,category,hsn_code,unit,"
                    "last_purchase_price,average_cost,selling_price,tax_rate,reorder_level,quantity_on_hand,is_active,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (product_id, business_id, data["sku"], data["barcode"], data["name"], data["description"],
                     data["category"], data["hsn_code"], data["unit"], _money_text(data["purchase_price"]),
                     _money_text(data["purchase_price"]), _money_text(data["selling_price"]),
                     _money_text(data["tax_rate"]), _qty_text(data["reorder_level"]), "0.000", now, now),
                )
                if opening > 0:
                    self._apply_stock_change(
                        conn, business_id, product_id, opening, data["purchase_price"], "opening", "product", product_id,
                        "Opening stock", actor_user_id, now,
                    )
                self._audit(conn, business_id, actor_user_id, "inventory.product.created", "product", product_id,
                            {"sku": data["sku"], "name": data["name"], "opening_quantity": _qty_text(opening)}, now)
        except Exception as exc:
            self._translate_integrity(exc, "A product with this SKU or barcode already exists in this business.")
        return product_id

    def update_product(self, business_id: str, actor_user_id: str, product_id: str, values: dict[str, Any]) -> None:
        data = self._validate_product(values, include_opening=False)
        now = _now()
        try:
            with self.database.transaction() as conn:
                self._assert_actor(conn, business_id, actor_user_id, "inventory.manage")
                old = conn.execute("SELECT * FROM products WHERE business_id=? AND product_id=?", (business_id, product_id)).fetchone()
                if not old:
                    raise InventoryError("Product not found in this business.")
                if not data["sku"]:
                    data["sku"] = str(old["sku"])
                sku_changed = str(old["sku"]).casefold() != data["sku"].casefold()
                unit_changed = str(old["unit"]).casefold() != data["unit"].casefold()
                if sku_changed or unit_changed:
                    has_history = conn.execute(
                        "SELECT 1 FROM stock_movements WHERE product_id=? "
                        "UNION ALL SELECT 1 FROM purchase_order_items WHERE product_id=? "
                        "UNION ALL SELECT 1 FROM purchase_items WHERE product_id=? "
                        "UNION ALL SELECT 1 FROM bill_items WHERE product_id=? LIMIT 1",
                        (product_id, product_id, product_id, product_id),
                    ).fetchone()
                    if has_history or _decimal(old["quantity_on_hand"], "Current stock") != ZERO:
                        fields = "unit or SKU" if sku_changed and unit_changed else "unit" if unit_changed else "SKU"
                        raise InventoryError(
                            f"The {fields} cannot be changed after stock or document history exists. "
                            "Create a new catalog product and use a documented stock adjustment instead."
                        )
                conn.execute(
                    "UPDATE products SET sku=?,barcode=?,name=?,description=?,category=?,hsn_code=?,unit=?,last_purchase_price=?,"
                    "selling_price=?,tax_rate=?,reorder_level=?,updated_at=? WHERE business_id=? AND product_id=?",
                    (data["sku"], data["barcode"], data["name"], data["description"], data["category"], data["hsn_code"],
                     data["unit"], _money_text(data["purchase_price"]), _money_text(data["selling_price"]),
                     _money_text(data["tax_rate"]), _qty_text(data["reorder_level"]), now, business_id, product_id),
                )
                # With zero stock, the newly entered purchase price is also a sensible opening cost basis.
                if _decimal(old["quantity_on_hand"], "Current stock") == 0:
                    conn.execute("UPDATE products SET average_cost=? WHERE business_id=? AND product_id=?",
                                 (_money_text(data["purchase_price"]), business_id, product_id))
                self._audit(conn, business_id, actor_user_id, "inventory.product.updated", "product", product_id,
                            {"sku": data["sku"], "name": data["name"]}, now)
        except Exception as exc:
            self._translate_integrity(exc, "A product with this SKU or barcode already exists in this business.")

    def archive_product(self, business_id: str, actor_user_id: str, product_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "inventory.manage")
            product = conn.execute("SELECT quantity_on_hand FROM products WHERE business_id=? AND product_id=?", (business_id, product_id)).fetchone()
            if not product:
                raise InventoryError("Product not found in this business.")
            if _decimal(product["quantity_on_hand"], "Current stock") != ZERO:
                raise InventoryError("A product with stock on hand cannot be archived. Adjust or sell the stock first.")
            open_purchase_order = conn.execute(
                "SELECT poi.quantity,poi.received_quantity FROM purchase_order_items poi "
                "JOIN purchase_orders po ON po.purchase_order_id=poi.purchase_order_id "
                "WHERE poi.product_id=? AND po.business_id=? AND po.status IN ('draft','ordered','partially_received')",
                (product_id, business_id),
            ).fetchall()
            if any(_decimal(row["quantity"], "Ordered quantity") > _decimal(row["received_quantity"], "Received quantity") for row in open_purchase_order):
                raise InventoryError("This product belongs to an open purchase order and cannot be archived yet.")
            open_purchase_bill = conn.execute(
                "SELECT 1 FROM purchase_items pi JOIN purchase_bills pb ON pb.purchase_bill_id=pi.purchase_bill_id "
                "WHERE pi.product_id=? AND pb.business_id=? AND pb.status='draft' LIMIT 1",
                (product_id, business_id),
            ).fetchone()
            open_sales_bill = conn.execute(
                "SELECT 1 FROM bill_items bi JOIN bills b ON b.bill_id=bi.bill_id "
                "WHERE bi.product_id=? AND b.business_id=? AND b.status='draft' LIMIT 1",
                (product_id, business_id),
            ).fetchone()
            draft_return = conn.execute(
                "SELECT 1 FROM supplier_return_items sri JOIN supplier_returns sr ON sr.supplier_return_id=sri.supplier_return_id "
                "WHERE sri.product_id=? AND sr.business_id=? AND sr.status='draft' LIMIT 1",
                (product_id, business_id),
            ).fetchone()
            unbilled_received_order = conn.execute(
                "SELECT 1 FROM purchase_order_items poi JOIN purchase_orders po ON po.purchase_order_id=poi.purchase_order_id "
                "WHERE poi.product_id=? AND po.business_id=? AND po.status='received' "
                "AND NOT EXISTS(SELECT 1 FROM purchase_bills pb WHERE pb.source_purchase_order_id=po.purchase_order_id) LIMIT 1",
                (product_id, business_id),
            ).fetchone()
            if open_purchase_bill or open_sales_bill or draft_return or unbilled_received_order:
                raise InventoryError("This product is referenced by an unposted bill, return, or unbilled receipt and cannot be archived yet.")
            conn.execute("UPDATE products SET is_active=0,updated_at=? WHERE business_id=? AND product_id=?", (now, business_id, product_id))
            self._audit(conn, business_id, actor_user_id, "inventory.product.archived", "product", product_id, {}, now)

    def get_product(self, business_id: str, product_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM products WHERE business_id=? AND product_id=?", (business_id, product_id)).fetchone()
        return dict(row) if row else None

    def list_products(self, business_id: str, search: str = "", category: str = "All", *,
                      active_only: bool = True, low_stock_only: bool = False) -> list[dict[str, Any]]:
        clauses = ["business_id=?"]
        params: list[Any] = [business_id]
        if active_only:
            clauses.append("is_active=1")
        if search.strip():
            pattern = f"%{search.strip()}%"
            clauses.append("(name LIKE ? OR sku LIKE ? OR barcode LIKE ? OR hsn_code LIKE ?)")
            params.extend([pattern] * 4)
        if category and category != "All":
            clauses.append("category=?")
            params.append(category)
        if low_stock_only:
            clauses.append("CAST(quantity_on_hand AS REAL) <= CAST(reorder_level AS REAL) AND CAST(reorder_level AS REAL) > 0")
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM products WHERE {' AND '.join(clauses)} ORDER BY name COLLATE NOCASE", params
            ).fetchall()
        return [dict(row) for row in rows]

    def product_categories(self, business_id: str) -> list[str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT DISTINCT category FROM products WHERE business_id=? AND is_active=1 ORDER BY category COLLATE NOCASE", (business_id,)).fetchall()
        return [str(row[0]) for row in rows]

    def next_sku(self, business_id: str) -> str:
        with self.database.connection() as conn:
            return self._next_sku(conn, business_id)

    @staticmethod
    def _next_sku(conn, business_id: str) -> str:
        rows = conn.execute("SELECT sku FROM products WHERE business_id=?", (business_id,)).fetchall()
        highest = 0
        for row in rows:
            match = re.fullmatch(r"SKU-(\d+)", str(row["sku"] or ""), re.I)
            if match:
                highest = max(highest, int(match.group(1)))
        candidate = highest + 1
        existing = {str(row["sku"]).casefold() for row in rows}
        while f"SKU-{candidate:06d}".casefold() in existing:
            candidate += 1
        return f"SKU-{candidate:06d}"

    @staticmethod
    def suggest_hsn_code(name: str, category: str = "") -> dict[str, str] | None:
        """Return a conservative HSN candidate; users must verify classification before invoicing.

        These are assistive catalog suggestions, not a tax/legal classification service.
        Tax rates are never inferred from HSN. The catalog owner must confirm the suggested code.
        """
        text = f"{name or ''} {category or ''}".casefold()
        rules = [
            (("laptop", "desktop computer", "computer", "workstation", "server"), "8471", "Automatic data-processing machines; verify exact product scope."),
            (("mobile phone", "smartphone", "cell phone", "telephone handset"), "8517", "Telephone apparatus; verify exact product scope."),
            (("printer", "multifunction printer"), "8443", "Printing machinery; verify product type."),
            (("notebook", "exercise book", "register"), "4820", "Notebooks, registers and similar stationery; verify exact paper product."),
            (("printed book", "book"), "4901", "Printed books and similar printed matter; verify exact product."),
            (("rice", "paddy"), "1006", "Rice; verify whether husked, milled or otherwise processed."),
            (("wheat",), "1001", "Wheat and meslin; verify exact goods."),
            (("tea leaves", "tea powder", "green tea", "black tea"), "0902", "Tea; verify preparation and packaging details."),
            (("coffee bean", "ground coffee", "instant coffee"), "0901", "Coffee; verify processing and preparation."),
            (("pasta", "macaroni", "noodles"), "1902", "Pasta and similar products; verify exact composition."),
            (("soap", "toilet soap"), "3401", "Soap and organic surface-active products; verify formulation."),
            (("detergent", "washing powder", "laundry liquid"), "3402", "Cleaning preparations; verify composition and use."),
            (("cosmetic", "face cream", "lipstick", "makeup", "moisturizer"), "3304", "Beauty or make-up preparations; verify exact preparation."),
            (("furniture", "chair", "desk", "table", "cabinet"), "9403", "Other furniture and parts; verify material and intended use."),
            (("footwear", "shoe", "sandal", "slipper"), "6403", "Footwear candidate only; material and construction can change classification."),
            (("t-shirt", "tee shirt", "knitted shirt"), "6109", "Knitted or crocheted T-shirts and similar garments; verify fibre/type."),
            (("plastic household", "plastic container", "plastic box"), "3924", "Plastic household/tableware articles candidate; verify exact article."),
        ]
        for keywords, code, reason in rules:
            if any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords):
                return {"code": code, "reason": reason, "verified": "false"}
        return None

    # ---------- Supplier directory ----------
    def create_supplier(self, business_id: str, actor_user_id: str, values: dict[str, Any]) -> str:
        data = self._validate_supplier(values)
        supplier_id = new_id("SUP")
        now = _now()
        try:
            with self.database.transaction() as conn:
                self._assert_actor(conn, business_id, actor_user_id, "purchasing.manage_suppliers")
                conn.execute(
                    "INSERT INTO suppliers(supplier_id,business_id,supplier_code,name,contact_person,phone,email,gstin,pan,address,city,state,pincode,payment_terms_days,notes,is_active,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (supplier_id, business_id, data["supplier_code"], data["name"], data["contact_person"], data["phone"],
                     data["email"], data["gstin"], data["pan"], data["address"], data["city"], data["state"], data["pincode"],
                     data["payment_terms_days"], data["notes"], now, now),
                )
                self._audit(conn, business_id, actor_user_id, "purchasing.supplier.created", "supplier", supplier_id,
                            {"supplier_code": data["supplier_code"], "name": data["name"]}, now)
        except Exception as exc:
            self._translate_integrity(exc, "A supplier with this code already exists in this business.")
        return supplier_id

    def update_supplier(self, business_id: str, actor_user_id: str, supplier_id: str, values: dict[str, Any]) -> None:
        data = self._validate_supplier(values)
        now = _now()
        try:
            with self.database.transaction() as conn:
                self._assert_actor(conn, business_id, actor_user_id, "purchasing.manage_suppliers")
                found = conn.execute("SELECT 1 FROM suppliers WHERE business_id=? AND supplier_id=?", (business_id, supplier_id)).fetchone()
                if not found:
                    raise InventoryError("Supplier not found in this business.")
                conn.execute(
                    "UPDATE suppliers SET supplier_code=?,name=?,contact_person=?,phone=?,email=?,gstin=?,pan=?,address=?,city=?,state=?,pincode=?,payment_terms_days=?,notes=?,updated_at=? "
                    "WHERE business_id=? AND supplier_id=?",
                    (data["supplier_code"], data["name"], data["contact_person"], data["phone"], data["email"], data["gstin"],
                     data["pan"], data["address"], data["city"], data["state"], data["pincode"], data["payment_terms_days"],
                     data["notes"], now, business_id, supplier_id),
                )
                self._audit(conn, business_id, actor_user_id, "purchasing.supplier.updated", "supplier", supplier_id,
                            {"supplier_code": data["supplier_code"], "name": data["name"]}, now)
        except Exception as exc:
            self._translate_integrity(exc, "A supplier with this code already exists in this business.")

    def archive_supplier(self, business_id: str, actor_user_id: str, supplier_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.manage_suppliers")
            supplier = conn.execute("SELECT 1 FROM suppliers WHERE business_id=? AND supplier_id=?", (business_id, supplier_id)).fetchone()
            if not supplier:
                raise InventoryError("Supplier not found in this business.")
            open_balance = self._supplier_balance(conn, business_id, supplier_id)
            if open_balance != ZERO:
                balance_label = "outstanding payable" if open_balance > ZERO else "unused supplier credit"
                raise InventoryError(f"This supplier has an {balance_label} balance and cannot be archived yet.")
            open_order = conn.execute(
                "SELECT 1 FROM purchase_orders WHERE business_id=? AND supplier_id=? AND status IN ('draft','ordered','partially_received') LIMIT 1",
                (business_id, supplier_id),
            ).fetchone()
            open_bill = conn.execute(
                "SELECT 1 FROM purchase_bills WHERE business_id=? AND supplier_id=? AND status='draft' LIMIT 1",
                (business_id, supplier_id),
            ).fetchone()
            unbilled_receipt = conn.execute(
                "SELECT 1 FROM purchase_orders po WHERE po.business_id=? AND po.supplier_id=? AND po.status='received' "
                "AND NOT EXISTS (SELECT 1 FROM purchase_bills pb WHERE pb.source_purchase_order_id=po.purchase_order_id) LIMIT 1",
                (business_id, supplier_id),
            ).fetchone()
            if open_order or open_bill or unbilled_receipt:
                raise InventoryError("This supplier has an open purchase order, unbilled receipt, or draft purchase bill. Finish or cancel those documents before archiving the supplier.")
            conn.execute("UPDATE suppliers SET is_active=0,updated_at=? WHERE business_id=? AND supplier_id=?", (now, business_id, supplier_id))
            self._audit(conn, business_id, actor_user_id, "purchasing.supplier.archived", "supplier", supplier_id, {}, now)

    def get_supplier(self, business_id: str, supplier_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM suppliers WHERE business_id=? AND supplier_id=?", (business_id, supplier_id)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["outstanding_balance"] = _money_text(self._supplier_balance_read(business_id, supplier_id))
        return data

    def list_suppliers(self, business_id: str, search: str = "", *, active_only: bool = True) -> list[dict[str, Any]]:
        clauses = ["s.business_id=?"]
        params: list[Any] = [business_id]
        if active_only:
            clauses.append("s.is_active=1")
        if search.strip():
            pattern = f"%{search.strip()}%"
            clauses.append("(s.name LIKE ? OR s.supplier_code LIKE ? OR s.phone LIKE ? OR s.gstin LIKE ? OR s.email LIKE ?)")
            params.extend([pattern] * 5)
        with self.database.connection() as conn:
            rows = conn.execute(f"SELECT s.* FROM suppliers s WHERE {' AND '.join(clauses)} ORDER BY s.name COLLATE NOCASE", params).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data["outstanding_balance"] = _money_text(self._supplier_balance(conn, business_id, str(row["supplier_id"])))
                result.append(data)
        return result

    # ---------- Purchase orders ----------
    def create_purchase_order(self, business_id: str, actor_user_id: str, values: dict[str, Any]) -> str:
        data = self._validate_purchase_document(conn=None, business_id=business_id, values=values, require_supplier=True)
        now = _now()
        order_id = new_id("POR")
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.create")
            self._assert_supplier(conn, business_id, data["supplier_id"])
            items, totals = self._normalize_product_lines(conn, business_id, data["items"])
            order_number = self._next_number(conn, "purchase_orders", "order_number", business_id, "PO", data["document_date"])
            conn.execute(
                "INSERT INTO purchase_orders(purchase_order_id,business_id,supplier_id,order_number,order_date,expected_date,status,subtotal,discount_total,taxable_total,tax_total,grand_total,notes,created_by,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'draft',?,?,?,?,?,?, ?,?,?)",
                (order_id, business_id, data["supplier_id"], order_number, data["document_date"], data["due_date"],
                 totals["subtotal"], totals["discount_total"], totals["taxable_total"], totals["tax_total"], totals["grand_total"],
                 data["notes"], actor_user_id, now, now),
            )
            self._insert_purchase_order_items(conn, order_id, items)
            self._audit(conn, business_id, actor_user_id, "purchasing.order.created", "purchase_order", order_id,
                        {"order_number": order_number, "grand_total": totals["grand_total"]}, now)
        return order_id

    def update_purchase_order(self, business_id: str, actor_user_id: str, purchase_order_id: str, values: dict[str, Any]) -> None:
        data = self._validate_purchase_document(conn=None, business_id=business_id, values=values, require_supplier=True)
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.create")
            old = conn.execute("SELECT * FROM purchase_orders WHERE business_id=? AND purchase_order_id=?", (business_id, purchase_order_id)).fetchone()
            if not old:
                raise InventoryError("Purchase order not found in this business.")
            if old["status"] != "draft":
                raise InventoryError("Only draft purchase orders can be edited.")
            self._assert_supplier(conn, business_id, data["supplier_id"])
            items, totals = self._normalize_product_lines(conn, business_id, data["items"])
            conn.execute(
                "UPDATE purchase_orders SET supplier_id=?,order_date=?,expected_date=?,subtotal=?,discount_total=?,taxable_total=?,tax_total=?,grand_total=?,notes=?,updated_at=? WHERE purchase_order_id=? AND business_id=?",
                (data["supplier_id"], data["document_date"], data["due_date"], totals["subtotal"], totals["discount_total"],
                 totals["taxable_total"], totals["tax_total"], totals["grand_total"], data["notes"], now, purchase_order_id, business_id),
            )
            conn.execute("DELETE FROM purchase_order_items WHERE purchase_order_id=?", (purchase_order_id,))
            self._insert_purchase_order_items(conn, purchase_order_id, items)
            self._audit(conn, business_id, actor_user_id, "purchasing.order.updated", "purchase_order", purchase_order_id, {}, now)

    def order_purchase_order(self, business_id: str, actor_user_id: str, purchase_order_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.post")
            order = conn.execute("SELECT status,grand_total FROM purchase_orders WHERE business_id=? AND purchase_order_id=?", (business_id, purchase_order_id)).fetchone()
            if not order:
                raise InventoryError("Purchase order not found in this business.")
            if order["status"] != "draft":
                raise InventoryError("Only draft purchase orders can be marked as ordered.")
            if _decimal(order["grand_total"], "Order total") <= 0:
                raise InventoryError("Add at least one priced item before ordering this purchase order.")
            conn.execute("UPDATE purchase_orders SET status='ordered',updated_at=? WHERE purchase_order_id=?", (now, purchase_order_id))
            self._audit(conn, business_id, actor_user_id, "purchasing.order.ordered", "purchase_order", purchase_order_id, {}, now)

    def receive_purchase_order(self, business_id: str, actor_user_id: str, purchase_order_id: str,
                               receipts: list[dict[str, Any]]) -> str | None:
        if not receipts:
            raise InventoryError("Enter the received quantity for at least one order item.")
        now = _now()
        generated_bill_id: str | None = None
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.receive")
            order = conn.execute("SELECT * FROM purchase_orders WHERE business_id=? AND purchase_order_id=?", (business_id, purchase_order_id)).fetchone()
            if not order:
                raise InventoryError("Purchase order not found in this business.")
            if order["status"] not in {"ordered", "partially_received"}:
                raise InventoryError("Only ordered or partially received purchase orders can receive stock.")
            requested: dict[str, Decimal] = {}
            for entry in receipts:
                item_id = str(entry.get("purchase_order_item_id", ""))
                amount = _quantize(_decimal(entry.get("quantity"), "Received quantity", minimum=Decimal("0.001")), QUANTITY, "Received quantity")
                if amount <= 0:
                    raise InventoryError("Received quantity must be greater than zero.")
                if item_id in requested:
                    raise InventoryError("An order line was submitted more than once.")
                requested[item_id] = amount
            rows = conn.execute(
                "SELECT * FROM purchase_order_items WHERE purchase_order_id=?", (purchase_order_id,)
            ).fetchall()
            by_id = {str(row["purchase_order_item_id"]): row for row in rows}
            for item_id, amount in requested.items():
                row = by_id.get(item_id)
                if not row:
                    raise InventoryError("A selected line does not belong to this purchase order.")
                ordered = _decimal(row["quantity"], "Ordered quantity")
                already = _decimal(row["received_quantity"], "Already received quantity")
                if amount > ordered - already:
                    raise InventoryError(f"Received quantity exceeds the remaining quantity for {row['product_name']}.")
                product = conn.execute("SELECT quantity_on_hand FROM products WHERE business_id=? AND product_id=?", (business_id, row["product_id"])).fetchone()
                if not product:
                    raise InventoryError("A product on this purchase order no longer exists in this business.")
                conn.execute("UPDATE purchase_order_items SET received_quantity=? WHERE purchase_order_item_id=?", (_qty_text(already + amount), item_id))
                unit_cost = _decimal(row["unit_cost"], "Unit cost")
                discount_percent = _decimal(row["discount_percent"], "Purchase discount")
                effective_cost = _money(unit_cost * (Decimal("1") - discount_percent / Decimal("100")))
                self._apply_stock_change(
                    conn, business_id, str(row["product_id"]), amount, effective_cost,
                    "purchase_order_receipt", "purchase_order", purchase_order_id,
                    f"Receipt against {order['order_number']}", actor_user_id, now,
                )
                conn.execute(
                    "UPDATE products SET last_purchase_price=?,updated_at=? WHERE business_id=? AND product_id=?",
                    (_money_text(effective_cost), now, business_id, row["product_id"]),
                )
            refreshed = conn.execute("SELECT quantity,received_quantity FROM purchase_order_items WHERE purchase_order_id=?", (purchase_order_id,)).fetchall()
            any_received = any(_decimal(row["received_quantity"], "Received quantity") > 0 for row in refreshed)
            complete = all(_decimal(row["received_quantity"], "Received quantity") == _decimal(row["quantity"], "Order quantity") for row in refreshed)
            status = "received" if complete else "partially_received" if any_received else "ordered"
            conn.execute("UPDATE purchase_orders SET status=?,updated_at=? WHERE purchase_order_id=?", (status, now, purchase_order_id))
            self._audit(conn, business_id, actor_user_id, "purchasing.order.received", "purchase_order", purchase_order_id,
                        {"received_lines": len(requested), "status": status}, now)
            if any_received:
                # Create/update a bill draft on the first receipt and keep its received quantities
                # synchronized as further deliveries arrive. It remains unpostable until full receipt.
                generated_bill_id = self._auto_generate_purchase_bill(
                    conn, business_id, actor_user_id, purchase_order_id, now
                )
        return generated_bill_id

    def _auto_generate_purchase_bill(self, conn, business_id: str, actor_user_id: str,
                                     purchase_order_id: str, now: str) -> str | None:
        """Create/update one draft purchase bill for received lines; receipt already posts stock."""
        order = conn.execute(
            "SELECT * FROM purchase_orders WHERE business_id=? AND purchase_order_id=? "
            "AND status IN ('partially_received','received')",
            (business_id, purchase_order_id),
        ).fetchone()
        if not order:
            return None

        existing = conn.execute(
            "SELECT * FROM purchase_bills WHERE business_id=? AND source_purchase_order_id=? LIMIT 1",
            (business_id, purchase_order_id),
        ).fetchone()
        bill_id = None
        purchase_number = ""
        is_auto_draft = False
        if existing:
            is_auto_draft = (
                existing["status"] == "draft"
                and str(existing["notes"] or "").startswith("Auto-generated from purchase order")
            )
            if not is_auto_draft:
                # A manually created or already-posted document is never silently rewritten.
                return None
            bill_id = str(existing["purchase_bill_id"])
            purchase_number = str(existing["purchase_number"])

        order_lines = conn.execute(
            "SELECT * FROM purchase_order_items WHERE purchase_order_id=? ORDER BY row_order",
            (purchase_order_id,),
        ).fetchall()
        received_lines = []
        subtotal = ZERO
        discounts = ZERO
        taxable_total = ZERO
        tax_total = ZERO
        for line in order_lines:
            quantity = _qty(_decimal(line["received_quantity"], "Received quantity"))
            if quantity <= 0:
                continue
            unit_cost = _money(_decimal(line["unit_cost"], "Unit cost"))
            discount_percent = _decimal(line["discount_percent"], "Purchase discount")
            tax_rate = _decimal(line["tax_rate"], "Purchase tax rate")
            base = _money(quantity * unit_cost)
            discount = _money(base * discount_percent / Decimal("100"))
            taxable = _money(base - discount)
            tax = _money(taxable * tax_rate / Decimal("100"))
            subtotal += base
            discounts += discount
            taxable_total += taxable
            tax_total += tax
            received_lines.append({
                "product_id": str(line["product_id"]),
                "product_name": str(line["product_name"]),
                "sku": str(line["sku"]),
                "quantity": quantity,
                "unit": str(line["unit"]),
                "unit_cost": unit_cost,
                "discount_percent": discount_percent,
                "tax_rate": tax_rate,
                "taxable_value": taxable,
                "tax_amount": tax,
                "line_total": _money(taxable + tax),
            })
        if not received_lines:
            return None

        subtotal = _money(subtotal)
        discounts = _money(discounts)
        taxable_total = _money(taxable_total)
        tax_total = _money(tax_total)
        grand_total = _money(taxable_total + tax_total)
        due_date = str(order["expected_date"] or "")
        receipt_state = "fully received" if order["status"] == "received" else "partially received"
        note = (
            f"Auto-generated from purchase order {order['order_number']} ({receipt_state}). "
            "Enter the supplier invoice number and verify the supplier document before posting. "
            "KoshFlow updates this draft as further quantities are received; stock is recorded separately at receipt."
        )

        if not bill_id:
            bill_id = new_id("PBL")
            purchase_number = self._next_number(
                conn, "purchase_bills", "purchase_number", business_id, "PB", str(order["order_date"])
            )
            conn.execute(
                "INSERT INTO purchase_bills(purchase_bill_id,business_id,supplier_id,source_purchase_order_id,purchase_number,supplier_invoice_number,purchase_date,due_date,status,subtotal,discount_total,taxable_total,tax_total,grand_total,amount_paid,notes,created_by,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'',?,?,'draft',?,?,?,?,?,'0.00',?,?,?,?)",
                (bill_id, business_id, order["supplier_id"], purchase_order_id, purchase_number,
                 order["order_date"], due_date, _money_text(subtotal), _money_text(discounts),
                 _money_text(taxable_total), _money_text(tax_total), _money_text(grand_total),
                 note, actor_user_id, now, now),
            )
            audit_action = "purchasing.bill.auto_generated"
        else:
            conn.execute(
                "UPDATE purchase_bills SET purchase_date=?,due_date=?,subtotal=?,discount_total=?,taxable_total=?,tax_total=?,grand_total=?,notes=?,updated_at=? WHERE business_id=? AND purchase_bill_id=? AND status='draft'",
                (order["order_date"], due_date, _money_text(subtotal), _money_text(discounts),
                 _money_text(taxable_total), _money_text(tax_total), _money_text(grand_total), note, now,
                 business_id, bill_id),
            )
            conn.execute("DELETE FROM purchase_items WHERE purchase_bill_id=?", (bill_id,))
            audit_action = "purchasing.bill.auto_draft_updated"

        for index, line in enumerate(received_lines):
            conn.execute(
                "INSERT INTO purchase_items(purchase_item_id,purchase_bill_id,row_order,product_id,product_name,sku,quantity,unit,unit_cost,discount_percent,tax_rate,taxable_value,tax_amount,line_total) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("PBI"), bill_id, index, line["product_id"], line["product_name"], line["sku"],
                 _qty_text(line["quantity"]), line["unit"], _money_text(line["unit_cost"]),
                 str(line["discount_percent"]), str(line["tax_rate"]), _money_text(line["taxable_value"]),
                 _money_text(line["tax_amount"]), _money_text(line["line_total"])),
            )
        self._audit(
            conn, business_id, actor_user_id, audit_action, "purchase_bill", bill_id,
            {"purchase_number": purchase_number, "source_purchase_order_id": purchase_order_id,
             "source_order_number": order["order_number"], "status": "draft",
             "received_lines": len(received_lines), "receipt_state": receipt_state}, now,
        )
        return bill_id

    def cancel_purchase_order(self, business_id: str, actor_user_id: str, purchase_order_id: str, reason: str) -> None:
        reason = str(reason or "").strip()
        if not reason:
            raise InventoryError("Enter a reason for cancelling the purchase order.")
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.post")
            order = conn.execute("SELECT status FROM purchase_orders WHERE business_id=? AND purchase_order_id=?", (business_id, purchase_order_id)).fetchone()
            if not order:
                raise InventoryError("Purchase order not found in this business.")
            received = conn.execute("SELECT 1 FROM purchase_order_items WHERE purchase_order_id=? AND CAST(received_quantity AS REAL)>0 LIMIT 1", (purchase_order_id,)).fetchone()
            if order["status"] not in {"draft", "ordered"} or received:
                raise InventoryError("A purchase order cannot be cancelled after any stock has been received. Record a supplier return instead.")
            conn.execute("UPDATE purchase_orders SET status='cancelled',notes=CASE WHEN notes='' THEN ? ELSE notes || char(10) || ? END,updated_at=? WHERE purchase_order_id=?",
                         (f"Cancellation reason: {reason}", f"Cancellation reason: {reason}", now, purchase_order_id))
            self._audit(conn, business_id, actor_user_id, "purchasing.order.cancelled", "purchase_order", purchase_order_id, {"reason": reason}, now)

    def list_purchase_orders(self, business_id: str, search: str = "", status: str = "All") -> list[dict[str, Any]]:
        clauses = ["po.business_id=?"]
        params: list[Any] = [business_id]
        if search.strip():
            p = f"%{search.strip()}%"
            clauses.append("(po.order_number LIKE ? OR s.name LIKE ? OR s.supplier_code LIKE ?)")
            params.extend([p, p, p])
        if status and status != "All":
            clauses.append("po.status=?")
            params.append(status)
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT po.*,s.name AS supplier_name,(SELECT COUNT(*) FROM purchase_order_items i WHERE i.purchase_order_id=po.purchase_order_id) AS line_count "
                f"FROM purchase_orders po JOIN suppliers s ON s.supplier_id=po.supplier_id WHERE {' AND '.join(clauses)} ORDER BY po.order_date DESC,po.created_at DESC", params
            ).fetchall()
        return [dict(row) for row in rows]

    def get_purchase_order(self, business_id: str, purchase_order_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT po.*,s.name AS supplier_name FROM purchase_orders po JOIN suppliers s ON s.supplier_id=po.supplier_id WHERE po.business_id=? AND po.purchase_order_id=?", (business_id, purchase_order_id)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["items"] = [dict(item) for item in conn.execute("SELECT * FROM purchase_order_items WHERE purchase_order_id=? ORDER BY row_order", (purchase_order_id,)).fetchall()]
        return result

    # ---------- Supplier purchase bills ----------
    def create_purchase_bill(self, business_id: str, actor_user_id: str, values: dict[str, Any]) -> str:
        data = self._validate_purchase_document(conn=None, business_id=business_id, values=values, require_supplier=True)
        now = _now()
        bill_id = new_id("PBL")
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.create")
            self._assert_supplier(conn, business_id, data["supplier_id"])
            items, totals = self._normalize_product_lines(conn, business_id, data["items"])
            po_id = str(values.get("source_purchase_order_id") or "").strip() or None
            supplier_invoice_number = str(values.get("supplier_invoice_number", "")).strip()[:100]
            self._assert_supplier_invoice_unique(conn, business_id, data["supplier_id"], supplier_invoice_number)
            if po_id:
                self._validate_linked_order(conn, business_id, data["supplier_id"], po_id, items) if not conn.execute(
                    "SELECT 1 FROM purchase_bills WHERE business_id=? AND source_purchase_order_id=? AND status='draft' AND notes LIKE 'Auto-generated from purchase order%' LIMIT 1",
                    (business_id, po_id),
                ).fetchone() else self._validate_linked_order_rows(conn, business_id, data["supplier_id"], po_id, items)
                auto_existing = conn.execute(
                    "SELECT * FROM purchase_bills WHERE business_id=? AND source_purchase_order_id=? AND status='draft' AND notes LIKE 'Auto-generated from purchase order%' LIMIT 1",
                    (business_id, po_id),
                ).fetchone()
                if auto_existing:
                    conn.execute(
                        "UPDATE purchase_bills SET supplier_invoice_number=?,purchase_date=?,due_date=?,subtotal=?,discount_total=?,taxable_total=?,tax_total=?,grand_total=?,notes=?,updated_at=? WHERE purchase_bill_id=?",
                        (supplier_invoice_number, data["document_date"], data["due_date"], totals["subtotal"], totals["discount_total"],
                         totals["taxable_total"], totals["tax_total"], totals["grand_total"], data["notes"] or auto_existing["notes"], now, auto_existing["purchase_bill_id"]),
                    )
                    conn.execute("DELETE FROM purchase_items WHERE purchase_bill_id=?", (auto_existing["purchase_bill_id"],))
                    self._insert_purchase_items(conn, str(auto_existing["purchase_bill_id"]), items)
                    self._audit(conn, business_id, actor_user_id, "purchasing.bill.auto_draft_completed", "purchase_bill", str(auto_existing["purchase_bill_id"]),
                                {"supplier_invoice_number": supplier_invoice_number, "source_purchase_order_id": po_id}, now)
                    return str(auto_existing["purchase_bill_id"])
                self._assert_purchase_order_invoice_available(conn, business_id, po_id)
            purchase_number = self._next_number(conn, "purchase_bills", "purchase_number", business_id, "PB", data["document_date"])
            conn.execute(
                "INSERT INTO purchase_bills(purchase_bill_id,business_id,supplier_id,source_purchase_order_id,purchase_number,supplier_invoice_number,purchase_date,due_date,status,subtotal,discount_total,taxable_total,tax_total,grand_total,amount_paid,notes,created_by,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?, 'draft',?,?,?,?,?,'0.00',?,?,?,?)",
                (bill_id, business_id, data["supplier_id"], po_id, purchase_number,
                 supplier_invoice_number, data["document_date"], data["due_date"],
                 totals["subtotal"], totals["discount_total"], totals["taxable_total"], totals["tax_total"], totals["grand_total"],
                 data["notes"], actor_user_id, now, now),
            )
            self._insert_purchase_items(conn, bill_id, items)
            self._audit(conn, business_id, actor_user_id, "purchasing.bill.created", "purchase_bill", bill_id,
                        {"purchase_number": purchase_number, "grand_total": totals["grand_total"]}, now)
        return bill_id

    def update_purchase_bill(self, business_id: str, actor_user_id: str, purchase_bill_id: str, values: dict[str, Any]) -> None:
        data = self._validate_purchase_document(conn=None, business_id=business_id, values=values, require_supplier=True)
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.create")
            old = conn.execute("SELECT * FROM purchase_bills WHERE business_id=? AND purchase_bill_id=?", (business_id, purchase_bill_id)).fetchone()
            if not old:
                raise InventoryError("Purchase bill not found in this business.")
            if old["status"] != "draft":
                raise InventoryError("Only draft purchase bills can be edited. Posted purchase bills must be corrected through return/credit workflows.")
            self._assert_supplier(conn, business_id, data["supplier_id"])
            items, totals = self._normalize_product_lines(conn, business_id, data["items"])
            po_id = str(values.get("source_purchase_order_id") or "").strip() or None
            supplier_invoice_number = str(values.get("supplier_invoice_number", "")).strip()[:100]
            self._assert_supplier_invoice_unique(
                conn, business_id, data["supplier_id"], supplier_invoice_number,
                exclude_purchase_bill_id=purchase_bill_id,
            )
            if po_id:
                self._assert_purchase_order_invoice_available(conn, business_id, po_id, exclude_purchase_bill_id=purchase_bill_id)
                self._validate_linked_order(conn, business_id, data["supplier_id"], po_id, items)
            conn.execute(
                "UPDATE purchase_bills SET supplier_id=?,source_purchase_order_id=?,supplier_invoice_number=?,purchase_date=?,due_date=?,subtotal=?,discount_total=?,taxable_total=?,tax_total=?,grand_total=?,notes=?,updated_at=? WHERE purchase_bill_id=? AND business_id=?",
                (data["supplier_id"], po_id, supplier_invoice_number, data["document_date"], data["due_date"],
                 totals["subtotal"], totals["discount_total"], totals["taxable_total"], totals["tax_total"], totals["grand_total"], data["notes"], now, purchase_bill_id, business_id),
            )
            conn.execute("DELETE FROM purchase_items WHERE purchase_bill_id=?", (purchase_bill_id,))
            self._insert_purchase_items(conn, purchase_bill_id, items)
            self._audit(conn, business_id, actor_user_id, "purchasing.bill.updated", "purchase_bill", purchase_bill_id, {}, now)

    def post_purchase_bill(self, business_id: str, actor_user_id: str, purchase_bill_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.post")
            bill = conn.execute("SELECT * FROM purchase_bills WHERE business_id=? AND purchase_bill_id=?", (business_id, purchase_bill_id)).fetchone()
            if not bill:
                raise InventoryError("Purchase bill not found in this business.")
            if bill["status"] != "draft":
                raise InventoryError("Only draft purchase bills can be posted.")
            if _decimal(bill["grand_total"], "Purchase total") <= ZERO:
                raise InventoryError("Add at least one priced item before posting a purchase bill.")
            items = conn.execute("SELECT * FROM purchase_items WHERE purchase_bill_id=? ORDER BY row_order", (purchase_bill_id,)).fetchall()
            if not items:
                raise InventoryError("A purchase bill must contain at least one item.")
            source_po_id = bill["source_purchase_order_id"]
            if source_po_id:
                # A linked order has already changed stock during receipt. Matching received
                # quantities prevents both double-counting and posting an unmatched invoice.
                self._assert_purchase_order_invoice_available(
                    conn, business_id, str(source_po_id), exclude_purchase_bill_id=purchase_bill_id
                )
                self._validate_linked_order_rows(conn, business_id, str(bill["supplier_id"]), str(source_po_id), items)
            else:
                for item in items:
                    qty = _decimal(item["quantity"], "Purchase quantity", minimum=Decimal("0.001"))
                    listed_cost = _decimal(item["unit_cost"], "Unit cost")
                    discount_percent = _decimal(item["discount_percent"], "Purchase discount")
                    effective_cost = _money(listed_cost * (Decimal("1") - discount_percent / Decimal("100")))
                    self._apply_stock_change(
                        conn, business_id, str(item["product_id"]), qty, effective_cost,
                        "purchase", "purchase_bill", purchase_bill_id, f"Receipt against {bill['purchase_number']}", actor_user_id, now,
                    )
            for item in items:
                listed_cost = _decimal(item["unit_cost"], "Unit cost")
                discount_percent = _decimal(item["discount_percent"], "Purchase discount")
                effective_cost = _money(listed_cost * (Decimal("1") - discount_percent / Decimal("100")))
                conn.execute("UPDATE products SET last_purchase_price=?,updated_at=? WHERE business_id=? AND product_id=?",
                             (_money_text(effective_cost), now, business_id, item["product_id"]))
            conn.execute("UPDATE purchase_bills SET status='posted',posted_at=?,updated_at=? WHERE purchase_bill_id=? AND business_id=?",
                         (now, now, purchase_bill_id, business_id))
            self._audit(conn, business_id, actor_user_id, "purchasing.bill.posted", "purchase_bill", purchase_bill_id,
                        {"grand_total": bill["grand_total"], "stock_applied": not bool(source_po_id)}, now)
            AccountingService.post_purchase_bill_conn(conn, business_id, actor_user_id, purchase_bill_id)

    def delete_purchase_bill_draft(self, business_id: str, actor_user_id: str, purchase_bill_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.create")
            row = conn.execute("SELECT status FROM purchase_bills WHERE business_id=? AND purchase_bill_id=?", (business_id, purchase_bill_id)).fetchone()
            if not row:
                raise InventoryError("Purchase bill not found in this business.")
            if row["status"] != "draft":
                raise InventoryError("Only draft purchase bills can be deleted. Posted records must remain auditable.")
            conn.execute("DELETE FROM purchase_bills WHERE purchase_bill_id=?", (purchase_bill_id,))
            self._audit(conn, business_id, actor_user_id, "purchasing.bill.draft_deleted", "purchase_bill", purchase_bill_id, {}, now)

    def list_purchase_bills(self, business_id: str, search: str = "", status: str = "All") -> list[dict[str, Any]]:
        clauses = ["pb.business_id=?"]
        params: list[Any] = [business_id]
        if search.strip():
            p = f"%{search.strip()}%"
            clauses.append("(pb.purchase_number LIKE ? OR pb.supplier_invoice_number LIKE ? OR s.name LIKE ? OR s.supplier_code LIKE ?)")
            params.extend([p, p, p, p])
        if status and status != "All":
            clauses.append("pb.status=?")
            params.append(status)
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT pb.*,s.name AS supplier_name FROM purchase_bills pb JOIN suppliers s ON s.supplier_id=pb.supplier_id "
                f"WHERE {' AND '.join(clauses)} ORDER BY pb.purchase_date DESC,pb.created_at DESC", params
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data["balance_due"] = _money_text(self._purchase_bill_balance(conn, data))
                result.append(data)
        return result

    def get_purchase_bill(self, business_id: str, purchase_bill_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT pb.*,s.name AS supplier_name FROM purchase_bills pb JOIN suppliers s ON s.supplier_id=pb.supplier_id WHERE pb.business_id=? AND pb.purchase_bill_id=?",
                (business_id, purchase_bill_id),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["balance_due"] = _money_text(self._purchase_bill_balance(conn, result))
            result["items"] = [dict(item) for item in conn.execute("SELECT * FROM purchase_items WHERE purchase_bill_id=? ORDER BY row_order", (purchase_bill_id,)).fetchall()]
            result["payments"] = [dict(payment) for payment in conn.execute("SELECT * FROM supplier_payments WHERE purchase_bill_id=? ORDER BY paid_at DESC", (purchase_bill_id,)).fetchall()]
            result["returns"] = [dict(ret) for ret in conn.execute("SELECT * FROM supplier_returns WHERE purchase_bill_id=? ORDER BY return_date DESC", (purchase_bill_id,)).fetchall()]
        return result

    def record_supplier_payment(self, business_id: str, actor_user_id: str, purchase_bill_id: str,
                                amount: Any, payment_method: str, reference: str = "", paid_at: str | None = None) -> str:
        value = _money(_decimal(amount, "Payment amount", minimum=Decimal("0.01")))
        if payment_method not in PAYMENT_METHODS:
            raise InventoryError("Choose a supported payment method.")
        paid_date = _date(paid_at or date.today().isoformat(), "Payment date")
        now = _now()
        payment_id = new_id("SPM")
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.pay")
            bill = conn.execute("SELECT * FROM purchase_bills WHERE business_id=? AND purchase_bill_id=?", (business_id, purchase_bill_id)).fetchone()
            if not bill:
                raise InventoryError("Purchase bill not found in this business.")
            if bill["status"] not in {"posted", "part_paid", "paid"}:
                raise InventoryError("Payments can only be recorded against posted purchase bills.")
            returned = self._purchase_return_total(conn, purchase_bill_id)
            due = _money(_decimal(bill["grand_total"], "Purchase total") - _decimal(bill["amount_paid"], "Amount paid") - returned)
            if value > due:
                raise InventoryError(f"Payment exceeds the outstanding supplier balance of ₹{due:.2f}.")
            new_paid = _money(_decimal(bill["amount_paid"], "Amount paid") + value)
            new_due = _money(_decimal(bill["grand_total"], "Purchase total") - new_paid - returned)
            status = "paid" if new_due <= ZERO else "part_paid"
            conn.execute("INSERT INTO supplier_payments(supplier_payment_id,business_id,supplier_id,purchase_bill_id,amount,payment_method,reference,paid_at,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (payment_id, business_id, bill["supplier_id"], purchase_bill_id, _money_text(value), payment_method, str(reference or "").strip()[:120], paid_date, actor_user_id, now))
            conn.execute("UPDATE purchase_bills SET amount_paid=?,status=?,updated_at=? WHERE purchase_bill_id=?",
                         (_money_text(new_paid), status, now, purchase_bill_id))
            self._audit(conn, business_id, actor_user_id, "purchasing.payment.recorded", "supplier_payment", payment_id,
                        {"purchase_bill_id": purchase_bill_id, "amount": _money_text(value), "method": payment_method}, now)
            AccountingService.post_supplier_payment_conn(conn, business_id, actor_user_id, payment_id)
        return payment_id

    # ---------- Supplier returns / credits ----------
    def create_supplier_return(self, business_id: str, actor_user_id: str, purchase_bill_id: str,
                               purchase_item_id: str, quantity: Any, reason: str, return_date: str | None = None) -> str:
        qty = _quantize(_decimal(quantity, "Return quantity", minimum=Decimal("0.001")), QUANTITY, "Return quantity")
        why = str(reason or "").strip()
        if not why:
            raise InventoryError("Enter the reason for returning goods to the supplier.")
        ret_date = _date(return_date or date.today().isoformat(), "Return date")
        now = _now()
        return_id = new_id("PRR")
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.return")
            bill = conn.execute("SELECT * FROM purchase_bills WHERE business_id=? AND purchase_bill_id=?", (business_id, purchase_bill_id)).fetchone()
            if not bill or bill["status"] not in {"posted", "part_paid", "paid"}:
                raise InventoryError("Supplier returns require a posted purchase bill.")
            item = conn.execute("SELECT * FROM purchase_items WHERE purchase_bill_id=? AND purchase_item_id=?", (purchase_bill_id, purchase_item_id)).fetchone()
            if not item:
                raise InventoryError("The selected purchase item does not belong to this bill.")
            prior_returns = conn.execute(
                "SELECT sri.quantity FROM supplier_return_items sri JOIN supplier_returns sr ON sr.supplier_return_id=sri.supplier_return_id WHERE sri.purchase_item_id=? AND sr.status IN ('draft','posted')",
                (purchase_item_id,),
            ).fetchall()
            reserved_return = sum((_decimal(row["quantity"], "Reserved return quantity") for row in prior_returns), QZERO)
            available_return = _decimal(item["quantity"], "Purchased quantity") - reserved_return
            if qty > available_return:
                raise InventoryError(f"Return quantity exceeds the unreturned purchased quantity ({_qty_text(available_return)} {item['unit']}).")
            product = conn.execute("SELECT quantity_on_hand FROM products WHERE business_id=? AND product_id=?", (business_id, item["product_id"])).fetchone()
            on_hand = _decimal(product["quantity_on_hand"], "Current stock") if product else ZERO
            draft_stock_returns = conn.execute(
                "SELECT sri.quantity FROM supplier_return_items sri JOIN supplier_returns sr ON sr.supplier_return_id=sri.supplier_return_id WHERE sri.product_id=? AND sr.status='draft'",
                (item["product_id"],),
            ).fetchall()
            stock_reserved = sum((_decimal(row["quantity"], "Reserved stock return") for row in draft_stock_returns), QZERO)
            available_stock = on_hand - stock_reserved
            if qty > available_stock:
                raise InventoryError(f"Only {_qty_text(max(QZERO, available_stock))} {item['unit']} is available for a new supplier return after existing draft return reservations.")
            unit_cost = _decimal(item["unit_cost"], "Unit cost")
            discount_percent = _decimal(item["discount_percent"], "Purchase discount")
            effective_unit_cost = _money(unit_cost * (Decimal("1") - discount_percent / Decimal("100")))
            taxable = _money(qty * effective_unit_cost)
            tax_rate = _decimal(item["tax_rate"], "Tax rate")
            tax = _money(taxable * tax_rate / Decimal("100"))
            number = self._next_number(conn, "supplier_returns", "return_number", business_id, "SR", ret_date)
            conn.execute(
                "INSERT INTO supplier_returns(supplier_return_id,business_id,supplier_id,purchase_bill_id,return_number,return_date,status,subtotal,tax_total,grand_total,reason,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,'draft',?,?,?,?,?,?,?)",
                (return_id, business_id, bill["supplier_id"], purchase_bill_id, number, ret_date,
                 _money_text(taxable), _money_text(tax), _money_text(taxable + tax), why[:1000], actor_user_id, now, now),
            )
            conn.execute(
                "INSERT INTO supplier_return_items(supplier_return_item_id,supplier_return_id,purchase_item_id,product_id,product_name,quantity,unit_cost,discount_percent,tax_rate,taxable_value,tax_amount,line_total) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("PRI"), return_id, purchase_item_id, item["product_id"], item["product_name"], _qty_text(qty),
                 item["unit_cost"], item["discount_percent"], item["tax_rate"], _money_text(taxable), _money_text(tax), _money_text(taxable + tax)),
            )
            self._audit(conn, business_id, actor_user_id, "purchasing.return.created", "supplier_return", return_id,
                        {"return_number": number, "quantity": _qty_text(qty), "grand_total": _money_text(taxable + tax)}, now)
        return return_id

    def post_supplier_return(self, business_id: str, actor_user_id: str, supplier_return_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.return")
            ret = conn.execute("SELECT * FROM supplier_returns WHERE business_id=? AND supplier_return_id=?", (business_id, supplier_return_id)).fetchone()
            if not ret:
                raise InventoryError("Supplier return not found in this business.")
            if ret["status"] != "draft":
                raise InventoryError("Only draft supplier returns can be posted.")
            items = conn.execute("SELECT * FROM supplier_return_items WHERE supplier_return_id=?", (supplier_return_id,)).fetchall()
            if not items:
                raise InventoryError("A supplier return must include at least one item.")
            for item in items:
                return_cost = _money(
                    _decimal(item["unit_cost"], "Unit cost")
                    * (Decimal("1") - _decimal(item["discount_percent"], "Purchase discount") / Decimal("100"))
                )
                self._apply_stock_change(
                    conn, business_id, str(item["product_id"]), -_decimal(item["quantity"], "Return quantity"),
                    return_cost, "supplier_return", "supplier_return", supplier_return_id,
                    f"Return to supplier: {ret['reason']}", actor_user_id, now,
                )
            conn.execute("UPDATE supplier_returns SET status='posted',posted_at=?,updated_at=? WHERE supplier_return_id=?", (now, now, supplier_return_id))
            bill = conn.execute("SELECT * FROM purchase_bills WHERE purchase_bill_id=?", (ret["purchase_bill_id"],)).fetchone()
            returned_total = self._purchase_return_total(conn, str(ret["purchase_bill_id"])) + _decimal(ret["grand_total"], "Return total")
            due = _money(_decimal(bill["grand_total"], "Purchase total") - _decimal(bill["amount_paid"], "Amount paid") - returned_total)
            new_status = "paid" if due <= ZERO else "part_paid" if _decimal(bill["amount_paid"], "Amount paid") > ZERO else "posted"
            conn.execute("UPDATE purchase_bills SET status=?,updated_at=? WHERE purchase_bill_id=?", (new_status, now, ret["purchase_bill_id"]))
            self._audit(conn, business_id, actor_user_id, "purchasing.return.posted", "supplier_return", supplier_return_id,
                        {"grand_total": ret["grand_total"], "purchase_bill_id": ret["purchase_bill_id"]}, now)
            AccountingService.post_supplier_return_conn(conn, business_id, actor_user_id, supplier_return_id)

    def cancel_supplier_return_draft(self, business_id: str, actor_user_id: str, supplier_return_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "purchasing.return")
            row = conn.execute("SELECT status FROM supplier_returns WHERE business_id=? AND supplier_return_id=?", (business_id, supplier_return_id)).fetchone()
            if not row:
                raise InventoryError("Supplier return not found in this business.")
            if row["status"] != "draft":
                raise InventoryError("Only draft returns can be cancelled. Posted returns require a documented correction.")
            conn.execute("UPDATE supplier_returns SET status='cancelled',updated_at=? WHERE supplier_return_id=?", (now, supplier_return_id))
            self._audit(conn, business_id, actor_user_id, "purchasing.return.cancelled", "supplier_return", supplier_return_id, {}, now)

    def list_supplier_returns(self, business_id: str, search: str = "", status: str = "All") -> list[dict[str, Any]]:
        clauses = ["sr.business_id=?"]
        params: list[Any] = [business_id]
        if search.strip():
            p = f"%{search.strip()}%"
            clauses.append("(sr.return_number LIKE ? OR s.name LIKE ? OR pb.purchase_number LIKE ?)")
            params.extend([p, p, p])
        if status and status != "All":
            clauses.append("sr.status=?")
            params.append(status)
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT sr.*,s.name AS supplier_name,pb.purchase_number FROM supplier_returns sr JOIN suppliers s ON s.supplier_id=sr.supplier_id JOIN purchase_bills pb ON pb.purchase_bill_id=sr.purchase_bill_id WHERE {' AND '.join(clauses)} ORDER BY sr.return_date DESC,sr.created_at DESC", params
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- Stock ledger and reporting ----------
    def adjust_stock(self, business_id: str, actor_user_id: str, product_id: str, mode: str,
                     quantity: Any, reason: str, unit_cost: Any = None) -> str:
        why = str(reason or "").strip()
        if not why:
            raise InventoryError("A stock adjustment requires a reason for the audit trail.")
        value = _quantize(_decimal(quantity, "Adjustment quantity", minimum=ZERO), QUANTITY, "Adjustment quantity")
        if mode not in {"add", "remove", "set"}:
            raise InventoryError("Choose add, remove or set stock mode.")
        if value <= 0 and mode != "set":
            raise InventoryError("Adjustment quantity must be greater than zero.")
        now = _now()
        movement_id = new_id("STM")
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "inventory.adjust")
            product = conn.execute("SELECT * FROM products WHERE business_id=? AND product_id=? AND is_active=1", (business_id, product_id)).fetchone()
            if not product:
                raise InventoryError("Active product not found in this business.")
            current = _decimal(product["quantity_on_hand"], "Current stock")
            delta = value - current if mode == "set" else value if mode == "add" else -value
            if delta == ZERO:
                raise InventoryError("The entered stock count matches the current quantity; no adjustment is needed.")
            cost = _decimal(unit_cost if unit_cost not in (None, "") else product["average_cost"], "Unit cost")
            movement_type = "adjustment_in" if delta > 0 else "adjustment_out"
            self._apply_stock_change(conn, business_id, product_id, delta, cost, movement_type, "stock_adjustment", movement_id,
                                     why, actor_user_id, now)
            self._audit(conn, business_id, actor_user_id, "inventory.stock.adjusted", "stock_movement", movement_id,
                        {"product_id": product_id, "delta": _qty_text(delta), "reason": why}, now)
        return movement_id

    def list_stock_movements(self, business_id: str, search: str = "", limit: int = 500) -> list[dict[str, Any]]:
        clauses = ["sm.business_id=?"]
        params: list[Any] = [business_id]
        if search.strip():
            p = f"%{search.strip()}%"
            clauses.append("(p.name LIKE ? OR p.sku LIKE ? OR sm.source_type LIKE ? OR sm.source_id LIKE ? OR sm.reason LIKE ? OR u.display_name LIKE ?)")
            params.extend([p, p, p, p, p, p])
        params.append(max(1, min(int(limit), 5000)))
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT sm.*,p.name AS product_name,p.sku,p.unit,u.display_name AS actor_name, "
                "COALESCE((SELECT b.bill_number FROM bills b WHERE b.bill_id=sm.source_id AND sm.source_type='bill'), "
                "(SELECT pb.purchase_number FROM purchase_bills pb WHERE pb.purchase_bill_id=sm.source_id AND sm.source_type='purchase_bill'), "
                "(SELECT po.order_number FROM purchase_orders po WHERE po.purchase_order_id=sm.source_id AND sm.source_type='purchase_order'), "
                "(SELECT sr.return_number FROM supplier_returns sr WHERE sr.supplier_return_id=sm.source_id AND sm.source_type='supplier_return'), sm.source_id) AS source_reference "
                f"FROM stock_movements sm JOIN products p ON p.product_id=sm.product_id "
                "LEFT JOIN users u ON u.user_id=sm.created_by "
                f"WHERE {' AND '.join(clauses)} ORDER BY sm.created_at DESC,sm.rowid DESC LIMIT ?", params
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            delta = _decimal(item.get("quantity_delta"), "Quantity delta", allow_negative=True)
            unit_cost = _decimal(item.get("unit_cost"), "Unit cost")
            item["movement_value"] = item.get("movement_value") or _money_text(abs(delta) * unit_cost)
            item["source_reference"] = item.get("source_reference") or item.get("source_id", "")
            result.append(item)
        return result

    def inventory_summary(self, business_id: str) -> dict[str, Any]:
        with self.database.connection() as conn:
            products = conn.execute(
                "SELECT quantity_on_hand,average_cost,reorder_level FROM products WHERE business_id=? AND is_active=1",
                (business_id,),
            ).fetchall()
            movement_count = conn.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE business_id=? AND substr(created_at,1,10)=?",
                (business_id, date.today().isoformat()),
            ).fetchone()[0]
            supplier_count = conn.execute("SELECT COUNT(*) FROM suppliers WHERE business_id=? AND is_active=1", (business_id,)).fetchone()[0]
        valuation = ZERO
        products_with_stock = 0
        low_stock = 0
        for row in products:
            qty = _decimal(row["quantity_on_hand"], "On-hand quantity")
            cost = _decimal(row["average_cost"], "Average cost")
            reorder = _decimal(row["reorder_level"], "Reorder level")
            valuation += qty * cost
            if qty > ZERO:
                products_with_stock += 1
            if reorder > ZERO and qty <= reorder:
                low_stock += 1
        return {"product_count": len(products), "products_with_stock": products_with_stock, "low_stock_count": low_stock,
                "valuation": _money_text(valuation),
                "movements_today": int(movement_count), "supplier_count": int(supplier_count)}

    def purchasing_summary(self, business_id: str) -> dict[str, Any]:
        with self.database.connection() as conn:
            orders = conn.execute(
                "SELECT status,COUNT(*) AS cnt FROM purchase_orders WHERE business_id=? GROUP BY status",
                (business_id,),
            ).fetchall()
            bills = conn.execute(
                "SELECT status,COUNT(*) AS cnt FROM purchase_bills WHERE business_id=? GROUP BY status",
                (business_id,),
            ).fetchall()
            supplier_count = conn.execute(
                "SELECT COUNT(*) FROM suppliers WHERE business_id=? AND is_active=1", (business_id,),
            ).fetchone()[0]
            supplier_ids = [str(row[0]) for row in conn.execute(
                "SELECT supplier_id FROM suppliers WHERE business_id=?", (business_id,),
            ).fetchall()]
            draft_returns = conn.execute(
                "SELECT COUNT(*) FROM supplier_returns WHERE business_id=? AND status='draft'", (business_id,),
            ).fetchone()[0]

            payable_total = ZERO
            credit_total = ZERO
            for supplier_id in supplier_ids:
                balance = self._supplier_balance(conn, business_id, supplier_id)
                if balance > ZERO:
                    payable_total += balance
                elif balance < ZERO:
                    credit_total += abs(balance)

        order_counts = {str(row["status"]): int(row["cnt"]) for row in orders}
        bill_counts = {str(row["status"]): int(row["cnt"]) for row in bills}
        return {
            "supplier_count": int(supplier_count),
            "orders_open": order_counts.get("ordered", 0) + order_counts.get("partially_received", 0),
            "orders_draft": order_counts.get("draft", 0),
            "bills_count": sum(bill_counts.values()),
            "bills_unpaid": bill_counts.get("posted", 0) + bill_counts.get("part_paid", 0),
            "supplier_payables": _money_text(payable_total),
            "supplier_credits": _money_text(credit_total),
            "draft_returns": int(draft_returns),
        }

    def list_supplier_payments(self, business_id: str, search: str = "") -> list[dict[str, Any]]:
        clauses = ["sp.business_id=?"]
        params: list[Any] = [business_id]
        if search.strip():
            p = f"%{search.strip()}%"
            clauses.append("(s.name LIKE ? OR sp.reference LIKE ? OR pb.purchase_number LIKE ?)")
            params.extend([p, p, p])
        with self.database.connection() as conn:
            rows = conn.execute(f"SELECT sp.*,s.name AS supplier_name,pb.purchase_number FROM supplier_payments sp JOIN suppliers s ON s.supplier_id=sp.supplier_id JOIN purchase_bills pb ON pb.purchase_bill_id=sp.purchase_bill_id WHERE {' AND '.join(clauses)} ORDER BY sp.paid_at DESC,sp.created_at DESC", params).fetchall()
        return [dict(row) for row in rows]

    def export_products_csv(self, business_id: str) -> str:
        output = StringIO(newline="")
        fields = ["SKU", "Name", "Category", "Barcode", "HSN", "Unit", "On hand", "Reorder level", "Average cost", "Selling price", "Tax rate %", "Active"]
        writer = csv.writer(output)
        writer.writerow(fields)
        for product in self.list_products(business_id, active_only=False):
            writer.writerow([product["sku"], product["name"], product["category"], product["barcode"] or "", product["hsn_code"], product["unit"], product["quantity_on_hand"], product["reorder_level"], product["average_cost"], product["selling_price"], product["tax_rate"], "Yes" if product["is_active"] else "No"])
        return output.getvalue()

    # ---------- Shared validation and helpers ----------
    def _validate_product(self, values: dict[str, Any], include_opening: bool = True) -> dict[str, Any]:
        sku = str(values.get("sku", "")).strip()
        name = str(values.get("name", "")).strip()
        if not name:
            raise InventoryError("Product name is required.")
        if len(sku) > 80 or len(name) > 180:
            raise InventoryError("SKU or product name is too long.")
        barcode = str(values.get("barcode", "")).strip() or None
        purchase_price = _money(_decimal(values.get("purchase_price", 0), "Purchase price"))
        selling_price = _money(_decimal(values.get("selling_price", 0), "Selling price"))
        tax_rate = _decimal(values.get("tax_rate", 0), "Tax rate")
        reorder = _quantize(_decimal(values.get("reorder_level", 0), "Reorder level"), QUANTITY, "Reorder level")
        opening = _quantize(_decimal(values.get("opening_quantity", 0), "Opening quantity"), QUANTITY, "Opening quantity") if include_opening else QZERO
        if tax_rate > 100:
            raise InventoryError("Tax rate cannot exceed 100%.")
        unit = str(values.get("unit", "pcs")).strip() or "pcs"
        return {"sku": sku[:80], "barcode": barcode[:100] if barcode else None, "name": name[:180],
                "description": str(values.get("description", "")).strip()[:1000],
                "category": str(values.get("category", "General")).strip()[:80] or "General",
                "hsn_code": str(values.get("hsn_code", "")).strip()[:20], "unit": unit[:20],
                "purchase_price": purchase_price, "selling_price": selling_price, "tax_rate": tax_rate,
                "reorder_level": reorder, "opening_quantity": opening}

    def _validate_supplier(self, values: dict[str, Any]) -> dict[str, Any]:
        code = str(values.get("supplier_code", "")).strip()
        name = str(values.get("name", "")).strip()
        if not code:
            raise InventoryError("A unique supplier code is required.")
        if not name:
            raise InventoryError("Supplier/business name is required.")
        gstin = normalize_gstin(str(values.get("gstin", "")))
        if gstin and (error := validate_gstin(gstin)):
            raise InventoryError(error)
        try:
            terms = int(values.get("payment_terms_days", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise InventoryError("Payment terms must be a whole number of days.") from exc
        if not 0 <= terms <= 365:
            raise InventoryError("Payment terms must be between 0 and 365 days.")
        email = str(values.get("email", "")).strip()
        if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
            raise InventoryError("Enter a valid supplier email address.")
        return {"supplier_code": code[:80], "name": name[:180], "contact_person": str(values.get("contact_person", "")).strip()[:180],
                "phone": str(values.get("phone", "")).strip()[:40], "email": email[:180], "gstin": gstin,
                "pan": str(values.get("pan", "")).strip().upper()[:10], "address": str(values.get("address", "")).strip()[:1000],
                "city": str(values.get("city", "")).strip()[:100], "state": str(values.get("state", "")).strip()[:100],
                "pincode": str(values.get("pincode", "")).strip()[:10], "payment_terms_days": terms,
                "notes": str(values.get("notes", "")).strip()[:2000]}

    def _validate_purchase_document(self, conn, business_id: str, values: dict[str, Any], require_supplier: bool) -> dict[str, Any]:
        supplier_id = str(values.get("supplier_id", "")).strip()
        if require_supplier and not supplier_id:
            raise InventoryError("Choose a supplier before saving the purchase document.")
        document_date = _date(values.get("document_date", date.today().isoformat()), "Document date")
        due_date = _date(values.get("due_date", ""), "Due date", optional=True)
        if due_date and due_date < document_date:
            raise InventoryError("Due date cannot be earlier than the document date.")
        items = values.get("items") or []
        if not isinstance(items, list):
            raise InventoryError("Purchase lines are invalid.")
        if not items:
            raise InventoryError("Add at least one product line.")
        return {"supplier_id": supplier_id, "document_date": document_date, "due_date": due_date,
                "notes": str(values.get("notes", "")).strip()[:2000], "items": items}

    def _normalize_product_lines(self, conn, business_id: str, raw_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        rows = []
        subtotal = ZERO
        discounts = ZERO
        taxable_total = ZERO
        tax_total = ZERO
        seen: set[str] = set()
        for index, item in enumerate(raw_items):
            product_id = str(item.get("product_id", "")).strip()
            if not product_id:
                raise InventoryError(f"Line {index + 1}: choose an existing product.")
            product = conn.execute("SELECT * FROM products WHERE business_id=? AND product_id=? AND is_active=1", (business_id, product_id)).fetchone()
            if not product:
                raise InventoryError(f"Line {index + 1}: product is inactive or belongs to another business.")
            if product_id in seen:
                raise InventoryError(f"Line {index + 1}: this product is already on the document. Increase the quantity on its existing line instead.")
            seen.add(product_id)
            quantity = _quantize(_decimal(item.get("quantity", 0), f"Line {index + 1} quantity", minimum=Decimal("0.001")), QUANTITY, f"Line {index + 1} quantity")
            unit_cost = _money(_decimal(item.get("unit_cost", product["last_purchase_price"]), f"Line {index + 1} unit cost"))
            discount_pct = _decimal(item.get("discount_percent", 0), f"Line {index + 1} discount")
            tax_rate = _decimal(item.get("tax_rate", product["tax_rate"]), f"Line {index + 1} tax rate")
            if discount_pct > 100 or tax_rate > 100:
                raise InventoryError(f"Line {index + 1}: discount and tax rates cannot exceed 100%.")
            base = _money(quantity * unit_cost)
            discount = _money(base * discount_pct / Decimal("100"))
            taxable = _money(base - discount)
            tax = _money(taxable * tax_rate / Decimal("100"))
            subtotal += base
            discounts += discount
            taxable_total += taxable
            tax_total += tax
            rows.append({"product_id": product_id, "product_name": str(product["name"]), "sku": str(product["sku"]),
                         "quantity": quantity, "unit": str(product["unit"]), "unit_cost": unit_cost,
                         "discount_percent": discount_pct, "tax_rate": tax_rate, "taxable_value": taxable,
                         "tax_amount": tax, "line_total": _money(taxable + tax)})
        totals = {"subtotal": _money_text(subtotal), "discount_total": _money_text(discounts),
                  "taxable_total": _money_text(taxable_total), "tax_total": _money_text(tax_total),
                  "grand_total": _money_text(taxable_total + tax_total)}
        return rows, totals

    def _insert_purchase_order_items(self, conn, purchase_order_id: str, items: list[dict[str, Any]]) -> None:
        for index, item in enumerate(items):
            conn.execute(
                "INSERT INTO purchase_order_items(purchase_order_item_id,purchase_order_id,row_order,product_id,product_name,sku,quantity,received_quantity,unit,unit_cost,discount_percent,tax_rate,taxable_value,tax_amount,line_total) VALUES(?,?,?,?,?,?,?,'0.000',?,?,?,?,?,?,?)",
                (new_id("POI"), purchase_order_id, index, item["product_id"], item["product_name"], item["sku"], _qty_text(item["quantity"]),
                 item["unit"], _money_text(item["unit_cost"]), str(item["discount_percent"]), str(item["tax_rate"]),
                 _money_text(item["taxable_value"]), _money_text(item["tax_amount"]), _money_text(item["line_total"])),
            )

    def _insert_purchase_items(self, conn, purchase_bill_id: str, items: list[dict[str, Any]]) -> None:
        for index, item in enumerate(items):
            conn.execute(
                "INSERT INTO purchase_items(purchase_item_id,purchase_bill_id,row_order,product_id,product_name,sku,quantity,unit,unit_cost,discount_percent,tax_rate,taxable_value,tax_amount,line_total) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("PBI"), purchase_bill_id, index, item["product_id"], item["product_name"], item["sku"],
                 _qty_text(item["quantity"]), item["unit"], _money_text(item["unit_cost"]), str(item["discount_percent"]),
                 str(item["tax_rate"]), _money_text(item["taxable_value"]), _money_text(item["tax_amount"]), _money_text(item["line_total"])),
            )

    @staticmethod
    def _assert_supplier_invoice_unique(
        conn, business_id: str, supplier_id: str, supplier_invoice_number: str,
        exclude_purchase_bill_id: str | None = None,
    ) -> None:
        reference = supplier_invoice_number.strip()
        if not reference:
            return
        query = (
            "SELECT purchase_number FROM purchase_bills "
            "WHERE business_id=? AND supplier_id=? AND supplier_invoice_number=? COLLATE NOCASE"
        )
        params: list[Any] = [business_id, supplier_id, reference]
        if exclude_purchase_bill_id:
            query += " AND purchase_bill_id<>?"
            params.append(exclude_purchase_bill_id)
        query += " LIMIT 1"
        existing = conn.execute(query, params).fetchone()
        if existing:
            raise InventoryError(
                f"Supplier invoice number '{reference}' is already recorded on {existing['purchase_number']}. "
                "Verify the supplier reference before creating another purchase bill."
            )

    @staticmethod
    def _assert_purchase_order_invoice_available(
        conn, business_id: str, purchase_order_id: str, exclude_purchase_bill_id: str | None = None,
    ) -> None:
        query = (
            "SELECT purchase_number FROM purchase_bills "
            "WHERE business_id=? AND source_purchase_order_id=?"
        )
        params: list[Any] = [business_id, purchase_order_id]
        if exclude_purchase_bill_id:
            query += " AND purchase_bill_id<>?"
            params.append(exclude_purchase_bill_id)
        query += " LIMIT 1"
        existing = conn.execute(query, params).fetchone()
        if existing:
            raise InventoryError(
                f"This purchase order is already linked to supplier bill {existing['purchase_number']}. "
                "A received purchase order can be invoiced only once."
            )

    def _validate_linked_order(self, conn, business_id: str, supplier_id: str, po_id: str, items: list[dict[str, Any]]) -> None:
        order = conn.execute("SELECT * FROM purchase_orders WHERE business_id=? AND purchase_order_id=?", (business_id, po_id)).fetchone()
        if not order or order["supplier_id"] != supplier_id:
            raise InventoryError("The linked purchase order must belong to this business and the selected supplier.")
        if order["status"] != "received":
            raise InventoryError("A purchase bill can be linked only after the purchase order is fully received.")
        self._validate_linked_order_rows(conn, business_id, supplier_id, po_id, items)

    def _validate_linked_order_rows(self, conn, business_id: str, supplier_id: str, po_id: str, bill_items: list[Any]) -> None:
        order = conn.execute(
            "SELECT * FROM purchase_orders WHERE business_id=? AND purchase_order_id=?",
            (business_id, po_id),
        ).fetchone()
        if not order or order["supplier_id"] != supplier_id or order["status"] != "received":
            raise InventoryError("Linked purchase order is not fully received for the selected supplier.")

        order_rows = conn.execute(
            "SELECT product_id,received_quantity,unit_cost,discount_percent,tax_rate FROM purchase_order_items WHERE purchase_order_id=?",
            (po_id,),
        ).fetchall()
        order_by_product = {str(row["product_id"]): row for row in order_rows}
        bill_by_product: dict[str, Any] = {}
        for row in bill_items:
            product_id = str(row["product_id"])
            if product_id in bill_by_product:
                raise InventoryError("A linked purchase bill cannot repeat the same product on multiple lines. Combine its quantities first.")
            bill_by_product[product_id] = row

        if set(order_by_product) != set(bill_by_product):
            raise InventoryError("Linked purchase bill products must match the fully received purchase order exactly.")

        for product_id, order_item in order_by_product.items():
            bill_item = bill_by_product[product_id]
            ordered_qty = _qty(_decimal(order_item["received_quantity"], "Received quantity"))
            billed_qty = _qty(_decimal(bill_item["quantity"], "Purchase quantity"))
            if ordered_qty != billed_qty:
                raise InventoryError("Linked purchase bill quantities must match the fully received purchase order exactly.")
            for field, label in (("unit_cost", "unit cost"), ("discount_percent", "discount"), ("tax_rate", "tax rate")):
                order_value = _decimal(order_item[field], f"Purchase order {label}")
                bill_value = _decimal(bill_item[field], f"Purchase bill {label}")
                if order_value != bill_value:
                    raise InventoryError(
                        f"Linked purchase bill {label} must match the received purchase order. "
                        "KoshFlow will not silently change stock valuation or tax values after receipt. "
                        "A price-variance adjustment workflow is required for differences."
                    )

    def _apply_stock_change(self, conn, business_id: str, product_id: str, delta: Decimal, unit_cost: Decimal,
                            movement_type: str, source_type: str, source_id: str, reason: str,
                            actor_user_id: str, now: str) -> None:
        product = conn.execute("SELECT quantity_on_hand,average_cost FROM products WHERE business_id=? AND product_id=?", (business_id, product_id)).fetchone()
        if not product:
            raise InventoryError("Stock movement product is not in this business.")
        old_qty = _decimal(product["quantity_on_hand"], "Current quantity")
        old_cost = _decimal(product["average_cost"], "Average cost")
        delta = _qty(delta)
        new_qty = _qty(old_qty + delta)
        if new_qty < 0:
            raise InventoryError(f"Stock would become negative. Current stock is {_qty_text(old_qty)}.")
        new_cost = old_cost
        if delta > 0 and unit_cost >= 0 and new_qty > 0:
            new_cost = _money((old_qty * old_cost + delta * unit_cost) / new_qty)
        conn.execute("UPDATE products SET quantity_on_hand=?,average_cost=?,updated_at=? WHERE business_id=? AND product_id=?",
                     (_qty_text(new_qty), _money_text(new_cost), now, business_id, product_id))
        movement_id = new_id("STM")
        conn.execute(
            "INSERT INTO stock_movements(stock_movement_id,business_id,product_id,movement_type,quantity_delta,quantity_before,quantity_after,unit_cost,movement_value,source_type,source_id,reason,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (movement_id, business_id, product_id, movement_type, _qty_text(delta), _qty_text(old_qty), _qty_text(new_qty),
             _money_text(unit_cost), _money_text(abs(delta) * unit_cost), source_type, source_id, reason[:1000], actor_user_id, now),
        )
        AccountingService.post_stock_movement_conn(conn, business_id, actor_user_id, movement_id)

    def _assert_supplier(self, conn, business_id: str, supplier_id: str) -> None:
        row = conn.execute("SELECT is_active FROM suppliers WHERE business_id=? AND supplier_id=?", (business_id, supplier_id)).fetchone()
        if not row or not row["is_active"]:
            raise InventoryError("Select an active supplier from this business.")

    @staticmethod
    def _supplier_balance(conn, business_id: str, supplier_id: str) -> Decimal:
        bills = conn.execute("SELECT grand_total,amount_paid FROM purchase_bills WHERE business_id=? AND supplier_id=? AND status IN ('posted','part_paid','paid')", (business_id, supplier_id)).fetchall()
        returns = conn.execute("SELECT grand_total FROM supplier_returns WHERE business_id=? AND supplier_id=? AND status='posted'", (business_id, supplier_id)).fetchall()
        total = sum((_decimal(row["grand_total"], "Purchase total") for row in bills), ZERO)
        paid = sum((_decimal(row["amount_paid"], "Paid amount") for row in bills), ZERO)
        credits = sum((_decimal(row["grand_total"], "Return total") for row in returns), ZERO)
        return _money(total - paid - credits)

    def _supplier_balance_read(self, business_id: str, supplier_id: str) -> Decimal:
        with self.database.connection() as conn:
            return self._supplier_balance(conn, business_id, supplier_id)

    @staticmethod
    def _purchase_return_total(conn, purchase_bill_id: str) -> Decimal:
        rows = conn.execute("SELECT grand_total FROM supplier_returns WHERE purchase_bill_id=? AND status='posted'", (purchase_bill_id,)).fetchall()
        return _money(sum((_decimal(row["grand_total"], "Return total") for row in rows), ZERO))

    @classmethod
    def _purchase_bill_balance(cls, conn, bill: dict[str, Any]) -> Decimal:
        returned = cls._purchase_return_total(conn, str(bill["purchase_bill_id"]))
        total = _decimal(bill["grand_total"], "Purchase total")
        paid = _decimal(bill["amount_paid"], "Paid amount")
        return _money(total - paid - returned)

    @staticmethod
    def _next_number(conn, table: str, column: str, business_id: str, prefix: str, doc_date: str) -> str:
        year = doc_date[:4]
        token = f"{prefix}-{year}-"
        row = conn.execute(f"SELECT {column} FROM {table} WHERE business_id=? AND {column} LIKE ? ORDER BY {column} DESC LIMIT 1", (business_id, token + "%")).fetchone()
        sequence = 1
        if row:
            try:
                sequence = int(str(row[0]).rsplit("-", 1)[1]) + 1
            except (ValueError, IndexError):
                raise InventoryError("Could not determine the next document number. Contact support before retrying.")
        return f"{token}{sequence:05d}"

    @staticmethod
    def _assert_actor(conn, business_id: str, actor_user_id: str, permission: str) -> None:
        row = conn.execute("SELECT role FROM user_businesses WHERE user_id=? AND business_id=?", (actor_user_id, business_id)).fetchone()
        if not row:
            raise InventoryError("Your user is not a member of this business workspace.")
        if not has_permission(str(row["role"]), permission):
            raise InventoryError("Your current role does not allow this inventory or purchasing action.")

    @staticmethod
    def _audit(conn, business_id: str, actor_user_id: str, action: str, entity_type: str,
               entity_id: str, details: dict[str, Any], now: str) -> None:
        import json
        conn.execute("INSERT INTO audit_logs(audit_id,business_id,actor_user_id,action,entity_type,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (new_id("AUD"), business_id, actor_user_id, action, entity_type, entity_id,
                      json.dumps(details, ensure_ascii=False, default=str), now))

    @staticmethod
    def _translate_integrity(exc: Exception, duplicate_message: str) -> None:
        import sqlite3
        if isinstance(exc, sqlite3.IntegrityError):
            raise InventoryError(duplicate_message) from exc
        raise exc
