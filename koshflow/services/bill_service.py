"""Local bill lifecycle, deterministic totals, payment records and PDF templates.

Purpose: Provide transaction-safe bill CRUD for B2B/B2C sales and reusable PDF themes.
Canonical path: koshflow/services/bill_service.py
Project: KoshFlow | Version: 0.6.0
Developer: Mayank Chawdhari AKA BOSS294
Integration: Use BillService(Database) from the billing pages and tests.
Changelog: v0.6.0 — Integrated sales issuance, payment and cancellation events with the double-entry ledger.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from koshflow.core.database import Database
from koshflow.core.security import new_id, normalize_gstin, validate_gstin
from koshflow.core.permissions import has_permission
from koshflow.services.accounting_service import AccountingService

MONEY = Decimal("0.01")
ZERO = Decimal("0.00")
ALLOWED_DOCUMENT_TYPES = {"tax_invoice", "bill_of_supply", "proforma", "estimate"}
ALLOWED_STATUSES = {"draft", "issued", "part_paid", "paid", "cancelled"}
ALLOWED_PAYMENT_METHODS = {"Cash", "UPI", "Bank transfer", "Card", "Cheque", "Other"}
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BillError(ValueError):
    """Expected bill or template validation error shown to the user."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decimal(value: Any, label: str, *, minimum: Decimal = ZERO) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BillError(f"{label} must be a valid number.") from exc
    if not result.is_finite() or result < minimum:
        raise BillError(f"{label} cannot be negative or invalid.")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _money_text(value: Decimal) -> str:
    return f"{_money(value):.2f}"


