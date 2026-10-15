"""Real-data dashboard queries for KoshFlow.

Purpose: Aggregate connected sales, purchasing, inventory, contact, due-date and audit data
         without fabricated metrics; monetary values remain Decimal-backed strings.
Project: KoshFlow | Version: 0.6.3
Canonical path: koshflow/services/dashboard_service.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: DashboardPage calls DashboardService.snapshot(business_id, period).
Changelog: v0.6.3 — Normalized legacy status casing and invoice date matching so older issued/paid bills remain visible in dashboard totals.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from koshflow.config import DEFAULT_TIMEZONE
from koshflow.core.database import Database

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
ACTIVE_BILL_STATUSES = ("issued", "part_paid", "paid")
ACTIVE_PURCHASE_STATUSES = ("posted", "part_paid", "paid")


def decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
        return result if result.is_finite() else ZERO
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


def money(value: Any) -> Decimal:
    return decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money_text(value: Any) -> str:
    return f"{money(value):.2f}"


def _sum(rows, key: str) -> Decimal:
    return sum((decimal(row[key]) for row in rows), ZERO).quantize(CENT, rounding=ROUND_HALF_UP)


class DashboardService:
    """Read-only aggregation service scoped to one business workspace."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def period_range(period: str, today: date | None = None) -> tuple[date, date]:
        current = today or datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()
        if period == "Today":
            return current, current
        if period == "Last 7 days":
            return current - timedelta(days=6), current
        if period == "This month":
            return current.replace(day=1), current
        if period == "This quarter":
            first_month = ((current.month - 1) // 3) * 3 + 1
            return current.replace(month=first_month, day=1), current
        if period == "Financial year":
            year = current.year if current.month >= 4 else current.year - 1
            return date(year, 4, 1), current
        return current - timedelta(days=6), current

    def snapshot(self, business_id: str, period: str = "Last 7 days", today: date | None = None) -> dict[str, Any]:
        current = today or datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()
        start, end = self.period_range(period, current)
        start_s, end_s, today_s = start.isoformat(), end.isoformat(), current.isoformat()
        future_s = (current + timedelta(days=14)).isoformat()

        with self.database.connection() as conn:
            sales = [dict(r) for r in conn.execute(
                "SELECT bill_id,bill_number,customer_id,customer_name,customer_phone,invoice_date,due_date,"
                "subtotal,taxable_total,tax_total,grand_total,amount_paid,status FROM bills "
                "WHERE business_id=? AND date(substr(invoice_date,1,10)) BETWEEN date(?) AND date(?) AND LOWER(TRIM(status)) IN ('issued','part_paid','paid') "
                "ORDER BY invoice_date DESC,created_at DESC", (business_id, start_s, end_s),
            ).fetchall()]
            all_open_sales = [dict(r) for r in conn.execute(
                "SELECT bill_id,bill_number,customer_name,invoice_date,due_date,grand_total,amount_paid,status "
                "FROM bills WHERE business_id=? AND LOWER(TRIM(status)) IN ('issued','part_paid') ORDER BY due_date,bill_number",
                (business_id,),
            ).fetchall()]
            purchases = [dict(r) for r in conn.execute(
                "SELECT pb.purchase_bill_id,pb.purchase_number,pb.supplier_invoice_number,pb.purchase_date,pb.due_date,"
                "pb.grand_total,pb.amount_paid,pb.status,s.name AS supplier_name "
                "FROM purchase_bills pb JOIN suppliers s ON s.supplier_id=pb.supplier_id "
                "WHERE pb.business_id=? AND date(substr(pb.purchase_date,1,10)) BETWEEN date(?) AND date(?) AND LOWER(TRIM(pb.status)) IN ('posted','part_paid','paid') "
                "ORDER BY pb.purchase_date DESC,pb.created_at DESC", (business_id, start_s, end_s),
            ).fetchall()]
            all_open_purchases = [dict(r) for r in conn.execute(
                "SELECT pb.purchase_bill_id,pb.purchase_number,pb.purchase_date,pb.due_date,pb.grand_total,pb.amount_paid,"
                "pb.status,s.name AS supplier_name FROM purchase_bills pb JOIN suppliers s ON s.supplier_id=pb.supplier_id "
                "WHERE pb.business_id=? AND LOWER(TRIM(pb.status)) IN ('posted','part_paid') ORDER BY pb.due_date,pb.purchase_number",
                (business_id,),
            ).fetchall()]
            customer_receipts = [dict(r) for r in conn.execute(
                "SELECT amount,paid_at FROM bill_payments WHERE business_id=? AND substr(paid_at,1,10) BETWEEN ? AND ?",
                (business_id, start_s, end_s),
            ).fetchall()]
            supplier_payments = [dict(r) for r in conn.execute(
                "SELECT amount,paid_at FROM supplier_payments WHERE business_id=? AND substr(paid_at,1,10) BETWEEN ? AND ?",
                (business_id, start_s, end_s),
            ).fetchall()]
            products = [dict(r) for r in conn.execute(
                "SELECT product_id,sku,name,category,unit,average_cost,selling_price,quantity_on_hand,reorder_level,is_active "
                "FROM products WHERE business_id=? AND is_active=1 ORDER BY name COLLATE NOCASE", (business_id,),
            ).fetchall()]
            customer_count = int(conn.execute("SELECT COUNT(*) FROM customers WHERE business_id=? AND is_active=1", (business_id,)).fetchone()[0])
            supplier_count = int(conn.execute("SELECT COUNT(*) FROM suppliers WHERE business_id=? AND is_active=1", (business_id,)).fetchone()[0])
            product_count = len(products)
            new_customer_count = int(conn.execute(
                "SELECT COUNT(*) FROM customers WHERE business_id=? AND substr(created_at,1,10) BETWEEN ? AND ? AND is_active=1",
                (business_id, start_s, end_s),
            ).fetchone()[0])
            audit = [dict(r) for r in conn.execute(
                "SELECT action,entity_type,entity_id,created_at FROM audit_logs WHERE business_id=? "
                "ORDER BY created_at DESC LIMIT 6", (business_id,),
            ).fetchall()]
            raw_due_sales = [dict(r) for r in conn.execute(
                "SELECT bill_number,customer_name,due_date,grand_total,amount_paid,status FROM bills WHERE business_id=? "
                "AND LOWER(TRIM(status)) IN ('issued','part_paid') AND due_date<>'' AND due_date BETWEEN ? AND ? ORDER BY due_date LIMIT 8",
                (business_id, today_s, future_s),
            ).fetchall()]
            raw_due_purchases = [dict(r) for r in conn.execute(
                "SELECT pb.purchase_number,pb.due_date,pb.grand_total,pb.amount_paid,s.name supplier_name FROM purchase_bills pb "
                "JOIN suppliers s ON s.supplier_id=pb.supplier_id WHERE pb.business_id=? AND LOWER(TRIM(pb.status)) IN ('posted','part_paid') "
                "AND pb.due_date<>'' AND pb.due_date BETWEEN ? AND ? ORDER BY pb.due_date LIMIT 8",
                (business_id, today_s, future_s),
            ).fetchall()]
            item_rows = [dict(r) for r in conn.execute(
                "SELECT COALESCE(p.product_id,bi.description) product_key,COALESCE(p.name,bi.description) product_name,"
                "COALESCE(p.sku,'') sku,bi.quantity,bi.taxable_value,bi.line_total FROM bill_items bi "
                "JOIN bills b ON b.bill_id=bi.bill_id LEFT JOIN products p ON p.product_id=bi.product_id "
                "WHERE b.business_id=? AND date(substr(b.invoice_date,1,10)) BETWEEN date(?) AND date(?) AND LOWER(TRIM(b.status)) IN ('issued','part_paid','paid')",
                (business_id, start_s, end_s),
            ).fetchall()]

        sales_taxable = _sum(sales, "taxable_total")
        sales_total = _sum(sales, "grand_total")
        sales_tax = _sum(sales, "tax_total")
        receipts_total = _sum(customer_receipts, "amount")
        purchase_total = _sum(purchases, "grand_total")
        supplier_paid_total = _sum(supplier_payments, "amount")
        receivable_total = sum((max(ZERO, money(decimal(r["grand_total"]) - decimal(r["amount_paid"]))) for r in all_open_sales), ZERO).quantize(CENT)
        overdue_sales = [r for r in all_open_sales if r.get("due_date") and r["due_date"] < today_s and money(decimal(r["grand_total"]) - decimal(r["amount_paid"])) > ZERO]
        overdue_receivables = sum((max(ZERO, money(decimal(r["grand_total"]) - decimal(r["amount_paid"]))) for r in overdue_sales), ZERO).quantize(CENT)
        payable_total = sum((max(ZERO, money(decimal(r["grand_total"]) - decimal(r["amount_paid"]))) for r in all_open_purchases), ZERO).quantize(CENT)
        overdue_purchases = [r for r in all_open_purchases if r.get("due_date") and r["due_date"] < today_s and money(decimal(r["grand_total"]) - decimal(r["amount_paid"])) > ZERO]
        overdue_payables = sum((max(ZERO, money(decimal(r["grand_total"]) - decimal(r["amount_paid"]))) for r in overdue_purchases), ZERO).quantize(CENT)

        low_stock = []
        out_of_stock = 0
        inventory_value = ZERO
        for product in products:
            on_hand = decimal(product["quantity_on_hand"])
            reorder = decimal(product["reorder_level"])
            cost = decimal(product["average_cost"])
            inventory_value += on_hand * cost
            if on_hand <= ZERO:
                out_of_stock += 1
            if reorder > ZERO and on_hand <= reorder:
                low_stock.append({**product, "shortage": str(max(ZERO, reorder-on_hand))})
        inventory_value = money(inventory_value)

        by_day: dict[str, Decimal] = defaultdict(lambda: ZERO)
        receipts_by_day: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for row in sales:
            # invoice_date may be stored as an ISO date or an ISO datetime in migrated workspaces.
            by_day[str(row["invoice_date"] or "")[:10]] += decimal(row["taxable_total"])
        for row in customer_receipts:
            receipts_by_day[str(row.get("paid_at", ""))[:10]] += decimal(row["amount"])
        span = max(1, (end - start).days + 1)
        bucket_count = min(8, span)
        buckets = [{"label": "", "value": ZERO, "receipts": ZERO} for _ in range(bucket_count)]
        for index in range(bucket_count):
            left = start + timedelta(days=(span * index) // bucket_count)
            right = start + timedelta(days=(span * (index + 1)) // bucket_count - 1)
            buckets[index]["label"] = left.strftime("%d %b") if span > 31 else left.strftime("%d %b")
            right_s = right.isoformat()
            left_s = left.isoformat()
            buckets[index]["value"] = sum((value for day, value in by_day.items() if left_s <= day <= right_s), ZERO)
            buckets[index]["receipts"] = sum((value for day, value in receipts_by_day.items() if left_s <= day <= right_s), ZERO)

        product_sales: dict[str, dict[str, Any]] = {}
        customer_sales: dict[tuple[str, str], dict[str, Any]] = {}
        for item in item_rows:
            key = str(item["product_key"])
            record = product_sales.setdefault(key, {"name": item["product_name"], "sku": item["sku"], "quantity": ZERO, "sales": ZERO})
            record["quantity"] += decimal(item["quantity"])
            record["sales"] += decimal(item["taxable_value"] or item["line_total"])
        top_products = sorted(product_sales.values(), key=lambda x: x["sales"], reverse=True)[:5]
        for bill in sales:
            key = (str(bill.get("customer_id") or bill.get("customer_name") or "Walk-in"), str(bill.get("customer_name") or "Walk-in Customer"))
            row = customer_sales.setdefault(key, {"name": key[1], "invoice_count": 0, "sales": ZERO, "paid": ZERO, "outstanding": ZERO})
            row["invoice_count"] += 1
            row["sales"] += decimal(bill["taxable_total"])
            row["paid"] += decimal(bill["amount_paid"])
            row["outstanding"] += max(ZERO, money(decimal(bill["grand_total"]) - decimal(bill["amount_paid"])))
        top_customers = sorted(customer_sales.values(), key=lambda x: x["sales"], reverse=True)[:5]

        # The ledger remains the source of truth for gross margin, expenses, cash/bank balances,
        # and balance-sheet health. synchronize_business is idempotent and backfills finalized
        # source documents that predate the accounting module.
        ledger_data: dict[str, Any] = {
            "gross_profit": None, "gross_margin_percent": None, "net_profit": None,
            "expenses": None, "cash_position": None, "total_assets": None,
            "trial_balance_status": "Ledger not available", "balance_sheet_status": "Ledger not available",
            "expense_rows": [],
        }
        try:
            from koshflow.services.accounting_service import AccountingService
            accounting = AccountingService(self.database)
            accounting.synchronize_business(business_id, None)
            trading = accounting.trading_account(business_id, start_s, end_s)
            pnl = accounting.profit_and_loss(business_id, start_s, end_s)
            balance_sheet = accounting.balance_sheet(business_id, end_s)
            trial_balance = accounting.trial_balance(business_id, end_s)
            cash_balance = decimal(accounting._balance_for_key(business_id, "cash", end_s))
            bank_balance = decimal(accounting._balance_for_key(business_id, "bank", end_s))
            ledger_sales = decimal(trading["net_sales"])
            ledger_gross_profit = decimal(trading["gross_profit"])
            ledger_data = {
                "gross_profit": money_text(ledger_gross_profit),
                "gross_margin_percent": money_text((ledger_gross_profit / ledger_sales * Decimal("100")) if ledger_sales else ZERO),
                "net_profit": pnl["net_profit"], "expenses": pnl["expenses"],
                "cash_position": money_text(cash_balance + bank_balance),
                "total_assets": balance_sheet["total_assets"],
                "trial_balance_status": "Balanced" if trial_balance["balanced"] else "Out of balance",
                "balance_sheet_status": "Balanced" if balance_sheet["balanced"] else "Out of balance",
                "expense_rows": [r for r in pnl["rows"] if r["type"] == "expense"],
            }
        except Exception:
            # A dashboard should still display sales/inventory even if legacy ledger data
            # needs attention. It must not invent the unavailable accounting metrics.
            pass

        due_rows: list[dict[str, Any]] = []
        for r in raw_due_sales:
            outstanding = max(ZERO, money(decimal(r["grand_total"])-decimal(r["amount_paid"])))
            if outstanding > ZERO:
                due_rows.append({"type": "Customer invoice", "document": r["bill_number"], "party": r["customer_name"], "due_date": r["due_date"], "amount": money_text(outstanding)})
        for r in raw_due_purchases:
            outstanding = max(ZERO, money(decimal(r["grand_total"])-decimal(r["amount_paid"])))
            if outstanding > ZERO:
                due_rows.append({"type": "Supplier bill", "document": r["purchase_number"], "party": r["supplier_name"], "due_date": r["due_date"], "amount": money_text(outstanding)})
        due_rows.sort(key=lambda r: r["due_date"])
        overdue_receivable_rows = [{
            "number": r["bill_number"], "customer": r["customer_name"], "due_date": r["due_date"],
            "amount": money_text(max(ZERO, money(decimal(r["grand_total"])-decimal(r["amount_paid"])))),
        } for r in overdue_sales]
        overdue_payable_rows = [{
            "number": r["purchase_number"], "supplier": r["supplier_name"], "due_date": r["due_date"],
            "amount": money_text(max(ZERO, money(decimal(r["grand_total"])-decimal(r["amount_paid"])))),
        } for r in overdue_purchases]

        return {
            "period": period, "start_date": start_s, "end_date": end_s, "as_of": today_s,
            "net_sales": money_text(sales_taxable), "gross_sales": money_text(sales_total), "sales_tax": money_text(sales_tax),
            "invoice_count": len(sales), "receivables": money_text(receivable_total), "overdue_receivables": money_text(overdue_receivables),
            "overdue_invoice_count": len(overdue_sales), "supplier_payables": money_text(payable_total),
            "overdue_payables": money_text(overdue_payables), "overdue_purchase_count": len(overdue_purchases),
            "customer_receipts": money_text(receipts_total), "supplier_payments": money_text(supplier_paid_total),
            "purchase_total": money_text(purchase_total), "purchase_count": len(purchases),
            "inventory_value": money_text(inventory_value), "product_count": product_count,
            "low_stock_count": len(low_stock), "out_of_stock_count": out_of_stock,
            "low_stock_products": low_stock[:6], "revenue_series": [{"label": r["label"], "value": money_text(r["value"])} for r in buckets],
            "receipt_series": [{"label": r["label"], "value": money_text(r["receipts"])} for r in buckets],
            "overdue_receivable_rows": overdue_receivable_rows[:6], "overdue_payable_rows": overdue_payable_rows[:6],
            "top_products": [{**r, "quantity": str(r["quantity"]), "sales": money_text(r["sales"])} for r in top_products],
            "top_customers": [{**r, "sales": money_text(r["sales"]), "paid": money_text(r["paid"]), "outstanding": money_text(r["outstanding"])} for r in top_customers],
            "recent_invoices": [{"number": r["bill_number"], "customer": r["customer_name"], "date": r["invoice_date"], "amount": money_text(r["grand_total"]), "status": r["status"]} for r in sales[:6]],
            "recent_purchases": [{"number": r["purchase_number"], "supplier": r["supplier_name"], "date": r["purchase_date"], "amount": money_text(r["grand_total"]), "status": r["status"]} for r in purchases[:6]],
            "customer_count": customer_count, "new_customer_count": new_customer_count, "supplier_count": supplier_count,
            "due_rows": due_rows[:8], "audit": audit,
            **ledger_data,
            "period_sales_decimal": sales_taxable, "period_receipts_decimal": receipts_total,
        }
