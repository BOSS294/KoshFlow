"""Double-entry accounting, journal posting and Indian tax-supporting reports.

Purpose: Keep a balanced, auditable local general ledger tied to sales and purchasing.
Canonical path: koshflow/services/accounting_service.py
Project: KoshFlow | Version: 0.6.2
Developer: Mayank Chawdhari AKA BOSS294
Integration: Use AccountingService(Database); source-document posts are exposed as *_conn helpers
             so calling services can post the source record and ledger atomically.
Changelog: v0.6.2 — Kept ledger reports as the source of truth while adding connected operational reports.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from koshflow.core.database import Database
from koshflow.core.security import new_id

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
IST = ZoneInfo("Asia/Kolkata")


class AccountingError(ValueError):
    """A journal or accounting operation would violate a ledger invariant."""


# key, code, name, type, normal side, description
DEFAULT_ACCOUNTS = [
    ("cash", "1000", "Cash on Hand", "asset", "debit", "Cash balances and counter collections."),
    ("bank", "1010", "Bank Account", "asset", "debit", "Bank and electronic payment balances."),
    ("accounts_receivable", "1100", "Accounts Receivable", "asset", "debit", "Amounts due from customers."),
    ("inventory", "1200", "Inventory", "asset", "debit", "Stock at recorded moving-average cost."),
    ("input_cgst", "1301", "Input GST - CGST", "asset", "debit", "Eligible central input GST tracked for reconciliation."),
    ("input_sgst", "1302", "Input GST - SGST", "asset", "debit", "Eligible state input GST tracked for reconciliation."),
    ("input_igst", "1303", "Input GST - IGST", "asset", "debit", "Eligible integrated input GST tracked for reconciliation."),
    ("fixed_assets", "1500", "Fixed Assets", "asset", "debit", "Equipment and other capital assets."),
    ("accounts_payable", "2000", "Accounts Payable", "liability", "credit", "Amounts payable to suppliers."),
    ("grni", "2010", "Goods Received Not Invoiced", "liability", "credit", "Stock received against purchase orders pending supplier-bill posting."),
    ("output_cgst", "2101", "Output GST - CGST", "liability", "credit", "Central output GST tracked for reconciliation."),
    ("output_sgst", "2102", "Output GST - SGST", "liability", "credit", "State output GST tracked for reconciliation."),
    ("output_igst", "2103", "Output GST - IGST", "liability", "credit", "Integrated output GST tracked for reconciliation."),
    ("tds_payable", "2200", "TDS Payable", "liability", "credit", "Tax deducted at source payable."),
    ("owners_capital", "3000", "Owner's Capital", "equity", "credit", "Owner capital introduced into the business."),
    ("opening_equity", "3010", "Opening Balance Equity", "equity", "credit", "Offset account for opening stock and migrated balances."),
    ("retained_earnings", "3100", "Retained Earnings", "equity", "credit", "Prior-period retained profits or losses."),
    ("sales_revenue", "4000", "Sales Revenue", "income", "credit", "Revenue from sold goods and billable items."),
    ("service_revenue", "4100", "Service Revenue", "income", "credit", "Revenue from services."),
    ("other_income", "4900", "Other Income", "income", "credit", "Other business income."),
    ("cogs", "5000", "Cost of Goods Sold", "expense", "debit", "Recorded cost of catalog stock sold."),
    ("operating_expenses", "5100", "Operating Expenses", "expense", "debit", "General operating expenses."),
    ("inventory_adjustment_loss", "5200", "Inventory Adjustment Loss", "expense", "debit", "Stock shortages and write-offs."),
    ("inventory_adjustment_gain", "4905", "Inventory Adjustment Gain", "income", "credit", "Documented positive stock adjustments."),
    ("bank_fees", "5300", "Bank Fees", "expense", "debit", "Bank charges and payment processing costs."),
    ("round_off", "5400", "Rounding Difference", "expense", "debit", "Explicitly recorded small rounding differences."),
]


def _now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _decimal(value: Any, label: str = "Amount") -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingError(f"{label} must be a valid decimal amount.") from exc
    if not result.is_finite():
        raise AccountingError(f"{label} must be finite.")
    return result


def _money(value: Any) -> Decimal:
    return _decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _money_text(value: Any) -> str:
    return f"{_money(value):.2f}"


def _date(value: str, label: str = "Date") -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError) as exc:
        raise AccountingError(f"{label} must use YYYY-MM-DD format.") from exc


def _state_key(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().replace("&", "and").split())


class AccountingService:
    def __init__(self, database: Database):
        self.database = database

    # ---------- Chart and period controls ----------
    @staticmethod
    def ensure_chart_conn(conn, business_id: str) -> None:
        now = _now()
        for key, code, name, kind, normal, description in DEFAULT_ACCOUNTS:
            conn.execute(
                "INSERT OR IGNORE INTO chart_of_accounts(account_id,business_id,account_code,account_name,account_type,normal_side,account_key,description,is_system,is_active,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,1,1,?,?)",
                (new_id("ACC"), business_id, code, name, kind, normal, key, description, now, now),
            )

    def ensure_chart(self, business_id: str) -> None:
        with self.database.transaction() as conn:
            self.ensure_chart_conn(conn, business_id)

    @staticmethod
    def _account_id(conn, business_id: str, key: str) -> str:
        row = conn.execute(
            "SELECT account_id FROM chart_of_accounts WHERE business_id=? AND account_key=? AND is_active=1",
            (business_id, key),
        ).fetchone()
        if not row:
            raise AccountingError(f"Required account '{key}' is not available in this business.")
        return str(row["account_id"])

    @staticmethod
    def _assert_period_open_conn(conn, business_id: str, entry_date: str) -> None:
        locked = conn.execute(
            "SELECT start_date,end_date,reason FROM accounting_period_locks WHERE business_id=? AND start_date<=? AND end_date>=? AND unlocked_at IS NULL LIMIT 1",
            (business_id, entry_date, entry_date),
        ).fetchone()
        if locked:
            raise AccountingError(
                f"Accounting date {entry_date} is locked ({locked['start_date']} to {locked['end_date']}). "
                "Unlock the period with an authorized correction workflow before posting here."
            )

    def list_accounts(self, business_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
        self.ensure_chart(business_id)
        clause = "" if include_inactive else " AND is_active=1"
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM chart_of_accounts WHERE business_id=?" + clause + " ORDER BY account_code",
                (business_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_account(self, business_id: str, actor_user_id: str, code: str, name: str,
                       account_type: str, normal_side: str | None = None, description: str = "") -> str:
        code, name = str(code).strip(), str(name).strip()
        account_type = str(account_type).strip().lower()
        if not code or len(code) > 20 or any(ch.isspace() for ch in code):
            raise AccountingError("Enter a short account code without spaces.")
        if not name or len(name) > 120:
            raise AccountingError("Account name must contain 1 to 120 characters.")
        if account_type not in {"asset", "liability", "equity", "income", "expense"}:
            raise AccountingError("Choose a valid account type.")
        normal_side = normal_side or ("debit" if account_type in {"asset", "expense"} else "credit")
        if normal_side not in {"debit", "credit"}:
            raise AccountingError("Normal side must be debit or credit.")
        now, account_id = _now(), new_id("ACC")
        with self.database.transaction() as conn:
            self.ensure_chart_conn(conn, business_id)
            self._assert_actor_conn(conn, business_id, actor_user_id, "accounts.manage")
            conn.execute(
                "INSERT INTO chart_of_accounts(account_id,business_id,account_code,account_name,account_type,normal_side,account_key,description,is_system,is_active,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,NULL,?,0,1,?,?)",
                (account_id, business_id, code, name, account_type, normal_side, str(description or "").strip()[:500], now, now),
            )
            self._audit_conn(conn, business_id, actor_user_id, "account.created", "account", account_id, {"code": code, "name": name})
        return account_id

    def lock_period(self, business_id: str, actor_user_id: str, start_date: str, end_date: str, reason: str) -> str:
        start, end = _date(start_date, "Start date"), _date(end_date, "End date")
        why = str(reason or "").strip()
        if start > end:
            raise AccountingError("Period start must be on or before its end.")
        if end >= _today():
            raise AccountingError("Only a closed period ending before today can be locked.")
        if not why:
            raise AccountingError("Provide a reason for locking this accounting period.")
        with self.database.transaction() as conn:
            self.ensure_chart_conn(conn, business_id)
            self._assert_actor_conn(conn, business_id, actor_user_id, "accounts.period_lock")
            overlap = conn.execute(
                "SELECT 1 FROM accounting_period_locks WHERE business_id=? AND unlocked_at IS NULL AND NOT(end_date<? OR start_date>?) LIMIT 1",
                (business_id, start, end),
            ).fetchone()
            if overlap:
                raise AccountingError("This period overlaps an existing lock.")
            lock_id = new_id("PLOCK")
            conn.execute(
                "INSERT INTO accounting_period_locks(period_lock_id,business_id,start_date,end_date,reason,locked_by,locked_at) VALUES(?,?,?,?,?,?,?)",
                (lock_id, business_id, start, end, why[:500], actor_user_id, _now()),
            )
            self._audit_conn(conn, business_id, actor_user_id, "accounting.period_locked", "accounting_period", lock_id,
                             {"start_date": start, "end_date": end, "reason": why[:500]})
        return lock_id

    def list_period_locks(self, business_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM accounting_period_locks WHERE business_id=? ORDER BY start_date DESC,locked_at DESC", (business_id,)
            ).fetchall()]

    def unlock_period(self, business_id: str, actor_user_id: str, period_lock_id: str, reason: str) -> None:
        why = str(reason or "").strip()
        if not why:
            raise AccountingError("Provide a reason for reopening a locked accounting period.")
        with self.database.transaction() as conn:
            self._assert_actor_conn(conn, business_id, actor_user_id, "accounts.period_lock")
            row = conn.execute(
                "SELECT * FROM accounting_period_locks WHERE business_id=? AND period_lock_id=?",
                (business_id, period_lock_id),
            ).fetchone()
            if not row:
                raise AccountingError("Accounting period lock not found in this business.")
            if row["unlocked_at"]:
                raise AccountingError("This accounting period is already open.")
            now = _now()
            conn.execute(
                "UPDATE accounting_period_locks SET unlocked_by=?,unlocked_at=?,unlock_reason=? WHERE business_id=? AND period_lock_id=? AND unlocked_at IS NULL",
                (actor_user_id, now, why[:500], business_id, period_lock_id),
            )
            self._audit_conn(conn, business_id, actor_user_id, "accounting.period_unlocked", "accounting_period", period_lock_id,
                             {"start_date": row["start_date"], "end_date": row["end_date"], "reason": why[:500]})

    # ---------- Balanced journal posting ----------
    @classmethod
    def _post_journal_conn(cls, conn, business_id: str, actor_user_id: str | None,
                           entry_date: str, narration: str, reference: str, source_type: str,
                           source_id: str, source_event: str, lines: list[dict[str, Any]],
                           reversal_of_entry_id: str | None = None) -> str:
        entry_date = _date(entry_date, "Journal date")
        narration = str(narration or "").strip()[:1000]
        if not narration:
            raise AccountingError("Journal narration is required.")
        existing = conn.execute(
            "SELECT entry_id FROM journal_entries WHERE business_id=? AND source_type=? AND source_id=? AND source_event=?",
            (business_id, source_type, source_id, source_event),
        ).fetchone()
        if existing:
            return str(existing["entry_id"])
        cls._assert_period_open_conn(conn, business_id, entry_date)
        cls.ensure_chart_conn(conn, business_id)
        normalized: list[dict[str, Any]] = []
        debit_total = ZERO
        credit_total = ZERO
        for item in lines:
            debit = _money(item.get("debit", 0))
            credit = _money(item.get("credit", 0))
            if debit < ZERO or credit < ZERO:
                raise AccountingError("Journal amounts cannot be negative.")
            if debit > ZERO and credit > ZERO:
                raise AccountingError("A journal line cannot contain both a debit and a credit.")
            if debit == ZERO and credit == ZERO:
                continue
            account_id = item.get("account_id")
            if not account_id and item.get("account_key"):
                account_id = cls._account_id(conn, business_id, str(item["account_key"]))
            account = conn.execute(
                "SELECT account_id FROM chart_of_accounts WHERE business_id=? AND account_id=? AND is_active=1",
                (business_id, str(account_id or "")),
            ).fetchone()
            if not account:
                raise AccountingError("A journal line references an inactive or foreign-business account.")
            normalized.append({
                "account_id": str(account["account_id"]),
                "description": str(item.get("description", "")).strip()[:500],
                "debit": debit, "credit": credit,
            })
            debit_total += debit
            credit_total += credit
        if len(normalized) < 2 or debit_total <= ZERO:
            raise AccountingError("A journal needs at least two non-zero lines and a positive total.")
        if debit_total != credit_total:
            raise AccountingError(f"Journal is not balanced: debits {_money_text(debit_total)} vs credits {_money_text(credit_total)}.")
        year = entry_date[:4]
        count = int(conn.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE business_id=? AND substr(entry_date,1,4)=?",
            (business_id, year),
        ).fetchone()[0]) + 1
        entry_number = f"JE-{year}-{count:05d}"
        now = _now()
        entry_id = new_id("JE")
        conn.execute(
            "INSERT INTO journal_entries(entry_id,business_id,entry_number,entry_date,reference,narration,source_type,source_id,source_event,status,reversal_of_entry_id,total_debit,total_credit,created_by,created_at,posted_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,'posted',?,?,?,?,?,?)",
            (entry_id, business_id, entry_number, entry_date, str(reference or "").strip()[:120], narration,
             source_type, source_id, source_event, reversal_of_entry_id, _money_text(debit_total), _money_text(credit_total), actor_user_id, now, now),
        )
        for ix, line in enumerate(normalized, start=1):
            conn.execute(
                "INSERT INTO journal_lines(journal_line_id,business_id,entry_id,account_id,line_number,description,debit,credit,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (new_id("JLN"), business_id, entry_id, line["account_id"], ix, line["description"],
                 _money_text(line["debit"]), _money_text(line["credit"]), now),
            )
        cls._audit_conn(conn, business_id, actor_user_id, "journal.posted", "journal_entry", entry_id,
                        {"entry_number": entry_number, "source_type": source_type, "source_id": source_id,
                         "debit": _money_text(debit_total), "credit": _money_text(credit_total)})
        return entry_id

    def create_manual_journal(self, business_id: str, actor_user_id: str, entry_date: str,
                              narration: str, reference: str, lines: list[dict[str, Any]]) -> str:
        entry_id_source = new_id("MANUAL")
        with self.database.transaction() as conn:
            self.ensure_chart_conn(conn, business_id)
            self._assert_actor_conn(conn, business_id, actor_user_id, "accounts.journal_manage")
            return self._post_journal_conn(
                conn, business_id, actor_user_id, entry_date, narration, reference,
                "manual_journal", entry_id_source, "posted", lines,
            )

    @classmethod
    def _reverse_entry_conn(cls, conn, business_id: str, actor_user_id: str | None,
                            source_type: str, source_id: str, source_event: str,
                            reversal_event: str, reversal_date: str, narration: str) -> str | None:
        original = conn.execute(
            "SELECT * FROM journal_entries WHERE business_id=? AND source_type=? AND source_id=? AND source_event=?",
            (business_id, source_type, source_id, source_event),
        ).fetchone()
        if not original:
            return None
        found = conn.execute(
            "SELECT entry_id FROM journal_entries WHERE business_id=? AND source_type=? AND source_id=? AND source_event=?",
            (business_id, source_type, source_id, reversal_event),
        ).fetchone()
        if found:
            return str(found["entry_id"])
        source_lines = conn.execute(
            "SELECT jl.*,coa.account_name FROM journal_lines jl JOIN chart_of_accounts coa ON coa.account_id=jl.account_id WHERE jl.entry_id=? ORDER BY jl.line_number",
            (original["entry_id"],),
        ).fetchall()
        lines = [{
            "account_id": row["account_id"], "description": f"Reversal: {row['description'] or row['account_name']}",
            "debit": row["credit"], "credit": row["debit"],
        } for row in source_lines]
        return cls._post_journal_conn(
            conn, business_id, actor_user_id, reversal_date, narration,
            str(original["entry_number"]), source_type, source_id, reversal_event, lines,
            reversal_of_entry_id=str(original["entry_id"]),
        )

    # ---------- Integrated source-document posting ----------
    @staticmethod
    def _gst_lines(conn, business_id: str, tax_amount: Any, counterparty_state: str,
                   prefix: str, description: str) -> list[dict[str, Any]]:
        tax = _money(tax_amount)
        if tax <= ZERO:
            return []
        seller = conn.execute("SELECT state FROM businesses WHERE business_id=?", (business_id,)).fetchone()
        seller_state = _state_key(seller["state"] if seller else "")
        buyer_state = _state_key(counterparty_state)
        if seller_state and buyer_state and seller_state == buyer_state:
            first = (tax / Decimal("2")).quantize(CENT, rounding=ROUND_HALF_UP)
            second = tax - first
            parts = [(f"{prefix}_cgst", first, f"{description} CGST"), (f"{prefix}_sgst", second, f"{description} SGST")]
        else:
            parts = [(f"{prefix}_igst", tax, f"{description} IGST")]
        return [{"account_key": key, "debit": amount if prefix == "input" else ZERO,
                 "credit": amount if prefix == "output" else ZERO, "description": label}
                for key, amount, label in parts if amount > ZERO]

    @classmethod
    def post_sales_invoice_conn(cls, conn, business_id: str, actor_user_id: str | None, bill_id: str) -> str | None:
        bill = conn.execute("SELECT * FROM bills WHERE business_id=? AND bill_id=?", (business_id, bill_id)).fetchone()
        if not bill or bill["document_type"] in {"estimate", "proforma"} or bill["status"] not in {"issued", "part_paid", "paid", "cancelled"}:
            return None
        cls.ensure_chart_conn(conn, business_id)
        grand = _money(bill["grand_total"])
        taxable = _money(bill["taxable_total"])
        tax = _money(bill["tax_total"])
        lines = [
            {"account_key": "accounts_receivable", "debit": grand, "description": f"Customer receivable - {bill['customer_name']}"},
            {"account_key": "sales_revenue", "credit": taxable, "description": f"Revenue - {bill['bill_number']}"},
        ]
        lines.extend(cls._gst_lines(conn, business_id, tax, bill["place_of_supply"], "output", "Sales GST"))
        cogs_rows = conn.execute(
            "SELECT movement_value FROM stock_movements WHERE business_id=? AND movement_type='sale' AND source_type='bill' AND source_id=?",
            (business_id, bill_id),
        ).fetchall()
        cogs = _money(sum((_decimal(row["movement_value"], "Stock movement value") for row in cogs_rows), ZERO))
        if cogs > ZERO:
            lines.extend([
                {"account_key": "cogs", "debit": cogs, "description": f"Cost of goods sold - {bill['bill_number']}"},
                {"account_key": "inventory", "credit": cogs, "description": f"Inventory relieved - {bill['bill_number']}"},
            ])
        return cls._post_journal_conn(
            conn, business_id, actor_user_id, bill["invoice_date"], f"Sales invoice {bill['bill_number']} - {bill['customer_name']}",
            bill["bill_number"], "bill", bill_id, "issued", lines,
        )

    @classmethod
    def post_bill_payment_conn(cls, conn, business_id: str, actor_user_id: str | None, payment_id: str) -> str | None:
        payment = conn.execute("SELECT * FROM bill_payments WHERE business_id=? AND payment_id=?", (business_id, payment_id)).fetchone()
        if not payment:
            return None
        bill = conn.execute("SELECT bill_number FROM bills WHERE business_id=? AND bill_id=?", (business_id, payment["bill_id"])).fetchone()
        amount = _money(payment["amount"])
        cash_key = "cash" if payment["payment_method"] == "Cash" else "bank"
        return cls._post_journal_conn(
            conn, business_id, actor_user_id, payment["paid_at"], f"Receipt against invoice {bill['bill_number'] if bill else payment['bill_id']}",
            payment["reference"], "bill_payment", payment_id, "received", [
                {"account_key": cash_key, "debit": amount, "description": f"Customer receipt ({payment['payment_method']})"},
                {"account_key": "accounts_receivable", "credit": amount, "description": f"Receivable settled - {bill['bill_number'] if bill else ''}"},
            ],
        )

    @classmethod
    def post_stock_movement_conn(cls, conn, business_id: str, actor_user_id: str | None, movement_id: str) -> str | None:
        movement = conn.execute(
            "SELECT * FROM stock_movements WHERE business_id=? AND stock_movement_id=?", (business_id, movement_id)
        ).fetchone()
        if not movement:
            return None
        kind = movement["movement_type"]
        value = _money(movement["movement_value"])
        if value <= ZERO:
            return None
        qty = _decimal(movement["quantity_delta"])
        if kind == "purchase_order_receipt":
            lines = [
                {"account_key": "inventory", "debit": value, "description": "Inventory received against purchase order"},
                {"account_key": "grni", "credit": value, "description": "Goods received not yet invoiced"},
            ]
        elif kind == "opening":
            if qty >= 0:
                lines = [
                    {"account_key": "inventory", "debit": value, "description": "Opening stock"},
                    {"account_key": "opening_equity", "credit": value, "description": "Opening stock balance"},
                ]
            else:
                lines = [
                    {"account_key": "opening_equity", "debit": value, "description": "Opening stock correction"},
                    {"account_key": "inventory", "credit": value, "description": "Opening stock correction"},
                ]
        elif kind == "adjustment_in":
            lines = [
                {"account_key": "inventory", "debit": value, "description": "Stock increase adjustment"},
                {"account_key": "inventory_adjustment_gain", "credit": value, "description": "Stock adjustment gain"},
            ]
        elif kind == "adjustment_out":
            lines = [
                {"account_key": "inventory_adjustment_loss", "debit": value, "description": "Stock shortage/write-off"},
                {"account_key": "inventory", "credit": value, "description": "Stock reduction adjustment"},
            ]
        else:
            # Purchase bills and sales invoices post their own compound entries; supplier returns are compound too.
            return None
        return cls._post_journal_conn(
            conn, business_id, actor_user_id, str(movement["created_at"])[:10],
            f"Stock movement {movement['movement_type']} - {movement['stock_movement_id']}",
            movement["stock_movement_id"], "stock_movement", movement_id, kind, lines,
        )

    @classmethod
    def post_purchase_bill_conn(cls, conn, business_id: str, actor_user_id: str | None, purchase_bill_id: str) -> str | None:
        bill = conn.execute("SELECT * FROM purchase_bills WHERE business_id=? AND purchase_bill_id=?", (business_id, purchase_bill_id)).fetchone()
        if not bill or bill["status"] not in {"posted", "part_paid", "paid"}:
            return None
        cls.ensure_chart_conn(conn, business_id)
        source_po = bill["source_purchase_order_id"]
        if source_po:
            # Backfill receipt entries from older local records before clearing GRNI.
            movements = conn.execute(
                "SELECT stock_movement_id FROM stock_movements WHERE business_id=? AND movement_type='purchase_order_receipt' AND source_type='purchase_order' AND source_id=? ORDER BY created_at,rowid",
                (business_id, source_po),
            ).fetchall()
            for movement in movements:
                cls.post_stock_movement_conn(conn, business_id, actor_user_id, str(movement["stock_movement_id"]))
        inventory_key = "grni" if source_po else "inventory"
        taxable, tax, grand = _money(bill["taxable_total"]), _money(bill["tax_total"]), _money(bill["grand_total"])
        supplier = conn.execute("SELECT state FROM suppliers WHERE business_id=? AND supplier_id=?", (business_id, bill["supplier_id"])).fetchone()
        lines = [{"account_key": inventory_key, "debit": taxable,
                  "description": "Clear goods received not invoiced" if source_po else "Purchased inventory"}]
        lines.extend(cls._gst_lines(conn, business_id, tax, supplier["state"] if supplier else "", "input", "Purchase GST"))
        lines.append({"account_key": "accounts_payable", "credit": grand, "description": f"Supplier payable - {bill['purchase_number']}"})
        return cls._post_journal_conn(
            conn, business_id, actor_user_id, bill["purchase_date"], f"Purchase bill {bill['purchase_number']}",
            bill["supplier_invoice_number"] or bill["purchase_number"], "purchase_bill", purchase_bill_id, "posted", lines,
        )

    @classmethod
    def post_supplier_payment_conn(cls, conn, business_id: str, actor_user_id: str | None, payment_id: str) -> str | None:
        payment = conn.execute("SELECT * FROM supplier_payments WHERE business_id=? AND supplier_payment_id=?", (business_id, payment_id)).fetchone()
        if not payment:
            return None
        bill = conn.execute("SELECT purchase_number FROM purchase_bills WHERE business_id=? AND purchase_bill_id=?", (business_id, payment["purchase_bill_id"])).fetchone()
        amount = _money(payment["amount"])
        cash_key = "cash" if payment["payment_method"] == "Cash" else "bank"
        return cls._post_journal_conn(
            conn, business_id, actor_user_id, payment["paid_at"], f"Supplier payment against {bill['purchase_number'] if bill else payment['purchase_bill_id']}",
            payment["reference"], "supplier_payment", payment_id, "paid", [
                {"account_key": "accounts_payable", "debit": amount, "description": "Supplier payable settled"},
                {"account_key": cash_key, "credit": amount, "description": f"Supplier payment ({payment['payment_method']})"},
            ],
        )

    @classmethod
    def post_supplier_return_conn(cls, conn, business_id: str, actor_user_id: str | None, supplier_return_id: str) -> str | None:
        ret = conn.execute("SELECT * FROM supplier_returns WHERE business_id=? AND supplier_return_id=?", (business_id, supplier_return_id)).fetchone()
        if not ret or ret["status"] != "posted":
            return None
        bill = conn.execute("SELECT supplier_id FROM purchase_bills WHERE business_id=? AND purchase_bill_id=?", (business_id, ret["purchase_bill_id"])).fetchone()
        supplier = conn.execute("SELECT state FROM suppliers WHERE business_id=? AND supplier_id=?", (business_id, ret["supplier_id"])).fetchone()
        taxable = _money(ret["subtotal"])
        tax = _money(ret["tax_total"])
        grand = _money(ret["grand_total"])
        lines = [{"account_key": "accounts_payable", "debit": grand, "description": f"Supplier credit {ret['return_number']}"}]
        lines.extend(cls._gst_lines(conn, business_id, tax, supplier["state"] if supplier else "", "input", "Reversal of purchase GST"))
        # Input tax asset is credited on return, so invert GST helper's normal purchase debit lines.
        for line in lines[1:]:
            line["debit"], line["credit"] = line.get("credit", ZERO), line.get("debit", ZERO)
        lines.append({"account_key": "inventory", "credit": taxable, "description": f"Stock returned to supplier {ret['return_number']}"})
        return cls._post_journal_conn(
            conn, business_id, actor_user_id, ret["return_date"], f"Supplier return {ret['return_number']}",
            ret["return_number"], "supplier_return", supplier_return_id, "posted", lines,
        )

    def synchronize_business(self, business_id: str, actor_user_id: str | None = None) -> list[str]:
        """Idempotently backfill ledger entries for finalized transactions made before v0.6.0."""
        warnings: list[str] = []
        self.ensure_chart(business_id)
        with self.database.connection() as conn:
            movements = [dict(r) for r in conn.execute(
                "SELECT stock_movement_id FROM stock_movements WHERE business_id=? AND movement_type IN ('purchase_order_receipt','opening','adjustment_in','adjustment_out') ORDER BY created_at,rowid",
                (business_id,),
            ).fetchall()]
            bills = [dict(r) for r in conn.execute(
                "SELECT bill_id,status,document_type FROM bills WHERE business_id=? AND status IN ('issued','part_paid','paid','cancelled') ORDER BY invoice_date,created_at",
                (business_id,),
            ).fetchall()]
            payment_ids = [str(r[0]) for r in conn.execute("SELECT payment_id FROM bill_payments WHERE business_id=? ORDER BY paid_at,created_at", (business_id,)).fetchall()]
            purchase_bills = [str(r[0]) for r in conn.execute("SELECT purchase_bill_id FROM purchase_bills WHERE business_id=? AND status IN ('posted','part_paid','paid') ORDER BY purchase_date,created_at", (business_id,)).fetchall()]
            supplier_payment_ids = [str(r[0]) for r in conn.execute("SELECT supplier_payment_id FROM supplier_payments WHERE business_id=? ORDER BY paid_at,created_at", (business_id,)).fetchall()]
            returns = [str(r[0]) for r in conn.execute("SELECT supplier_return_id FROM supplier_returns WHERE business_id=? AND status='posted' ORDER BY return_date,created_at", (business_id,)).fetchall()]
            # Preserve reverse links for canceled legacy invoices.
            cancelled_ids = [str(r["bill_id"]) for r in bills if r["status"] == "cancelled"]
        jobs = []
        jobs.extend(("stock", str(r["stock_movement_id"])) for r in movements)
        jobs.extend(("bill", str(r["bill_id"])) for r in bills)
        jobs.extend(("bill_payment", key) for key in payment_ids)
        jobs.extend(("purchase_bill", key) for key in purchase_bills)
        jobs.extend(("supplier_payment", key) for key in supplier_payment_ids)
        jobs.extend(("supplier_return", key) for key in returns)
        for kind, source_id in jobs:
            try:
                with self.database.transaction() as conn:
                    if kind == "stock":
                        self.post_stock_movement_conn(conn, business_id, actor_user_id, source_id)
                    elif kind == "bill":
                        self.post_sales_invoice_conn(conn, business_id, actor_user_id, source_id)
                        status = conn.execute("SELECT status FROM bills WHERE business_id=? AND bill_id=?", (business_id, source_id)).fetchone()
                        if status and status["status"] == "cancelled":
                            self._reverse_entry_conn(conn, business_id, actor_user_id, "bill", source_id, "issued", "cancelled", _today(), f"Cancellation reversal for bill {source_id}")
                    elif kind == "bill_payment":
                        self.post_bill_payment_conn(conn, business_id, actor_user_id, source_id)
                    elif kind == "purchase_bill":
                        self.post_purchase_bill_conn(conn, business_id, actor_user_id, source_id)
                    elif kind == "supplier_payment":
                        self.post_supplier_payment_conn(conn, business_id, actor_user_id, source_id)
                    elif kind == "supplier_return":
                        self.post_supplier_return_conn(conn, business_id, actor_user_id, source_id)
            except Exception as exc:  # keep the rest of the ledger accessible; surface each exception in the UI.
                warnings.append(f"{kind} {source_id}: {exc}")
        return warnings

    # ---------- Queries / statements ----------
    def list_entries(self, business_id: str, start_date: str | None = None, end_date: str | None = None,
                     search: str = "", limit: int = 1000) -> list[dict[str, Any]]:
        clauses = ["je.business_id=?"]
        params: list[Any] = [business_id]
        if start_date:
            clauses.append("je.entry_date>=?"); params.append(_date(start_date))
        if end_date:
            clauses.append("je.entry_date<=?"); params.append(_date(end_date))
        if search.strip():
            term = f"%{search.strip()}%"
            clauses.append("(je.entry_number LIKE ? OR je.reference LIKE ? OR je.narration LIKE ?)")
            params.extend([term, term, term])
        params.append(max(1, min(int(limit), 5000)))
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT je.*,COUNT(jl.journal_line_id) AS line_count FROM journal_entries je LEFT JOIN journal_lines jl ON jl.entry_id=je.entry_id WHERE {' AND '.join(clauses)} GROUP BY je.entry_id ORDER BY je.entry_date DESC,je.created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_entry(self, business_id: str, entry_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            entry = conn.execute("SELECT * FROM journal_entries WHERE business_id=? AND entry_id=?", (business_id, entry_id)).fetchone()
            if not entry:
                return None
            result = dict(entry)
            result["lines"] = [dict(r) for r in conn.execute(
                "SELECT jl.*,coa.account_code,coa.account_name,coa.account_type FROM journal_lines jl JOIN chart_of_accounts coa ON coa.account_id=jl.account_id WHERE jl.business_id=? AND jl.entry_id=? ORDER BY jl.line_number",
                (business_id, entry_id),
            ).fetchall()]
        return result

    @staticmethod
    def _sum_account_lines_conn(conn, business_id: str, account_id: str, *,
                                start_date: str | None = None, end_date: str | None = None,
                                before_date: str | None = None, through_date: str | None = None) -> tuple[Decimal, Decimal]:
        """Sum ledger money as Decimal in Python; SQLite REAL casts lose cent precision at scale."""
        clauses = ["jl.business_id=?", "jl.account_id=?"]
        params: list[Any] = [business_id, account_id]
        if start_date:
            clauses.append("je.entry_date>=?"); params.append(start_date)
        if end_date:
            clauses.append("je.entry_date<=?"); params.append(end_date)
        if before_date:
            clauses.append("je.entry_date<?"); params.append(before_date)
        if through_date:
            clauses.append("je.entry_date<=?"); params.append(through_date)
        rows = conn.execute(
            "SELECT jl.debit,jl.credit FROM journal_lines jl JOIN journal_entries je ON je.entry_id=jl.entry_id WHERE " + " AND ".join(clauses),
            params,
        ).fetchall()
        debit = sum((_decimal(row["debit"], "Ledger debit") for row in rows), ZERO)
        credit = sum((_decimal(row["credit"], "Ledger credit") for row in rows), ZERO)
        return debit, credit

    def trial_balance(self, business_id: str, as_of: str | None = None) -> dict[str, Any]:
        self.ensure_chart(business_id)
        cutoff = _date(as_of or _today())
        with self.database.connection() as conn:
            accounts = conn.execute("SELECT * FROM chart_of_accounts WHERE business_id=? AND is_active=1 ORDER BY account_code", (business_id,)).fetchall()
            result = []
            total_dr = total_cr = ZERO
            for account in accounts:
                debit_total, credit_total = self._sum_account_lines_conn(
                    conn, business_id, str(account["account_id"]), through_date=cutoff,
                )
                net = _money(debit_total - credit_total)
                debit_balance = max(net, ZERO)
                credit_balance = max(-net, ZERO)
                if debit_balance or credit_balance:
                    result.append({"account_id": account["account_id"], "code": account["account_code"], "name": account["account_name"],
                                   "type": account["account_type"], "debit": _money_text(debit_balance), "credit": _money_text(credit_balance)})
                total_dr += debit_balance; total_cr += credit_balance
        return {"as_of": cutoff, "rows": result, "total_debit": _money_text(total_dr), "total_credit": _money_text(total_cr),
                "balanced": total_dr == total_cr}

    def profit_and_loss(self, business_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        start, end = _date(start_date), _date(end_date)
        if start > end:
            raise AccountingError("Report start date must not be after the end date.")
        self.ensure_chart(business_id)
        with self.database.connection() as conn:
            accounts = conn.execute("SELECT * FROM chart_of_accounts WHERE business_id=? AND is_active=1 AND account_type IN ('income','expense') ORDER BY account_code", (business_id,)).fetchall()
            result, revenue, expenses = [], ZERO, ZERO
            for account in accounts:
                dr, cr = self._sum_account_lines_conn(
                    conn, business_id, str(account["account_id"]), start_date=start, end_date=end,
                )
                balance = _money(cr - dr) if account["account_type"] == "income" else _money(dr - cr)
                if balance != ZERO:
                    result.append({"code": account["account_code"], "name": account["account_name"], "type": account["account_type"], "amount": _money_text(balance)})
                    if account["account_type"] == "income": revenue += balance
                    else: expenses += balance
        return {"start_date": start, "end_date": end, "rows": result, "revenue": _money_text(revenue),
                "expenses": _money_text(expenses), "net_profit": _money_text(revenue-expenses)}

    def trading_account(self, business_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        """Return a Trading Account on the app's perpetual-inventory basis.

        Purchases are capitalized to inventory and cost of sales is recognized from
        recorded stock-sale movements. To avoid counting purchases twice, this report
        calculates gross profit as net sales less ledger COGS. Opening/closing stock
        are included as memorandum balances, not added again to COGS.
        """
        start, end = _date(start_date), _date(end_date)
        if start > end:
            raise AccountingError("Report start date must not be after the end date.")
        self.ensure_chart(business_id)
        with self.database.connection() as conn:
            def period_amount(account_key: str, debit_minus_credit: bool) -> Decimal:
                account = conn.execute(
                    "SELECT account_id FROM chart_of_accounts WHERE business_id=? AND account_key=? AND is_active=1",
                    (business_id, account_key),
                ).fetchone()
                if not account:
                    return ZERO
                debit, credit = self._sum_account_lines_conn(
                    conn, business_id, str(account["account_id"]), start_date=start, end_date=end,
                )
                return _money(debit-credit if debit_minus_credit else credit-debit)

            def stock_balance(cutoff: str | None, before: str | None = None) -> Decimal:
                account = conn.execute(
                    "SELECT account_id FROM chart_of_accounts WHERE business_id=? AND account_key='inventory' AND is_active=1",
                    (business_id,),
                ).fetchone()
                if not account:
                    return ZERO
                debit, credit = self._sum_account_lines_conn(
                    conn, business_id, str(account["account_id"]),
                    through_date=cutoff, before_date=before,
                )
                return _money(debit-credit)

            # Sales Revenue is credit-normal; COGS is debit-normal.
            net_sales = period_amount("sales_revenue", False)
            cogs = period_amount("cogs", True)
            opening_stock = stock_balance(None, start)
            closing_stock = stock_balance(end)
            stock_loss = period_amount("inventory_adjustment_loss", True)
            stock_gain = period_amount("inventory_adjustment_gain", False)
            gross_profit = _money(net_sales - cogs)
            rows = [
                {"section": "Trading", "code": "4000", "particulars": "Net sales", "amount": _money_text(net_sales)},
                {"section": "Trading", "code": "5000", "particulars": "Less: cost of goods sold", "amount": _money_text(cogs)},
                {"section": "Trading", "code": "", "particulars": "GROSS PROFIT / (LOSS)", "amount": _money_text(gross_profit)},
                {"section": "Memorandum", "code": "1200", "particulars": "Opening inventory balance (context only)", "amount": _money_text(opening_stock)},
                {"section": "Memorandum", "code": "1200", "particulars": "Closing inventory balance (context only)", "amount": _money_text(closing_stock)},
                {"section": "Excluded from gross profit", "code": "5200", "particulars": "Inventory adjustment losses (shown in P&L)", "amount": _money_text(stock_loss)},
                {"section": "Excluded from gross profit", "code": "4905", "particulars": "Inventory adjustment gains (shown in P&L)", "amount": _money_text(stock_gain)},
            ]
        return {
            "start_date": start, "end_date": end, "rows": rows,
            "net_sales": _money_text(net_sales), "cost_of_goods_sold": _money_text(cogs),
            "gross_profit": _money_text(gross_profit), "opening_inventory": _money_text(opening_stock),
            "closing_inventory": _money_text(closing_stock), "inventory_adjustment_loss": _money_text(stock_loss),
            "inventory_adjustment_gain": _money_text(stock_gain),
            "basis": "Perpetual inventory: gross profit is net sales less ledger cost of goods sold. Opening and closing inventory are memorandum balances and are not added a second time.",
        }

    def journal_register(self, business_id: str, start_date: str, end_date: str,
                         search: str = "", limit: int = 5000) -> dict[str, Any]:
        """Return date-filtered posted journal headers for UI and PDF/CSV exports."""
        start, end = _date(start_date), _date(end_date)
        if start > end:
            raise AccountingError("Report start date must not be after the end date.")
        entries = self.list_entries(business_id, start, end, search, limit)
        debit_total = sum((_money(row.get("total_debit")) for row in entries), ZERO)
        credit_total = sum((_money(row.get("total_credit")) for row in entries), ZERO)
        return {"start_date": start, "end_date": end, "rows": entries,
                "total_debit": _money_text(debit_total), "total_credit": _money_text(credit_total),
                "balanced": debit_total == credit_total, "count": len(entries)}

    def balance_sheet(self, business_id: str, as_of: str | None = None) -> dict[str, Any]:
        cutoff = _date(as_of or _today())
        self.ensure_chart(business_id)
        with self.database.connection() as conn:
            accounts = conn.execute("SELECT * FROM chart_of_accounts WHERE business_id=? AND is_active=1 AND account_type IN ('asset','liability','equity') ORDER BY account_code", (business_id,)).fetchall()
            sections: dict[str, list[dict[str, Any]]] = {"asset": [], "liability": [], "equity": []}
            totals = {"asset": ZERO, "liability": ZERO, "equity": ZERO}
            for account in accounts:
                dr, cr = self._sum_account_lines_conn(
                    conn, business_id, str(account["account_id"]), through_date=cutoff,
                )
                balance = _money(dr-cr) if account["account_type"] == "asset" else _money(cr-dr)
                if balance != ZERO:
                    sections[account["account_type"]].append({"code": account["account_code"], "name": account["account_name"], "amount": _money_text(balance)})
                    totals[account["account_type"]] += balance
            # Current and prior earnings are part of equity even before the year-end close journal.
            income_expense = conn.execute(
                "SELECT coa.account_type,jl.debit,jl.credit "
                "FROM journal_lines jl JOIN journal_entries je ON je.entry_id=jl.entry_id JOIN chart_of_accounts coa ON coa.account_id=jl.account_id "
                "WHERE jl.business_id=? AND je.entry_date<=? AND coa.account_type IN ('income','expense')",
                (business_id, cutoff),
            ).fetchall()
            totals_by_type: dict[str, dict[str, Decimal]] = {
                "income": {"debit": ZERO, "credit": ZERO},
                "expense": {"debit": ZERO, "credit": ZERO},
            }
            for item in income_expense:
                totals_by_type[item["account_type"]]["debit"] += _decimal(item["debit"], "Ledger debit")
                totals_by_type[item["account_type"]]["credit"] += _decimal(item["credit"], "Ledger credit")
            amounts = {
                "income": totals_by_type["income"]["credit"] - totals_by_type["income"]["debit"],
                "expense": totals_by_type["expense"]["debit"] - totals_by_type["expense"]["credit"],
            }
            current_earnings = _money(amounts.get("income", ZERO)-amounts.get("expense", ZERO))
            if current_earnings != ZERO:
                sections["equity"].append({"code": "CURRENT", "name": "Accumulated current earnings", "amount": _money_text(current_earnings)})
                totals["equity"] += current_earnings
        asset_total = _money(totals["asset"])
        liability_total = _money(totals["liability"])
        equity_total = _money(totals["equity"])
        return {"as_of": cutoff, "assets": sections["asset"], "liabilities": sections["liability"], "equity": sections["equity"],
                "total_assets": _money_text(asset_total), "total_liabilities": _money_text(liability_total),
                "total_equity": _money_text(equity_total), "liabilities_and_equity": _money_text(liability_total+equity_total),
                "balanced": asset_total == _money(liability_total+equity_total)}

    def general_ledger(self, business_id: str, account_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        start, end = _date(start_date), _date(end_date)
        if start > end:
            raise AccountingError("Report start date must not be after the end date.")
        with self.database.connection() as conn:
            account = conn.execute("SELECT * FROM chart_of_accounts WHERE business_id=? AND account_id=?", (business_id, account_id)).fetchone()
            if not account:
                raise AccountingError("Select an account from this business.")
            opening_debit, opening_credit = self._sum_account_lines_conn(
                conn, business_id, account_id, before_date=start,
            )
            net_opening = _money(opening_debit - opening_credit)
            running = net_opening if account["normal_side"] == "debit" else -net_opening
            opening_running = running
            rows = conn.execute(
                "SELECT je.entry_date,je.entry_number,je.reference,je.narration,jl.description,jl.debit,jl.credit "
                "FROM journal_lines jl JOIN journal_entries je ON je.entry_id=jl.entry_id WHERE jl.business_id=? AND jl.account_id=? AND je.entry_date BETWEEN ? AND ? ORDER BY je.entry_date,je.created_at,je.entry_number,jl.line_number",
                (business_id, account_id, start, end),
            ).fetchall()
            result = []
            for row in rows:
                dr, cr = _money(row["debit"]), _money(row["credit"])
                running += (dr-cr) if account["normal_side"] == "debit" else (cr-dr)
                result.append({**dict(row), "running_balance": _money_text(running)})
        return {"account": dict(account), "start_date": start, "end_date": end,
                "opening_balance": _money_text(opening_running), "rows": result,
                "closing_balance": _money_text(running)}

    def gst_summary(self, business_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        start, end = _date(start_date), _date(end_date)
        if start > end:
            raise AccountingError("Report start date must not be after the end date.")
        self.ensure_chart(business_id)
        keys = ["output_cgst", "output_sgst", "output_igst", "input_cgst", "input_sgst", "input_igst"]
        balances: dict[str, Decimal] = {}
        with self.database.connection() as conn:
            for key in keys:
                account = conn.execute("SELECT account_id FROM chart_of_accounts WHERE business_id=? AND account_key=?", (business_id, key)).fetchone()
                dr, cr = self._sum_account_lines_conn(
                    conn, business_id, str(account["account_id"]), start_date=start, end_date=end,
                )
                # Output tax is a credit-normal liability; input tax is a debit-normal asset.
                balances[key] = _money(cr - dr if key.startswith("output") else dr - cr)
        output = _money(sum((balances[k] for k in keys if k.startswith("output")), ZERO))
        input_tax = _money(sum((balances[k] for k in keys if k.startswith("input")), ZERO))
        return {"start_date": start, "end_date": end, "output_tax": _money_text(output), "input_tax": _money_text(input_tax),
                "net_payable": _money_text(output-input_tax), "rows": [
                    {"code": "Output CGST", "amount": _money_text(balances["output_cgst"])},
                    {"code": "Output SGST", "amount": _money_text(balances["output_sgst"])},
                    {"code": "Output IGST", "amount": _money_text(balances["output_igst"])},
                    {"code": "Input CGST", "amount": _money_text(balances["input_cgst"])},
                    {"code": "Input SGST", "amount": _money_text(balances["input_sgst"])},
                    {"code": "Input IGST", "amount": _money_text(balances["input_igst"])},
                ]}

    def hsn_sac_summary(self, business_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        """Build an item-level HSN/SAC support summary from issued documents and dated cancellations.

        This is a reconciliation aid, not a filed GST return. Cancellation entries are
        included in the period in which their reversal journal was posted.
        """
        start, end = _date(start_date), _date(end_date)
        if start > end:
            raise AccountingError("Report start date must not be after the end date.")
        with self.database.connection() as conn:
            invoice_rows = conn.execute(
                "SELECT b.bill_id,b.invoice_date,bi.hsn_sac,bi.description,bi.unit,bi.quantity,bi.tax_rate,bi.taxable_value,bi.tax_amount "
                "FROM bills b JOIN bill_items bi ON bi.bill_id=b.bill_id "
                "WHERE b.business_id=? AND b.invoice_date BETWEEN ? AND ? AND b.status IN ('issued','part_paid','paid','cancelled') "
                "AND b.document_type NOT IN ('estimate','proforma') ORDER BY b.invoice_date,b.bill_number,bi.row_order",
                (business_id, start, end),
            ).fetchall()
            cancellations = conn.execute(
                "SELECT je.source_id AS bill_id,je.entry_date,bi.hsn_sac,bi.description,bi.unit,bi.quantity,bi.tax_rate,bi.taxable_value,bi.tax_amount "
                "FROM journal_entries je JOIN bills b ON b.bill_id=je.source_id JOIN bill_items bi ON bi.bill_id=b.bill_id "
                "WHERE je.business_id=? AND je.source_type='bill' AND je.source_event='cancelled' "
                "AND je.entry_date BETWEEN ? AND ? AND b.document_type NOT IN ('estimate','proforma') "
                "ORDER BY je.entry_date,je.entry_number,bi.row_order",
                (business_id, start, end),
            ).fetchall()
        totals: dict[tuple[str, str, str], dict[str, Any]] = {}
        def add(row, sign: Decimal) -> None:
            code = str(row["hsn_sac"] or "Unspecified")
            unit = str(row["unit"] or "")
            rate = _money(row["tax_rate"])
            key = (code, unit, f"{rate:.2f}")
            target = totals.setdefault(key, {"hsn_sac": code, "unit": unit, "tax_rate": f"{rate:.2f}",
                                             "quantity": ZERO, "taxable_value": ZERO, "tax_amount": ZERO,
                                             "descriptions": set()})
            target["quantity"] += sign * _decimal(row["quantity"], "Invoice quantity")
            target["taxable_value"] += sign * _money(row["taxable_value"])
            target["tax_amount"] += sign * _money(row["tax_amount"])
            description = str(row["description"] or "").strip()
            if description:
                target["descriptions"].add(description)
        for row in invoice_rows:
            add(row, Decimal("1"))
        for row in cancellations:
            add(row, Decimal("-1"))
        result = []
        for row in totals.values():
            if row["quantity"] == ZERO and row["taxable_value"] == ZERO and row["tax_amount"] == ZERO:
                continue
            descriptions = sorted(row.pop("descriptions"))
            row["description"] = descriptions[0] if len(descriptions) == 1 else ("Multiple items" if descriptions else "")
            row["quantity"] = f"{row['quantity']:.3f}"
            row["taxable_value"] = _money_text(row["taxable_value"])
            row["tax_amount"] = _money_text(row["tax_amount"])
            result.append(row)
        result.sort(key=lambda r: (r["hsn_sac"], r["unit"], r["tax_rate"]))
        return {"start_date": start, "end_date": end, "rows": result,
                "taxable_total": _money_text(sum((Decimal(r["taxable_value"]) for r in result), ZERO)),
                "tax_total": _money_text(sum((Decimal(r["tax_amount"]) for r in result), ZERO)),
                "note": "HSN/SAC reconciliation support only; verify against current GST return rules before filing."}

    def cash_flow_statement(self, business_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        """Report posted cash/bank movement using exact decimal ledger values."""
        start, end = _date(start_date), _date(end_date)
        if start > end:
            raise AccountingError("Report start date must not be after the end date.")
        self.ensure_chart(business_id)
        with self.database.connection() as conn:
            cash_accounts = conn.execute(
                "SELECT account_id,account_code,account_name,account_key FROM chart_of_accounts "
                "WHERE business_id=? AND account_key IN ('cash','bank') AND is_active=1",
                (business_id,),
            ).fetchall()
            cash_ids = [str(r["account_id"]) for r in cash_accounts]
            opening = ZERO
            for account_id in cash_ids:
                dr, cr = self._sum_account_lines_conn(conn, business_id, account_id, before_date=start)
                opening += dr - cr
            movements = conn.execute(
                "SELECT je.entry_id,je.entry_date,je.entry_number,je.reference,je.narration,jl.account_id,jl.description,jl.debit,jl.credit,coa.account_name,coa.account_key "
                "FROM journal_lines jl JOIN journal_entries je ON je.entry_id=jl.entry_id "
                "JOIN chart_of_accounts coa ON coa.account_id=jl.account_id "
                "WHERE jl.business_id=? AND jl.account_id IN (SELECT account_id FROM chart_of_accounts WHERE business_id=? AND account_key IN ('cash','bank') AND is_active=1) "
                "AND je.entry_date BETWEEN ? AND ? ORDER BY je.entry_date,je.created_at,je.entry_number,jl.line_number",
                (business_id, business_id, start, end),
            ).fetchall()
            result = []
            inflows = outflows = ZERO
            for move in movements:
                counterparts = conn.execute(
                    "SELECT jl.debit,jl.credit,coa.account_name,coa.account_key,coa.account_type "
                    "FROM journal_lines jl JOIN chart_of_accounts coa ON coa.account_id=jl.account_id "
                    "WHERE jl.entry_id=? AND jl.account_id<>? ORDER BY jl.line_number",
                    (move["entry_id"], move["account_id"]),
                ).fetchall()
                counterpart_names = [str(r["account_name"]) for r in counterparts]
                counterpart_keys = {str(r["account_key"] or "") for r in counterparts}
                internal_transfer = bool(counterpart_keys) and counterpart_keys.issubset({"cash", "bank"})
                amount_in = _money(move["debit"])
                amount_out = _money(move["credit"])
                if internal_transfer:
                    activity = "Internal cash/bank transfer"
                elif any(str(r["account_key"] or "") in {"fixed_assets"} for r in counterparts):
                    activity = "Investing"
                elif any(str(r["account_key"] or "") in {"owners_capital", "retained_earnings"} for r in counterparts):
                    activity = "Financing"
                else:
                    activity = "Operating"
                if not internal_transfer:
                    inflows += amount_in
                    outflows += amount_out
                result.append({"date": move["entry_date"], "entry_number": move["entry_number"],
                               "reference": move["reference"], "narration": move["narration"],
                               "cash_account": move["account_name"], "counterpart": ", ".join(counterpart_names),
                               "activity": activity, "inflow": _money_text(amount_in), "outflow": _money_text(amount_out)})
            closing = ZERO
            for account_id in cash_ids:
                dr, cr = self._sum_account_lines_conn(conn, business_id, account_id, through_date=end)
                closing += dr - cr
        return {"start_date": start, "end_date": end, "opening_cash_bank": _money_text(opening),
                "inflows": _money_text(inflows), "outflows": _money_text(outflows),
                "net_change": _money_text(closing - opening), "closing_cash_bank": _money_text(closing),
                "rows": result, "note": "Based on recorded cash and bank accounts only. Reconcile bank statements for completeness."}

    def sales_register(self, business_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        start, end = _date(start_date), _date(end_date)
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT bill_number,invoice_date,customer_name,customer_gstin,customer_type,document_type,taxable_total,tax_total,grand_total,amount_paid,status "
                "FROM bills WHERE business_id=? AND invoice_date BETWEEN ? AND ? AND status IN ('issued','part_paid','paid','cancelled') ORDER BY invoice_date,bill_number",
                (business_id, start, end),
            ).fetchall()
        return [dict(r) for r in rows]

    def purchase_register(self, business_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        start, end = _date(start_date), _date(end_date)
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT pb.purchase_number,pb.supplier_invoice_number,pb.purchase_date,s.name AS supplier_name,s.gstin,pb.taxable_total,pb.tax_total,pb.grand_total,pb.amount_paid,pb.status "
                "FROM purchase_bills pb JOIN suppliers s ON s.supplier_id=pb.supplier_id WHERE pb.business_id=? AND pb.purchase_date BETWEEN ? AND ? AND pb.status IN ('posted','part_paid','paid') ORDER BY pb.purchase_date,pb.purchase_number",
                (business_id, start, end),
            ).fetchall()
        return [dict(r) for r in rows]

    def dashboard_summary(self, business_id: str, start_date: str, end_date: str) -> dict[str, str]:
        pl = self.profit_and_loss(business_id, start_date, end_date)
        tb = self.trial_balance(business_id, end_date)
        bs = self.balance_sheet(business_id, end_date)
        return {"revenue": pl["revenue"], "expenses": pl["expenses"], "net_profit": pl["net_profit"],
                "total_assets": bs["total_assets"], "total_payables": self._balance_for_key(business_id, "accounts_payable", end_date),
                "trial_balance": "Balanced" if tb["balanced"] else "Out of balance", "balance_sheet": "Balanced" if bs["balanced"] else "Out of balance"}

    def _balance_for_key(self, business_id: str, key: str, cutoff: str) -> str:
        self.ensure_chart(business_id)
        with self.database.connection() as conn:
            account = conn.execute("SELECT account_id,normal_side FROM chart_of_accounts WHERE business_id=? AND account_key=?", (business_id, key)).fetchone()
            dr, cr = self._sum_account_lines_conn(conn, business_id, str(account["account_id"]), through_date=_date(cutoff))
        delta = dr - cr
        if account["normal_side"] == "credit":
            delta = -delta
        return _money_text(delta)

    # ---------- Validation and audit internals ----------
    @staticmethod
    def _assert_actor_conn(conn, business_id: str, actor_user_id: str, permission: str) -> None:
        row = conn.execute("SELECT role FROM user_businesses WHERE business_id=? AND user_id=?", (business_id, actor_user_id)).fetchone()
        if not row:
            raise AccountingError("User does not belong to this business workspace.")
        role = str(row["role"])
        allowed = {
            "accounts.manage": {"owner", "admin", "accountant"},
            "accounts.journal_manage": {"owner", "admin", "accountant"},
            "accounts.period_lock": {"owner", "admin", "accountant"},
        }.get(permission, set())
        if role != "owner" and role not in allowed:
            raise AccountingError("Your role does not allow this accounting action.")

    @staticmethod
    def _audit_conn(conn, business_id: str, actor_user_id: str | None, action: str, entity_type: str,
                    entity_id: str, details: dict[str, Any]) -> None:
        import json
        conn.execute(
            "INSERT INTO audit_logs(audit_id,business_id,actor_user_id,action,entity_type,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("AUD"), business_id, actor_user_id, action, entity_type, entity_id,
             json.dumps(details, ensure_ascii=False, default=str), _now()),
        )