class BillService:
    """Own bill validation and persistence; UI widgets never calculate totals."""

    def __init__(self, database: Database):
        self.database = database

    def ensure_default_template(self, business_id: str) -> str:
        """Ensure the business has one default theme, repairing older local state safely."""
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT template_id FROM pdf_templates WHERE business_id = ? AND is_default = 1 LIMIT 1",
                (business_id,),
            ).fetchone()
        if row:
            return str(row["template_id"])

        now = _now()
        with self.database.transaction() as conn:
            existing_classic = conn.execute(
                "SELECT template_id FROM pdf_templates WHERE business_id = ? AND template_name = ?",
                (business_id, "KoshFlow Classic"),
            ).fetchone()
            conn.execute(
                "UPDATE pdf_templates SET is_default = 0 WHERE business_id = ?", (business_id,)
            )
            if existing_classic:
                template_id = str(existing_classic["template_id"])
                conn.execute(
                    "UPDATE pdf_templates SET is_default = 1, updated_at = ? WHERE template_id = ? AND business_id = ?",
                    (now, template_id, business_id),
                )
                return template_id

            template_id = new_id("TPL")
            conn.execute(
                "INSERT INTO pdf_templates(template_id, business_id, template_name, page_size, accent_color, "
                "font_family, font_size, show_logo, show_business_contact, show_gstin, footer_text, layout_json, "
                "is_default, created_at, updated_at) VALUES(?, ?, ?, 'A4', '#C9E86A', 'Unicode Sans', 9, 0, 1, 1, ?, '{}', 1, ?, ?)",
                (template_id, business_id, "KoshFlow Classic", "Thank you for your business.", now, now),
            )
        return template_id

    def ensure_starter_templates(self, business_id: str) -> None:
        """Install a curated set of 20 document themes once for a new business."""
        with self.database.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM pdf_templates WHERE business_id = ?", (business_id,)).fetchone()[0]
        if count:
            self.ensure_default_template(business_id)
            return
        presets = [
            ("KoshFlow Classic", "#C9E86A", "A4", "Unicode Sans", 9, 1),
            ("Mono Ledger", "#242720", "A4", "Helvetica", 9, 0),
            ("Olive Register", "#7F9147", "A4", "Helvetica", 9, 0),
            ("Forest Statement", "#315B43", "A4", "Helvetica", 9, 0),
            ("Cedar Paper", "#8C5A3C", "A4", "Times-Roman", 10, 0),
            ("Burgundy Formal", "#7B3344", "A4", "Times-Roman", 10, 0),
            ("Graphite Invoice", "#444841", "A4", "Helvetica", 9, 0),
            ("Ivory Trade", "#C7A96B", "A4", "Times-Roman", 10, 0),
            ("Terracotta Sales", "#A85F48", "A4", "Helvetica", 9, 0),
            ("Evergreen Goods", "#2E6B57", "A4", "Helvetica", 9, 0),
            ("Sage Minimal", "#A6B89A", "A4", "Helvetica", 9, 0),
            ("Copper Contract", "#B27852", "A4", "Times-Roman", 10, 0),
            ("Charcoal Modern", "#30332E", "A4", "Helvetica", 9, 0),
            ("Olive Compact", "#859447", "A5", "Helvetica", 8, 0),
            ("Cedar Compact", "#8C5A3C", "A5", "Times-Roman", 9, 0),
            ("Market Receipt", "#C9E86A", "THERMAL_80", "Helvetica", 8, 0),
            ("Clean Service", "#788C66", "A4", "Helvetica", 9, 0),
            ("Formal Estimate", "#6D7666", "A4", "Times-Roman", 10, 0),
            ("Supplier Copy", "#B5A27D", "A4", "Helvetica", 9, 0),
            ("Night Ledger", "#575B51", "A4", "Helvetica", 9, 0),
        ]
        now = _now()
        with self.database.transaction() as conn:
            for name, color, size, font, font_size, is_default in presets:
                conn.execute(
                    "INSERT OR IGNORE INTO pdf_templates(template_id, business_id, template_name, page_size, accent_color, font_family, "
                    "font_size, show_logo, show_business_contact, show_gstin, footer_text, layout_json, is_default, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, 0, 1, 1, 'Thank you for your business.', '{}', ?, ?, ?)",
                    (new_id("TPL"), business_id, name, size, color, font, font_size, is_default, now, now),
                )

    def list_templates(self, business_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pdf_templates WHERE business_id = ? ORDER BY is_default DESC, template_name COLLATE NOCASE",
                (business_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_template(self, business_id: str, actor_user_id: str, values: dict[str, Any], template_id: str | None = None) -> str:
        name = str(values.get("template_name", "")).strip()
        if not name:
            raise BillError("Give this PDF theme a name.")
        page_size = str(values.get("page_size", "A4"))
        if page_size not in {"A4", "A5", "THERMAL_80"}:
            raise BillError("Choose a supported page size.")
        color = str(values.get("accent_color", "#C9E86A")).strip()
        if not COLOR_PATTERN.fullmatch(color):
            raise BillError("Accent color must be a six-digit hex color.")
        font_family = str(values.get("font_family", "Helvetica"))
        if font_family not in {"Helvetica", "Times-Roman", "Courier", "Unicode Sans"}:
            font_family = "Helvetica"
        font_size = int(_decimal(values.get("font_size", 9), "Font size", minimum=Decimal(7)))
        if font_size > 18:
            raise BillError("Font size must be between 7 and 18.")
        show_logo = 1 if values.get("show_logo") else 0
        show_contact = 1 if values.get("show_business_contact", True) else 0
        show_gstin = 1 if values.get("show_gstin", True) else 0
        footer = str(values.get("footer_text", "Thank you for your business.")).strip()[:500]
        layout_json = json.dumps(values.get("layout", {}), ensure_ascii=False)
        now = _now()
        template_id = template_id or new_id("TPL")

        try:
            with self.database.transaction() as conn:
                self._assert_actor(conn, business_id, actor_user_id, "billing.theme_manage")
                existing = conn.execute(
                    "SELECT template_id FROM pdf_templates WHERE business_id = ? AND template_name = ? AND template_id <> ?",
                    (business_id, name, template_id),
                ).fetchone()
                if existing:
                    raise BillError("A PDF theme with this name already exists.")
                is_default = 1 if values.get("is_default") else 0
                if is_default:
                    conn.execute("UPDATE pdf_templates SET is_default = 0 WHERE business_id = ?", (business_id,))
                found = conn.execute(
                    "SELECT is_default FROM pdf_templates WHERE template_id = ? AND business_id = ?",
                    (template_id, business_id),
                ).fetchone()
                if found and found["is_default"] and not is_default:
                    raise BillError("Choose another default theme before removing the current default flag.")
                params = (name, page_size, color.upper(), font_family, font_size, show_logo,
                          show_contact, show_gstin, footer, layout_json, is_default, now)
                if found:
                    conn.execute(
                        "UPDATE pdf_templates SET template_name=?, page_size=?, accent_color=?, font_family=?, font_size=?, "
                        "show_logo=?, show_business_contact=?, show_gstin=?, footer_text=?, layout_json=?, is_default=?, updated_at=? "
                        "WHERE template_id=? AND business_id=?",
                        (*params, template_id, business_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO pdf_templates(template_id, business_id, template_name, page_size, accent_color, font_family, "
                        "font_size, show_logo, show_business_contact, show_gstin, footer_text, layout_json, is_default, created_at, updated_at) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (template_id, business_id, name, page_size, color.upper(), font_family, font_size,
                         show_logo, show_contact, show_gstin, footer, layout_json, is_default, now, now),
                    )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise BillError("A PDF theme with this name already exists.") from exc
            raise
        return template_id

    def delete_template(self, business_id: str, actor_user_id: str, template_id: str) -> None:
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "billing.theme_manage")
            row = conn.execute(
                "SELECT is_default FROM pdf_templates WHERE template_id = ? AND business_id = ?",
                (template_id, business_id),
            ).fetchone()
            if not row:
                raise BillError("The selected PDF theme was not found.")
            if row["is_default"]:
                raise BillError("Choose another default theme before deleting this one.")
            conn.execute("DELETE FROM pdf_templates WHERE template_id = ? AND business_id = ?", (template_id, business_id))

    def create_bill(self, business_id: str, actor_user_id: str, values: dict[str, Any]) -> str:
        normalized = self._validate_bill(values)
        now = _now()
        bill_id = new_id("BIL")
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "billing.create")
            self._assert_template_belongs_to_business(conn, business_id, normalized.get("template_id"))
            self._assert_customer_belongs_to_business(conn, business_id, normalized.get("customer_id"))
            self._assert_bill_products(conn, business_id, normalized["items"])
            bill_number = self._next_bill_number(conn, business_id, normalized["invoice_date"])
            totals, rows = self._calculate_items(normalized["items"], normalized["invoice_discount"])
            conn.execute(
                "INSERT INTO bills(bill_id, business_id, customer_id, bill_number, document_type, customer_type, customer_name, "
                "customer_phone, customer_email, customer_gstin, customer_address, place_of_supply, invoice_date, due_date, "
                "notes, terms, subtotal, discount_total, invoice_discount, taxable_total, tax_total, grand_total, amount_paid, status, template_id, "
                "created_by, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '0.00', 'draft', ?, ?, ?, ?)",
                (bill_id, business_id, normalized.get("customer_id"), bill_number, normalized["document_type"], normalized["customer_type"],
                 normalized["customer_name"], normalized["customer_phone"], normalized["customer_email"],
                 normalized["customer_gstin"], normalized["customer_address"], normalized["place_of_supply"],
                 normalized["invoice_date"], normalized["due_date"], normalized["notes"], normalized["terms"],
                 totals["subtotal"], totals["discount_total"], _money_text(normalized["invoice_discount"]),
                 totals["taxable_total"], totals["tax_total"], totals["grand_total"], normalized.get("template_id"), actor_user_id, now, now),
            )
            self._insert_items(conn, bill_id, rows)
            self._audit(conn, business_id, actor_user_id, "bill.created", "bill", bill_id,
                        {"bill_number": bill_number, "status": "draft"}, now)
        return bill_id

    def update_draft(self, business_id: str, actor_user_id: str, bill_id: str, values: dict[str, Any]) -> None:
        normalized = self._validate_bill(values)
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "billing.edit_draft")
            row = conn.execute(
                "SELECT bill_number, status FROM bills WHERE bill_id = ? AND business_id = ?",
                (bill_id, business_id),
            ).fetchone()
            if not row:
                raise BillError("The selected bill was not found.")
            if row["status"] != "draft":
                raise BillError("Only draft bills can be edited. Cancel or reverse an issued bill before correction.")
            self._assert_template_belongs_to_business(conn, business_id, normalized.get("template_id"))
            self._assert_customer_belongs_to_business(conn, business_id, normalized.get("customer_id"))
            self._assert_bill_products(conn, business_id, normalized["items"])
            totals, items = self._calculate_items(normalized["items"], normalized["invoice_discount"])
            conn.execute(
                "UPDATE bills SET customer_id=?, document_type=?, customer_type=?, customer_name=?, customer_phone=?, customer_email=?, "
                "customer_gstin=?, customer_address=?, place_of_supply=?, invoice_date=?, due_date=?, notes=?, terms=?, "
                "subtotal=?, discount_total=?, invoice_discount=?, taxable_total=?, tax_total=?, grand_total=?, template_id=?, updated_at=? "
                "WHERE bill_id=? AND business_id=?",
                (normalized.get("customer_id"), normalized["document_type"], normalized["customer_type"], normalized["customer_name"],
                 normalized["customer_phone"], normalized["customer_email"], normalized["customer_gstin"],
                 normalized["customer_address"], normalized["place_of_supply"], normalized["invoice_date"],
                 normalized["due_date"], normalized["notes"], normalized["terms"], totals["subtotal"],
                 totals["discount_total"], _money_text(normalized["invoice_discount"]), totals["taxable_total"],
                 totals["tax_total"], totals["grand_total"], normalized.get("template_id"), now, bill_id, business_id),
            )
            conn.execute("DELETE FROM bill_items WHERE bill_id = ?", (bill_id,))
            self._insert_items(conn, bill_id, items)
            self._audit(conn, business_id, actor_user_id, "bill.updated", "bill", bill_id,
                        {"bill_number": row["bill_number"]}, now)

    def issue_bill(self, business_id: str, actor_user_id: str, bill_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "billing.issue")
            row = conn.execute(
                "SELECT bill_number, status, grand_total FROM bills WHERE bill_id=? AND business_id=?",
                (bill_id, business_id),
            ).fetchone()
            if not row:
                raise BillError("The selected bill was not found.")
            if row["status"] != "draft":
                raise BillError("Only a draft bill can be issued.")
            item_count = conn.execute("SELECT COUNT(*) FROM bill_items WHERE bill_id=?", (bill_id,)).fetchone()[0]
            if item_count == 0 or Decimal(row["grand_total"]) <= ZERO:
                raise BillError("Add at least one bill item with a positive total before issuing.")
            bill_items = conn.execute(
                "SELECT bill_item_id,product_id,quantity,description,unit FROM bill_items WHERE bill_id=? ORDER BY row_order",
                (bill_id,),
            ).fetchall()
            self._assert_bill_products(conn, business_id, [dict(item) for item in bill_items])
            for item in bill_items:
                product_id = item["product_id"]
                if not product_id:
                    continue  # Free-text service or non-stock line.
                product = conn.execute(
                    "SELECT quantity_on_hand,average_cost,is_active,name FROM products WHERE business_id=? AND product_id=?",
                    (business_id, product_id),
                ).fetchone()
                if not product or not product["is_active"]:
                    raise BillError(f"Catalog product for '{item['description']}' is inactive or unavailable.")
                quantity = _decimal(item["quantity"], "Stock item quantity", minimum=Decimal("0.0001"))
                on_hand = _decimal(product["quantity_on_hand"], "Stock on hand")
                if quantity > on_hand:
                    raise BillError(f"Insufficient stock for {product['name']}. Available: {on_hand}. Required: {quantity}.")
                updated_quantity = (on_hand - quantity).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                conn.execute(
                    "UPDATE products SET quantity_on_hand=?,updated_at=? WHERE business_id=? AND product_id=?",
                    (f"{updated_quantity:.3f}", now, business_id, product_id),
                )
                movement_cost = Decimal(str(product["average_cost"] or "0"))
                conn.execute(
                    "INSERT INTO stock_movements(stock_movement_id,business_id,product_id,movement_type,quantity_delta,quantity_before,quantity_after,unit_cost,movement_value,source_type,source_id,reason,created_by,created_at) VALUES(?,?,?,'sale',?,?,?,?,?,?,?,?,?,?)",
                    (new_id("STM"), business_id, product_id, f"{-quantity:.3f}", f"{on_hand:.3f}", f"{updated_quantity:.3f}",
                     str(movement_cost), f"{(quantity * movement_cost).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}",
                     "bill", bill_id, f"Stock issued on invoice {row['bill_number']}", actor_user_id, now),
                )
            conn.execute("UPDATE bills SET status='issued', issued_at=?, updated_at=? WHERE bill_id=?", (now, now, bill_id))
            self._audit(conn, business_id, actor_user_id, "bill.issued", "bill", bill_id,
                        {"bill_number": row["bill_number"], "inventory_lines": sum(bool(item["product_id"]) for item in bill_items)}, now)
            # Financial journal posting shares the invoice transaction: invoice, stock and ledger
            # either commit together or roll back together.
            AccountingService.post_sales_invoice_conn(conn, business_id, actor_user_id, bill_id)

    def cancel_bill(self, business_id: str, actor_user_id: str, bill_id: str, reason: str) -> None:
        now = _now()
        reason = str(reason).strip()
        if not reason:
            raise BillError("A cancellation reason is required for the audit trail.")
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "billing.cancel")
            row = conn.execute(
                "SELECT bill_number, status, amount_paid FROM bills WHERE bill_id=? AND business_id=?",
                (bill_id, business_id),
            ).fetchone()
            if not row:
                raise BillError("The selected bill was not found.")
            if row["status"] != "issued" or Decimal(row["amount_paid"]) > ZERO:
                raise BillError("Only an unpaid issued bill can be cancelled directly. Drafts may be deleted; paid documents require a proper reversal or credit note.")
            items = conn.execute(
                "SELECT product_id,quantity,description FROM bill_items WHERE bill_id=? AND product_id IS NOT NULL ORDER BY row_order",
                (bill_id,),
            ).fetchall()
            for item in items:
                product = conn.execute(
                    "SELECT quantity_on_hand,average_cost FROM products WHERE business_id=? AND product_id=?",
                    (business_id, item["product_id"]),
                ).fetchone()
                if not product:
                    raise BillError("A stock-tracked product on this invoice is no longer available; cancellation was not completed.")
                quantity = _decimal(item["quantity"], "Stock item quantity", minimum=Decimal("0.0001"))
                restored = (_decimal(product["quantity_on_hand"], "Current stock") + quantity).quantize(
                    Decimal("0.001"), rounding=ROUND_HALF_UP,
                )
                # Restore at the cost captured when the original issue occurred, not the
                # product's possibly changed moving-average cost at cancellation time.
                original_sale = conn.execute(
                    "SELECT unit_cost FROM stock_movements WHERE business_id=? AND product_id=? "
                    "AND movement_type='sale' AND source_type='bill' AND source_id=? ORDER BY created_at LIMIT 1",
                    (business_id, item["product_id"], bill_id),
                ).fetchone()
                restore_cost = str(original_sale["unit_cost"] if original_sale else product["average_cost"])
                conn.execute("UPDATE products SET quantity_on_hand=?,updated_at=? WHERE business_id=? AND product_id=?",
                             (f"{restored:.3f}", now, business_id, item["product_id"]))
                before_quantity = _decimal(product["quantity_on_hand"], "Current stock")
                restore_unit_cost = Decimal(str(restore_cost))
                conn.execute(
                    "INSERT INTO stock_movements(stock_movement_id,business_id,product_id,movement_type,quantity_delta,quantity_before,quantity_after,unit_cost,movement_value,source_type,source_id,reason,created_by,created_at) VALUES(?,?,?,'sale_return',?,?,?,?,?,?,?,?,?,?)",
                    (new_id("STM"), business_id, item["product_id"], f"{quantity:.3f}", f"{before_quantity:.3f}", f"{restored:.3f}",
                     restore_cost, f"{(quantity * restore_unit_cost).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}",
                     "bill_cancellation", bill_id, f"Stock restored after cancelling invoice {row['bill_number']}", actor_user_id, now),
                )
                restored_cost = _money(
                    (_decimal(product["quantity_on_hand"], "Current stock") * _decimal(product["average_cost"], "Average cost")
                     + quantity * _decimal(restore_cost, "Original sale cost")) / restored
                ) if restored > ZERO else _money(_decimal(restore_cost, "Original sale cost"))
                conn.execute("UPDATE products SET average_cost=? WHERE business_id=? AND product_id=?",
                             (f"{restored_cost:.2f}", business_id, item["product_id"]))
            conn.execute("UPDATE bills SET status='cancelled', updated_at=? WHERE bill_id=?", (now, bill_id))
            self._audit(conn, business_id, actor_user_id, "bill.cancelled", "bill", bill_id,
                        {"bill_number": row["bill_number"], "reason": reason, "inventory_lines_restored": len(items)}, now)
            AccountingService.post_sales_invoice_conn(conn, business_id, actor_user_id, bill_id)
            AccountingService._reverse_entry_conn(
                conn, business_id, actor_user_id, "bill", bill_id, "issued", "cancelled",
                datetime.now().astimezone().date().isoformat(),
                f"Cancellation reversal for invoice {row['bill_number']}: {reason[:300]}",
            )

    def delete_draft(self, business_id: str, actor_user_id: str, bill_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "billing.delete_draft")
            row = conn.execute(
                "SELECT bill_number, status FROM bills WHERE bill_id=? AND business_id=?",
                (bill_id, business_id),
            ).fetchone()
            if not row:
                raise BillError("The selected bill was not found.")
            if row["status"] != "draft":
                raise BillError("Only draft bills can be deleted. Issued documents must remain auditable.")
            self._audit(conn, business_id, actor_user_id, "bill.draft_deleted", "bill", bill_id,
                        {"bill_number": row["bill_number"]}, now)
            conn.execute("DELETE FROM bills WHERE bill_id=? AND business_id=?", (bill_id, business_id))

    def record_payment(self, business_id: str, actor_user_id: str, bill_id: str, amount: Any,
                       payment_method: str = "UPI", reference: str = "", paid_at: str | None = None) -> str:
        payment_amount = _money(_decimal(amount, "Payment amount", minimum=Decimal("0.01")))
        if payment_method not in ALLOWED_PAYMENT_METHODS:
            raise BillError("Choose a supported payment method.")
        now = _now()
        payment_id = new_id("PAY")
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "billing.payment")
            row = conn.execute(
                "SELECT grand_total, amount_paid, status, bill_number FROM bills WHERE bill_id=? AND business_id=?",
                (bill_id, business_id),
            ).fetchone()
            if not row:
                raise BillError("The selected bill was not found.")
            if row["status"] not in {"issued", "part_paid"}:
                raise BillError("Payments can only be recorded against issued or partially paid bills.")
            due = _money(Decimal(row["grand_total"]) - Decimal(row["amount_paid"]))
            if payment_amount > due:
                raise BillError(f"Payment exceeds the outstanding balance of {due:.2f}.")
            paid_date = paid_at or date.today().isoformat()
            conn.execute(
                "INSERT INTO bill_payments(payment_id, business_id, bill_id, amount, payment_method, reference, paid_at, created_by, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (payment_id, business_id, bill_id, _money_text(payment_amount), payment_method,
                 str(reference).strip()[:120], paid_date, actor_user_id, now),
            )
            new_paid = _money(Decimal(row["amount_paid"]) + payment_amount)
            status = "paid" if new_paid >= Decimal(row["grand_total"]) else "part_paid"
            conn.execute("UPDATE bills SET amount_paid=?, status=?, updated_at=? WHERE bill_id=?",
                         (_money_text(new_paid), status, now, bill_id))
            self._audit(conn, business_id, actor_user_id, "bill.payment_recorded", "bill", bill_id,
                        {"bill_number": row["bill_number"], "amount": _money_text(payment_amount),
                         "method": payment_method, "status": status}, now)
            AccountingService.post_bill_payment_conn(conn, business_id, actor_user_id, payment_id)
        return payment_id

    def get_bill(self, business_id: str, bill_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT b.*, t.template_name FROM bills b LEFT JOIN pdf_templates t ON t.template_id=b.template_id "
                "WHERE b.bill_id=? AND b.business_id=?", (bill_id, business_id),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["items"] = [dict(item) for item in conn.execute(
                "SELECT * FROM bill_items WHERE bill_id=? ORDER BY row_order", (bill_id,),
            ).fetchall()]
            result["payments"] = [dict(payment) for payment in conn.execute(
                "SELECT * FROM bill_payments WHERE bill_id=? ORDER BY paid_at DESC, created_at DESC", (bill_id,),
            ).fetchall()]
        result["balance_due"] = _money_text(Decimal(result["grand_total"]) - Decimal(result["amount_paid"]))
        return result

    def list_bills(self, business_id: str, search: str = "", status: str = "All", limit: int = 500) -> list[dict[str, Any]]:
        clauses = ["business_id = ?"]
        params: list[Any] = [business_id]
        if search.strip():
            query = f"%{search.strip()}%"
            clauses.append("(bill_number LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ? OR customer_gstin LIKE ?)")
            params.extend([query, query, query, query])
        if status and status != "All":
            if status not in ALLOWED_STATUSES:
                raise BillError("Choose a supported bill status filter.")
            clauses.append("status = ?")
            params.append(status)
        params.append(max(1, min(int(limit), 2000)))
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT bill_id, bill_number, customer_name, customer_type, invoice_date, due_date, status, grand_total, amount_paid "
                f"FROM bills WHERE {' AND '.join(clauses)} ORDER BY invoice_date DESC, created_at DESC LIMIT ?", params,
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["balance_due"] = _money_text(Decimal(item["grand_total"]) - Decimal(item["amount_paid"]))
            results.append(item)
        return results

    def summary(self, business_id: str) -> dict[str, str | int]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT status, grand_total, amount_paid FROM bills WHERE business_id=?", (business_id,),
            ).fetchall()
        issued = [row for row in rows if row["status"] not in {"draft", "cancelled"}]
        due = sum((Decimal(row["grand_total"]) - Decimal(row["amount_paid"]) for row in issued), ZERO)
        paid = sum((Decimal(row["amount_paid"]) for row in rows), ZERO)
        return {
            "total_bills": len(rows), "drafts": sum(row["status"] == "draft" for row in rows),
            "issued": sum(row["status"] == "issued" for row in rows),
            "paid": sum(row["status"] == "paid" for row in rows),
            "outstanding": _money_text(due), "collected": _money_text(paid),
        }

    def _validate_bill(self, values: dict[str, Any]) -> dict[str, Any]:
        name = str(values.get("customer_name", "")).strip()
        if not name:
            raise BillError("Customer or party name is required.")
        customer_type = str(values.get("customer_type", "B2C"))
        if customer_type not in {"B2B", "B2C"}:
            raise BillError("Choose B2B or B2C customer type.")
        doc_type = str(values.get("document_type", "tax_invoice"))
        if doc_type not in ALLOWED_DOCUMENT_TYPES:
            raise BillError("Choose a supported document type.")
        gstin = normalize_gstin(str(values.get("customer_gstin", "")))
        if customer_type == "B2B" and not gstin:
            raise BillError("A GSTIN is required for B2B customer records in this billing workflow.")
        if error := validate_gstin(gstin):
            raise BillError(error)
        invoice_date = str(values.get("invoice_date", date.today().isoformat()))
        due_date = str(values.get("due_date", "")).strip()
        for field, value in (("Invoice date", invoice_date), ("Due date", due_date)):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise BillError(f"{field} must use YYYY-MM-DD format.") from exc
        if due_date and due_date < invoice_date:
            raise BillError("Due date cannot be earlier than the invoice date.")
        items = values.get("items") or []
        if not isinstance(items, list):
            raise BillError("Bill items are invalid.")
        invoice_discount = _decimal(values.get("invoice_discount", 0), "Invoice discount")
        normalized_items = []
        for index, item in enumerate(items, start=1):
            description = str(item.get("description", "")).strip()
            if not description:
                raise BillError(f"Item {index}: description is required.")
            quantity = _decimal(item.get("quantity", 1), f"Item {index} quantity", minimum=Decimal("0.0001"))
            price = _decimal(item.get("unit_price", 0), f"Item {index} price")
            discount = _decimal(item.get("discount_percent", 0), f"Item {index} discount")
            tax_rate = _decimal(item.get("tax_rate", 0), f"Item {index} tax rate")
            if discount > 100:
                raise BillError(f"Item {index} discount cannot exceed 100%.")
            if tax_rate > 100:
                raise BillError(f"Item {index} tax rate cannot exceed 100%.")
            normalized_items.append({
                "product_id": str(item.get("product_id") or "").strip() or None,
                "description": description[:250], "hsn_sac": str(item.get("hsn_sac", "")).strip()[:20],
                "quantity": quantity, "unit": str(item.get("unit", "pcs")).strip()[:20] or "pcs",
                "unit_price": price, "discount_percent": discount, "tax_rate": tax_rate,
            })
        if invoice_discount > Decimal(self._calculate_items(normalized_items, ZERO)[0]["taxable_total"]):
            raise BillError("Invoice discount cannot exceed the taxable value.")
        raw_template_id = values.get("template_id")
        template_id = str(raw_template_id).strip() if raw_template_id else None
        return {
            "customer_id": str(values.get("customer_id") or "").strip() or None,
            "customer_name": name[:180], "customer_type": customer_type, "document_type": doc_type,
            "customer_phone": str(values.get("customer_phone", "")).strip()[:40],
            "customer_email": str(values.get("customer_email", "")).strip()[:180],
            "customer_gstin": gstin, "customer_address": str(values.get("customer_address", "")).strip()[:1000],
            "place_of_supply": str(values.get("place_of_supply", "")).strip()[:100], "invoice_date": invoice_date,
            "due_date": due_date, "notes": str(values.get("notes", "")).strip()[:2000],
            "terms": str(values.get("terms", "")).strip()[:2000], "items": normalized_items,
            "invoice_discount": invoice_discount, "template_id": template_id,
        }

    @staticmethod
    def _calculate_items(items: list[dict[str, Any]], invoice_discount: Decimal) -> tuple[dict[str, str], list[dict[str, Any]]]:
        prepared = []
        raw_subtotal = ZERO
        line_discount_total = ZERO
        pre_tax_total = ZERO
        for item in items:
            qty = item["quantity"] if isinstance(item["quantity"], Decimal) else _decimal(item["quantity"], "Quantity")
            price = item["unit_price"] if isinstance(item["unit_price"], Decimal) else _decimal(item["unit_price"], "Price")
            disc_pct = item["discount_percent"] if isinstance(item["discount_percent"], Decimal) else _decimal(item["discount_percent"], "Discount")
            tax_rate = item["tax_rate"] if isinstance(item["tax_rate"], Decimal) else _decimal(item["tax_rate"], "Tax rate")
            base = _money(qty * price)
            line_disc = _money(base * disc_pct / Decimal("100"))
            taxable_before_invoice_disc = _money(base - line_disc)
            raw_subtotal += base
            line_discount_total += line_disc
            pre_tax_total += taxable_before_invoice_disc
            prepared.append({**item, "quantity": qty, "unit_price": price, "discount_percent": disc_pct,
                             "tax_rate": tax_rate, "_base": base, "_line_discount": line_disc,
                             "_pre_tax": taxable_before_invoice_disc})
        invoice_discount = min(_money(invoice_discount), _money(pre_tax_total))
        grand_taxable = ZERO
        grand_tax = ZERO
        results = []
        allocated = ZERO
        for index, item in enumerate(prepared):
            if index == len(prepared) - 1:
                discount_share = _money(invoice_discount - allocated)
            elif pre_tax_total > ZERO:
                discount_share = _money(invoice_discount * item["_pre_tax"] / pre_tax_total)
                allocated += discount_share
            else:
                discount_share = ZERO
            taxable = _money(max(ZERO, item["_pre_tax"] - discount_share))
            tax = _money(taxable * item["tax_rate"] / Decimal("100"))
            total = _money(taxable + tax)
            grand_taxable += taxable
            grand_tax += tax
            results.append({
                **item, "taxable_value": _money_text(taxable), "tax_amount": _money_text(tax),
                "line_total": _money_text(total),
            })
        totals = {
            "subtotal": _money_text(_money(raw_subtotal)),
            "discount_total": _money_text(_money(line_discount_total + invoice_discount)),
            "taxable_total": _money_text(_money(grand_taxable)), "tax_total": _money_text(_money(grand_tax)),
            "grand_total": _money_text(_money(grand_taxable + grand_tax)),
        }
        return totals, results

    @staticmethod
    def _assert_customer_belongs_to_business(conn, business_id: str, customer_id: str | None) -> None:
        if not customer_id:
            return
        row = conn.execute("SELECT is_active FROM customers WHERE business_id=? AND customer_id=?", (business_id, customer_id)).fetchone()
        if not row or not row["is_active"]:
            raise BillError("Selected customer is inactive or belongs to another business.")

    @staticmethod
    def _assert_bill_products(conn, business_id: str, items: list[dict[str, Any]]) -> None:
        """Ensure every linked catalog product is active and owned by this business."""
        for item in items:
            product_id = item.get("product_id")
            if not product_id:
                continue
            product = conn.execute(
                "SELECT name,unit,is_active FROM products WHERE product_id=? AND business_id=?",
                (product_id, business_id),
            ).fetchone()
            if not product or not product["is_active"]:
                raise BillError(f"The linked catalog product for '{item.get('description', 'line item')}' is inactive or belongs to another business.")
            catalog_unit = str(product["unit"]).strip()
            bill_unit = str(item.get("unit", "pcs")).strip()
            if catalog_unit.casefold() != bill_unit.casefold():
                raise BillError(
                    f"Unit for linked catalog product '{product['name']}' must match its catalog unit "
                    f"'{catalog_unit}'. Unit conversion is not supported."
                )
            quantity = _decimal(item.get("quantity", "0"), "Stock item quantity", minimum=Decimal("0.0001"))
            if quantity.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP) != quantity:
                raise BillError(
                    f"Quantity for linked catalog product '{product['name']}' supports at most three decimal places."
                )

    @staticmethod
    def _assert_actor(conn, business_id: str, actor_user_id: str, permission: str) -> None:
        row = conn.execute(
            "SELECT role FROM user_businesses WHERE user_id=? AND business_id=?",
            (actor_user_id, business_id),
        ).fetchone()
        if not row:
            raise BillError("Your user is not a member of this business workspace.")
        if not has_permission(str(row["role"]), permission):
            raise BillError("Your current role does not allow this billing action.")

    @staticmethod
    def _assert_template_belongs_to_business(conn, business_id: str, template_id: str | None) -> None:
        if not template_id:
            return
        row = conn.execute(
            "SELECT 1 FROM pdf_templates WHERE template_id=? AND business_id=?", (template_id, business_id)
        ).fetchone()
        if not row:
            raise BillError("The selected PDF theme does not belong to this business.")

    @staticmethod
    def _insert_items(conn, bill_id: str, items: list[dict[str, Any]]) -> None:
        for order, item in enumerate(items):
            conn.execute(
                "INSERT INTO bill_items(bill_item_id, bill_id, product_id, row_order, description, hsn_sac, quantity, unit, unit_price, "
                "discount_percent, tax_rate, taxable_value, tax_amount, line_total) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("BIT"), bill_id, item.get("product_id"), order, item["description"], item.get("hsn_sac", ""), str(item["quantity"]),
                 item.get("unit", "pcs"), str(item["unit_price"]), str(item["discount_percent"]), str(item["tax_rate"]),
                 item["taxable_value"], item["tax_amount"], item["line_total"]),
            )

    @staticmethod
    def _next_bill_number(conn, business_id: str, invoice_date: str) -> str:
        year = invoice_date[:4]
        prefix = f"KF-{year}-"
        row = conn.execute(
            "SELECT bill_number FROM bills WHERE business_id=? AND bill_number LIKE ? ORDER BY bill_number DESC LIMIT 1",
            (business_id, prefix + "%"),
        ).fetchone()
        sequence = 1
        if row:
            try:
                sequence = int(str(row["bill_number"]).rsplit("-", 1)[1]) + 1
            except (ValueError, IndexError):
                sequence = int(datetime.now().timestamp()) % 100000
        return f"{prefix}{sequence:05d}"

    @staticmethod
    def _audit(conn, business_id: str, actor_user_id: str, action: str, entity_type: str,
               entity_id: str, details: dict[str, Any], now: str) -> None:
        conn.execute(
            "INSERT INTO audit_logs(audit_id, business_id, actor_user_id, action, entity_type, entity_id, details_json, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("AUD"), business_id, actor_user_id, action, entity_type, entity_id,
             json.dumps(details, ensure_ascii=False, default=str), now),
        )
