"""Business-scoped operational reports built from local transactional records.

Purpose: Provide testable source-data reports for inventory, parties, sales and payments.
Project: KoshFlow | Version: 0.6.2
Canonical path: koshflow/services/operational_report_service.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: AccountingReportsPage delegates operational reports here and exports displayed rows to PDF/CSV.
Changelog: v0.6.2 — Added structured operational reports for stock, customer/supplier balances and payment registers.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from koshflow.core.database import Database

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _dec(value: Any) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
        return result if result.is_finite() else ZERO
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _money(value: Any) -> str:
    return f"{_dec(value).quantize(CENT, rounding=ROUND_HALF_UP):,.2f}"


class OperationalReportService:
    """Read-only report queries with dates and business scope passed explicitly."""

    REPORTS = {
        "Inventory valuation", "Low stock report", "Stock movement register", "Customer balances",
        "Supplier payables", "Top selling products", "Customer sales summary", "Supplier purchase summary",
        "Customer payment register", "Supplier payment register",
    }
    CURRENT_STATE_REPORTS = {"Inventory valuation", "Low stock report", "Customer balances", "Supplier payables"}

    HEADERS: dict[str, list[str]] = {
        "Inventory valuation": ["SKU", "Product", "Category", "On hand", "Unit", "Average cost", "Stock value", "Reorder level"],
        "Low stock report": ["SKU", "Product", "Category", "On hand", "Reorder level", "Shortfall", "Unit", "Status"],
        "Stock movement register": ["Date/time", "Type", "SKU", "Product", "Change", "Before", "After", "Unit cost", "Value", "Source", "Reason", "User"],
        "Customer balances": ["Customer", "Phone", "Open invoices", "Invoiced", "Paid", "Outstanding", "Overdue"],
        "Supplier payables": ["Supplier", "Phone", "Open bills", "Billed", "Paid", "Credits/returns", "Payable", "Overdue"],
        "Top selling products": ["SKU", "Product", "Units sold", "Taxable sales", "Tax", "Invoice count"],
        "Customer sales summary": ["Customer", "Phone", "Invoices", "Taxable sales", "Tax", "Total billed", "Paid (recorded)", "Outstanding"],
        "Supplier purchase summary": ["Supplier", "GSTIN", "Bills", "Taxable purchases", "Input tax", "Total billed", "Paid (recorded)", "Payable"],
        "Customer payment register": ["Date/time", "Receipt", "Invoice", "Customer", "Amount", "Method", "Reference"],
        "Supplier payment register": ["Date/time", "Payment", "Purchase bill", "Supplier", "Amount", "Method", "Reference"],
    }

    def __init__(self, database: Database):
        self.database = database

    def report(self, kind: str, business_id: str, start: str, end: str) -> dict[str, Any]:
        if kind not in self.REPORTS:
            raise ValueError(f"Unsupported operational report: {kind}")
        if not business_id:
            raise ValueError("A business workspace is required.")
        if start > end:
            raise ValueError("Report start date must be on or before the end date.")
        headers = list(self.HEADERS[kind])
        rows: list[list[Any]] = []
        summary = ""
        # All monetary calculations happen in Decimal after retrieving stored decimal-text values.
        with self.database.connection() as conn:
            if kind == "Inventory valuation":
                records = conn.execute(
                    "SELECT sku,name,category,quantity_on_hand,unit,average_cost,reorder_level "
                    "FROM products WHERE business_id=? AND is_active=1 ORDER BY name COLLATE NOCASE",
                    (business_id,),
                ).fetchall()
                total_value = ZERO
                for r in records:
                    qty, cost = _dec(r["quantity_on_hand"]), _dec(r["average_cost"])
                    value = (qty * cost).quantize(CENT, rounding=ROUND_HALF_UP)
                    total_value += value
                    rows.append([r["sku"], r["name"], r["category"], str(qty), r["unit"], _money(cost), _money(value), str(r["reorder_level"])])
                # Do not aggregate quantities across unrelated units (pcs, kg, litre, etc.).
                rows.append(["", "TOTAL INVENTORY VALUE", "", "", "", "", _money(total_value), ""])
                summary = f"Inventory as of {end} · {len(records)} active products · Value ₹{_money(total_value)} · On-hand quantity × moving-average cost. This is a current-state valuation, not a historic stock snapshot."

            elif kind == "Low stock report":
                records = conn.execute(
                    "SELECT sku,name,category,quantity_on_hand,reorder_level,unit FROM products "
                    "WHERE business_id=? AND is_active=1 ORDER BY name COLLATE NOCASE", (business_id,),
                ).fetchall()
                for r in records:
                    qty, reorder = _dec(r["quantity_on_hand"]), _dec(r["reorder_level"])
                    if reorder > 0 and qty <= reorder:
                        rows.append([r["sku"], r["name"], r["category"], str(qty), str(reorder), str(max(Decimal("0"), reorder-qty)), r["unit"], "OUT OF STOCK" if qty <= 0 else "LOW STOCK"])
                summary = f"Low stock as of {end} · {len(rows)} products at or below their configured reorder level. Products with no reorder level configured are not included."

            elif kind == "Stock movement register":
                records = conn.execute(
                    "SELECT m.created_at,m.movement_type,p.sku,p.name,m.quantity_delta,m.quantity_before,m.quantity_after,"
                    "m.unit_cost,m.movement_value,m.source_type,m.source_id,m.reason,u.display_name "
                    "FROM stock_movements m JOIN products p ON p.product_id=m.product_id "
                    "LEFT JOIN users u ON u.user_id=m.created_by WHERE m.business_id=? "
                    "AND substr(m.created_at,1,10) BETWEEN ? AND ? ORDER BY m.created_at,m.stock_movement_id",
                    (business_id, start, end),
                ).fetchall()
                for r in records:
                    source = f"{r['source_type']} · {r['source_id']}".strip(" ·")
                    rows.append([r["created_at"], r["movement_type"], r["sku"], r["name"], str(r["quantity_delta"]), str(r["quantity_before"]), str(r["quantity_after"]), _money(r["unit_cost"]), _money(r["movement_value"]), source, r["reason"], r["display_name"] or "System"])
                total_value = sum((_dec(r["movement_value"]) for r in records), ZERO)
                summary = f"Stock movements {start} to {end} · {len(records)} source-linked movement(s) · Signed movement value total ₹{_money(total_value)}."

            elif kind == "Customer balances":
                records = conn.execute(
                    "SELECT customer_id,customer_name,customer_phone,bill_number,due_date,grand_total,amount_paid "
                    "FROM bills WHERE business_id=? AND status IN ('issued','part_paid') "
                    "ORDER BY customer_name COLLATE NOCASE,due_date", (business_id,),
                ).fetchall()
                groups: dict[tuple[str, str, str], dict[str, Any]] = {}
                for r in records:
                    total, paid = _dec(r["grand_total"]), _dec(r["amount_paid"])
                    balance = max(ZERO, total - paid)
                    if balance <= ZERO:
                        continue
                    key = (str(r["customer_id"] or ""), str(r["customer_name"] or "Walk-in Customer"), str(r["customer_phone"] or ""))
                    g = groups.setdefault(key, {"count": 0, "billed": ZERO, "paid": ZERO, "outstanding": ZERO, "overdue": ZERO})
                    g["count"] += 1
                    g["billed"] += total
                    g["paid"] += paid
                    g["outstanding"] += balance
                    if r["due_date"] and str(r["due_date"]) < end:
                        g["overdue"] += balance
                for key, g in sorted(groups.items(), key=lambda item: item[1]["outstanding"], reverse=True):
                    rows.append([key[1], key[2], g["count"], _money(g["billed"]), _money(g["paid"]), _money(g["outstanding"]), _money(g["overdue"])])
                rows.append(["TOTAL", "", sum(g["count"] for g in groups.values()), _money(sum((g["billed"] for g in groups.values()), ZERO)), _money(sum((g["paid"] for g in groups.values()), ZERO)), _money(sum((g["outstanding"] for g in groups.values()), ZERO)), _money(sum((g["overdue"] for g in groups.values()), ZERO))])
                summary = f"Customer balances as of {end} · {len(groups)} customers with outstanding invoices. Balances include all currently open issued invoices."

            elif kind == "Supplier payables":
                records = conn.execute(
                    "SELECT pb.supplier_id,s.name,s.phone,pb.purchase_bill_id,pb.purchase_number,pb.due_date,pb.grand_total,pb.amount_paid "
                    "FROM purchase_bills pb JOIN suppliers s ON s.supplier_id=pb.supplier_id "
                    "WHERE pb.business_id=? AND pb.status IN ('posted','part_paid') ORDER BY s.name COLLATE NOCASE,pb.due_date",
                    (business_id,),
                ).fetchall()
                groups: dict[tuple[str, str, str], dict[str, Any]] = {}
                for r in records:
                    total, paid = _dec(r["grand_total"]), _dec(r["amount_paid"])
                    credit_rows = conn.execute(
                        "SELECT grand_total FROM supplier_returns WHERE business_id=? AND purchase_bill_id=? AND status='posted'",
                        (business_id, r["purchase_bill_id"]),
                    ).fetchall()
                    # Stored money values are decimal text. Sum them as Decimal instead of
                    # asking SQLite NUMERIC aggregation to round through binary floating point.
                    credit = sum((_dec(credit_row["grand_total"]) for credit_row in credit_rows), ZERO).quantize(CENT, rounding=ROUND_HALF_UP)
                    balance = max(ZERO, total - paid - credit)
                    if balance <= ZERO and credit <= ZERO:
                        continue
                    key = (str(r["supplier_id"]), str(r["name"]), str(r["phone"] or ""))
                    g = groups.setdefault(key, {"count": 0, "billed": ZERO, "paid": ZERO, "credits": ZERO, "balance": ZERO, "overdue": ZERO})
                    g["count"] += 1
                    g["billed"] += total
                    g["paid"] += paid
                    g["credits"] += credit
                    g["balance"] += balance
                    if r["due_date"] and str(r["due_date"]) < end:
                        g["overdue"] += balance
                headers = list(self.HEADERS[kind])
                for key, g in sorted(groups.items(), key=lambda item: item[1]["balance"], reverse=True):
                    rows.append([key[1], key[2], g["count"], _money(g["billed"]), _money(g["paid"]), _money(g["credits"]), _money(g["balance"]), _money(g["overdue"])])
                rows.append(["TOTAL", "", sum(g["count"] for g in groups.values()), _money(sum((g["billed"] for g in groups.values()), ZERO)), _money(sum((g["paid"] for g in groups.values()), ZERO)), _money(sum((g["credits"] for g in groups.values()), ZERO)), _money(sum((g["balance"] for g in groups.values()), ZERO)), _money(sum((g["overdue"] for g in groups.values()), ZERO))])
                summary = f"Supplier payables as of {end} · {len(groups)} suppliers with outstanding bills or posted returns. Posted supplier returns are shown as credits against their source bill."

            elif kind == "Top selling products":
                records = conn.execute(
                    "SELECT bi.product_id,bi.description,bi.quantity,bi.taxable_value,bi.tax_amount,b.bill_id,p.sku "
                    "FROM bill_items bi JOIN bills b ON b.bill_id=bi.bill_id LEFT JOIN products p ON p.product_id=bi.product_id "
                    "WHERE b.business_id=? AND b.invoice_date BETWEEN ? AND ? AND b.status IN ('issued','part_paid','paid') ORDER BY b.invoice_date",
                    (business_id, start, end),
                ).fetchall()
                groups: dict[tuple[str, str], dict[str, Any]] = {}
                for r in records:
                    key = (str(r["product_id"] or r["description"]), str(r["description"]))
                    g = groups.setdefault(key, {"sku": str(r["sku"] or ""), "qty": Decimal("0"), "sales": ZERO, "tax": ZERO, "bills": set()})
                    g["qty"] += _dec(r["quantity"])
                    g["sales"] += _dec(r["taxable_value"])
                    g["tax"] += _dec(r["tax_amount"])
                    g["bills"].add(str(r["bill_id"]))
                for key, g in sorted(groups.items(), key=lambda item: item[1]["sales"], reverse=True):
                    rows.append([g["sku"], key[1], str(g["qty"]), _money(g["sales"]), _money(g["tax"]), len(g["bills"])])
                summary = f"Top selling products {start} to {end} · {len(groups)} product/description line(s), ranked by taxable sales."

            elif kind == "Customer sales summary":
                records = conn.execute(
                    "SELECT customer_id,customer_name,customer_phone,taxable_total,tax_total,grand_total,amount_paid FROM bills "
                    "WHERE business_id=? AND invoice_date BETWEEN ? AND ? AND status IN ('issued','part_paid','paid') ORDER BY customer_name COLLATE NOCASE",
                    (business_id, start, end),
                ).fetchall()
                groups: dict[tuple[str, str, str], dict[str, Any]] = {}
                for r in records:
                    key = (str(r["customer_id"] or ""), str(r["customer_name"] or "Walk-in Customer"), str(r["customer_phone"] or ""))
                    g = groups.setdefault(key, {"count": 0, "taxable": ZERO, "tax": ZERO, "total": ZERO, "paid": ZERO, "out": ZERO})
                    total, paid = _dec(r["grand_total"]), _dec(r["amount_paid"])
                    g["count"] += 1; g["taxable"] += _dec(r["taxable_total"]); g["tax"] += _dec(r["tax_total"])
                    g["total"] += total; g["paid"] += paid; g["out"] += max(ZERO, total-paid)
                for key, g in sorted(groups.items(), key=lambda item: item[1]["total"], reverse=True):
                    rows.append([key[1], key[2], g["count"], _money(g["taxable"]), _money(g["tax"]), _money(g["total"]), _money(g["paid"]), _money(g["out"])])
                summary = f"Customer sales summary {start} to {end} · {len(groups)} customers. Paid and outstanding are current invoice balances, not a cash-receipts measure for this period."

            elif kind == "Supplier purchase summary":
                records = conn.execute(
                    "SELECT s.name,s.gstin,pb.taxable_total,pb.tax_total,pb.grand_total,pb.amount_paid FROM purchase_bills pb "
                    "JOIN suppliers s ON s.supplier_id=pb.supplier_id WHERE pb.business_id=? AND pb.purchase_date BETWEEN ? AND ? "
                    "AND pb.status IN ('posted','part_paid','paid') ORDER BY s.name COLLATE NOCASE", (business_id, start, end),
                ).fetchall()
                groups: dict[tuple[str, str], dict[str, Any]] = {}
                for r in records:
                    key = (str(r["name"]), str(r["gstin"] or ""))
                    g = groups.setdefault(key, {"count": 0, "taxable": ZERO, "tax": ZERO, "total": ZERO, "paid": ZERO, "out": ZERO})
                    total, paid = _dec(r["grand_total"]), _dec(r["amount_paid"])
                    g["count"] += 1; g["taxable"] += _dec(r["taxable_total"]); g["tax"] += _dec(r["tax_total"])
                    g["total"] += total; g["paid"] += paid; g["out"] += max(ZERO, total-paid)
                for key, g in sorted(groups.items(), key=lambda item: item[1]["total"], reverse=True):
                    rows.append([key[0], key[1], g["count"], _money(g["taxable"]), _money(g["tax"]), _money(g["total"]), _money(g["paid"]), _money(g["out"])])
                summary = f"Supplier purchase summary {start} to {end} · {len(groups)} suppliers."

            elif kind == "Customer payment register":
                records = conn.execute(
                    "SELECT bp.paid_at,bp.payment_id,b.bill_number,b.customer_name,bp.amount,bp.payment_method,bp.reference FROM bill_payments bp "
                    "JOIN bills b ON b.bill_id=bp.bill_id WHERE bp.business_id=? AND substr(bp.paid_at,1,10) BETWEEN ? AND ? ORDER BY bp.paid_at,bp.payment_id",
                    (business_id, start, end),
                ).fetchall()
                for r in records:
                    rows.append([r["paid_at"], r["payment_id"], r["bill_number"], r["customer_name"], _money(r["amount"]), r["payment_method"], r["reference"]])
                total = sum((_dec(r["amount"]) for r in records), ZERO)
                rows.append(["", "TOTAL", "", "", _money(total), "", ""])
                summary = f"Customer receipts {start} to {end} · {len(records)} receipt(s) · Total ₹{_money(total)}."

            else:  # Supplier payment register
                records = conn.execute(
                    "SELECT sp.paid_at,sp.supplier_payment_id,pb.purchase_number,s.name,sp.amount,sp.payment_method,sp.reference "
                    "FROM supplier_payments sp JOIN purchase_bills pb ON pb.purchase_bill_id=sp.purchase_bill_id "
                    "JOIN suppliers s ON s.supplier_id=sp.supplier_id WHERE sp.business_id=? AND substr(sp.paid_at,1,10) BETWEEN ? AND ? "
                    "ORDER BY sp.paid_at,sp.supplier_payment_id", (business_id, start, end),
                ).fetchall()
                for r in records:
                    rows.append([r["paid_at"], r["supplier_payment_id"], r["purchase_number"], r["name"], _money(r["amount"]), r["payment_method"], r["reference"]])
                total = sum((_dec(r["amount"]) for r in records), ZERO)
                rows.append(["", "TOTAL", "", "", _money(total), "", ""])
                summary = f"Supplier payments {start} to {end} · {len(records)} payment(s) · Total ₹{_money(total)}."

        return {"report_type": kind, "headers": headers, "rows": rows, "summary": summary, "start_date": start, "end_date": end}
