"""SQLite database setup and transaction helpers.

Purpose: Provide a local-first database, versioned schema, safe transactions,
         and app identity validation.
Project: KoshFlow | Version: 0.6.2
Canonical path: koshflow/core/database.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Instantiate Database(path), then call initialize() once at startup.
Changelog: v0.6.2 — Added persistent local notifications for desktop alerts and the in-app notification center.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from koshflow.config import APP_ID, SCHEMA_VERSION


class DatabaseError(RuntimeError):
    """Raised when the local database cannot be safely initialized or opened."""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_meta (
    meta_key TEXT PRIMARY KEY,
    meta_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS businesses (
    business_id TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL,
    trade_name TEXT NOT NULL DEFAULT '',
    business_type TEXT NOT NULL DEFAULT 'Other',
    address TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    pincode TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    gstin TEXT NOT NULL DEFAULT '',
    pan TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'INR',
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    fiscal_year_start_month INTEGER NOT NULL DEFAULT 4 CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    fiscal_year_start_day INTEGER NOT NULL DEFAULT 1 CHECK (fiscal_year_start_day BETWEEN 1 AND 31),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS user_businesses (
    membership_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'accountant', 'manager', 'cashier', 'viewer')),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(user_id, business_id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    setting_scope TEXT NOT NULL DEFAULT 'app',
    scope_id TEXT NOT NULL DEFAULT '',
    setting_key TEXT NOT NULL,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(setting_scope, scope_id, setting_key)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id TEXT PRIMARY KEY,
    business_id TEXT REFERENCES businesses(business_id) ON DELETE SET NULL,
    actor_user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_businesses_user ON user_businesses(user_id);
CREATE INDEX IF NOT EXISTS idx_user_businesses_business ON user_businesses(business_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_business_date ON audit_logs(business_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE CASCADE,
    alert_key TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('receivables','payables','inventory','purchasing','system','tax')),
    severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','success','warning','critical')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    related_page TEXT NOT NULL DEFAULT '',
    related_id TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0,1)),
    is_dismissed INTEGER NOT NULL DEFAULT 0 CHECK (is_dismissed IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, alert_key)
);
CREATE INDEX IF NOT EXISTS idx_notifications_business_active ON notifications(business_id, is_active, is_read, is_dismissed, updated_at DESC);

CREATE TABLE IF NOT EXISTS pdf_templates (
    template_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE CASCADE,
    template_name TEXT NOT NULL,
    page_size TEXT NOT NULL DEFAULT 'A4' CHECK (page_size IN ('A4', 'A5', 'THERMAL_80')),
    accent_color TEXT NOT NULL DEFAULT '#C9E86A',
    font_family TEXT NOT NULL DEFAULT 'Helvetica',
    font_size INTEGER NOT NULL DEFAULT 9 CHECK (font_size BETWEEN 7 AND 18),
    show_logo INTEGER NOT NULL DEFAULT 0 CHECK (show_logo IN (0, 1)),
    show_business_contact INTEGER NOT NULL DEFAULT 1 CHECK (show_business_contact IN (0, 1)),
    show_gstin INTEGER NOT NULL DEFAULT 1 CHECK (show_gstin IN (0, 1)),
    footer_text TEXT NOT NULL DEFAULT 'Thank you for your business.',
    layout_json TEXT NOT NULL DEFAULT '{}',
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, template_name)
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    customer_code TEXT NOT NULL COLLATE NOCASE,
    name TEXT NOT NULL,
    customer_type TEXT NOT NULL DEFAULT 'individual' CHECK (customer_type IN ('individual', 'business')),
    contact_person TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    alternate_phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    gstin TEXT NOT NULL DEFAULT '',
    pan TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    pincode TEXT NOT NULL DEFAULT '',
    credit_limit TEXT NOT NULL DEFAULT '0.00',
    payment_terms_days INTEGER NOT NULL DEFAULT 0 CHECK (payment_terms_days BETWEEN 0 AND 365),
    notes TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, customer_code)
);
CREATE INDEX IF NOT EXISTS idx_customers_business_active ON customers(business_id, is_active, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_customers_business_phone ON customers(business_id, phone);

CREATE TABLE IF NOT EXISTS bills (
    bill_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    customer_id TEXT REFERENCES customers(customer_id) ON DELETE SET NULL,
    bill_number TEXT NOT NULL,
    document_type TEXT NOT NULL DEFAULT 'tax_invoice' CHECK (document_type IN ('tax_invoice', 'bill_of_supply', 'proforma', 'estimate')),
    customer_type TEXT NOT NULL DEFAULT 'B2C' CHECK (customer_type IN ('B2B', 'B2C')),
    customer_name TEXT NOT NULL,
    customer_phone TEXT NOT NULL DEFAULT '',
    customer_email TEXT NOT NULL DEFAULT '',
    customer_gstin TEXT NOT NULL DEFAULT '',
    customer_address TEXT NOT NULL DEFAULT '',
    place_of_supply TEXT NOT NULL DEFAULT '',
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    terms TEXT NOT NULL DEFAULT '',
    subtotal TEXT NOT NULL DEFAULT '0.00',
    discount_total TEXT NOT NULL DEFAULT '0.00',
    invoice_discount TEXT NOT NULL DEFAULT '0.00',
    taxable_total TEXT NOT NULL DEFAULT '0.00',
    tax_total TEXT NOT NULL DEFAULT '0.00',
    grand_total TEXT NOT NULL DEFAULT '0.00',
    amount_paid TEXT NOT NULL DEFAULT '0.00',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'issued', 'part_paid', 'paid', 'cancelled')),
    template_id TEXT REFERENCES pdf_templates(template_id) ON DELETE SET NULL,
    created_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    issued_at TEXT,
    UNIQUE(business_id, bill_number)
);

CREATE TABLE IF NOT EXISTS bill_items (
    bill_item_id TEXT PRIMARY KEY,
    bill_id TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    product_id TEXT REFERENCES products(product_id) ON DELETE RESTRICT,
    row_order INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL,
    hsn_sac TEXT NOT NULL DEFAULT '',
    quantity TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'pcs',
    unit_price TEXT NOT NULL,
    discount_percent TEXT NOT NULL DEFAULT '0',
    tax_rate TEXT NOT NULL DEFAULT '0',
    taxable_value TEXT NOT NULL DEFAULT '0.00',
    tax_amount TEXT NOT NULL DEFAULT '0.00',
    line_total TEXT NOT NULL DEFAULT '0.00'
);

CREATE TABLE IF NOT EXISTS bill_payments (
    payment_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    bill_id TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE RESTRICT,
    amount TEXT NOT NULL,
    payment_method TEXT NOT NULL DEFAULT 'UPI' CHECK (payment_method IN ('Cash', 'UPI', 'Bank transfer', 'Card', 'Cheque', 'Other')),
    reference TEXT NOT NULL DEFAULT '',
    paid_at TEXT NOT NULL,
    created_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bills_business_date ON bills(business_id, invoice_date DESC);
CREATE INDEX IF NOT EXISTS idx_bills_business_status ON bills(business_id, status);
CREATE INDEX IF NOT EXISTS idx_bill_items_bill ON bill_items(bill_id, row_order);
CREATE INDEX IF NOT EXISTS idx_bill_payments_bill ON bill_payments(bill_id, paid_at DESC);
CREATE INDEX IF NOT EXISTS idx_pdf_templates_business ON pdf_templates(business_id, is_default DESC, template_name);

-- Inventory master records. Quantities and money are stored as decimal text and
-- are parsed with Decimal in the service layer to avoid binary float rounding.
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    sku TEXT NOT NULL COLLATE NOCASE,
    barcode TEXT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'General',
    hsn_code TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'pcs',
    last_purchase_price TEXT NOT NULL DEFAULT '0.00',
    average_cost TEXT NOT NULL DEFAULT '0.00',
    selling_price TEXT NOT NULL DEFAULT '0.00',
    tax_rate TEXT NOT NULL DEFAULT '0.00',
    reorder_level TEXT NOT NULL DEFAULT '0.000',
    quantity_on_hand TEXT NOT NULL DEFAULT '0.000',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, sku),
    UNIQUE(business_id, barcode)
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    supplier_code TEXT NOT NULL COLLATE NOCASE,
    name TEXT NOT NULL,
    contact_person TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    gstin TEXT NOT NULL DEFAULT '',
    pan TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    pincode TEXT NOT NULL DEFAULT '',
    payment_terms_days INTEGER NOT NULL DEFAULT 0 CHECK (payment_terms_days BETWEEN 0 AND 365),
    notes TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, supplier_code)
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    purchase_order_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    order_number TEXT NOT NULL,
    order_date TEXT NOT NULL,
    expected_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ordered', 'partially_received', 'received', 'cancelled')),
    subtotal TEXT NOT NULL DEFAULT '0.00',
    discount_total TEXT NOT NULL DEFAULT '0.00',
    taxable_total TEXT NOT NULL DEFAULT '0.00',
    tax_total TEXT NOT NULL DEFAULT '0.00',
    grand_total TEXT NOT NULL DEFAULT '0.00',
    notes TEXT NOT NULL DEFAULT '',
    created_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, order_number)
);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    purchase_order_item_id TEXT PRIMARY KEY,
    purchase_order_id TEXT NOT NULL REFERENCES purchase_orders(purchase_order_id) ON DELETE CASCADE,
    row_order INTEGER NOT NULL DEFAULT 0,
    product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    product_name TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity TEXT NOT NULL,
    received_quantity TEXT NOT NULL DEFAULT '0.000',
    unit TEXT NOT NULL DEFAULT 'pcs',
    unit_cost TEXT NOT NULL,
    discount_percent TEXT NOT NULL DEFAULT '0.00',
    tax_rate TEXT NOT NULL DEFAULT '0.00',
    taxable_value TEXT NOT NULL DEFAULT '0.00',
    tax_amount TEXT NOT NULL DEFAULT '0.00',
    line_total TEXT NOT NULL DEFAULT '0.00'
);

CREATE TABLE IF NOT EXISTS purchase_bills (
    purchase_bill_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    source_purchase_order_id TEXT REFERENCES purchase_orders(purchase_order_id) ON DELETE RESTRICT,
    purchase_number TEXT NOT NULL,
    supplier_invoice_number TEXT NOT NULL DEFAULT '',
    purchase_date TEXT NOT NULL,
    due_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'part_paid', 'paid', 'cancelled')),
    subtotal TEXT NOT NULL DEFAULT '0.00',
    discount_total TEXT NOT NULL DEFAULT '0.00',
    taxable_total TEXT NOT NULL DEFAULT '0.00',
    tax_total TEXT NOT NULL DEFAULT '0.00',
    grand_total TEXT NOT NULL DEFAULT '0.00',
    amount_paid TEXT NOT NULL DEFAULT '0.00',
    notes TEXT NOT NULL DEFAULT '',
    created_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    posted_at TEXT,
    UNIQUE(business_id, purchase_number)
);

CREATE TABLE IF NOT EXISTS purchase_items (
    purchase_item_id TEXT PRIMARY KEY,
    purchase_bill_id TEXT NOT NULL REFERENCES purchase_bills(purchase_bill_id) ON DELETE CASCADE,
    row_order INTEGER NOT NULL DEFAULT 0,
    product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    product_name TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'pcs',
    unit_cost TEXT NOT NULL,
    discount_percent TEXT NOT NULL DEFAULT '0.00',
    tax_rate TEXT NOT NULL DEFAULT '0.00',
    taxable_value TEXT NOT NULL DEFAULT '0.00',
    tax_amount TEXT NOT NULL DEFAULT '0.00',
    line_total TEXT NOT NULL DEFAULT '0.00'
);

CREATE TABLE IF NOT EXISTS supplier_payments (
    supplier_payment_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    purchase_bill_id TEXT NOT NULL REFERENCES purchase_bills(purchase_bill_id) ON DELETE RESTRICT,
    amount TEXT NOT NULL,
    payment_method TEXT NOT NULL DEFAULT 'Bank transfer' CHECK (payment_method IN ('Cash', 'UPI', 'Bank transfer', 'Card', 'Cheque', 'Other')),
    reference TEXT NOT NULL DEFAULT '',
    paid_at TEXT NOT NULL,
    created_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supplier_returns (
    supplier_return_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    purchase_bill_id TEXT NOT NULL REFERENCES purchase_bills(purchase_bill_id) ON DELETE RESTRICT,
    return_number TEXT NOT NULL,
    return_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
    subtotal TEXT NOT NULL DEFAULT '0.00',
    tax_total TEXT NOT NULL DEFAULT '0.00',
    grand_total TEXT NOT NULL DEFAULT '0.00',
    reason TEXT NOT NULL,
    created_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    posted_at TEXT,
    UNIQUE(business_id, return_number)
);

CREATE TABLE IF NOT EXISTS supplier_return_items (
    supplier_return_item_id TEXT PRIMARY KEY,
    supplier_return_id TEXT NOT NULL REFERENCES supplier_returns(supplier_return_id) ON DELETE CASCADE,
    purchase_item_id TEXT NOT NULL REFERENCES purchase_items(purchase_item_id) ON DELETE RESTRICT,
    product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    product_name TEXT NOT NULL,
    quantity TEXT NOT NULL,
    unit_cost TEXT NOT NULL,
    discount_percent TEXT NOT NULL DEFAULT '0.00',
    tax_rate TEXT NOT NULL DEFAULT '0.00',
    taxable_value TEXT NOT NULL DEFAULT '0.00',
    tax_amount TEXT NOT NULL DEFAULT '0.00',
    line_total TEXT NOT NULL DEFAULT '0.00'
);

CREATE TABLE IF NOT EXISTS stock_movements (
    stock_movement_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('opening', 'purchase', 'purchase_order_receipt', 'sale', 'sale_return', 'supplier_return', 'adjustment_in', 'adjustment_out', 'reversal')),
    quantity_delta TEXT NOT NULL,
    quantity_before TEXT NOT NULL DEFAULT '0.000',
    quantity_after TEXT NOT NULL DEFAULT '0.000',
    unit_cost TEXT NOT NULL DEFAULT '0.00',
    movement_value TEXT NOT NULL DEFAULT '0.00',
    source_type TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_business_active ON products(business_id, is_active, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_products_business_category ON products(business_id, category COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_suppliers_business_active ON suppliers(business_id, is_active, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_business_date ON purchase_orders(business_id, order_date DESC);
CREATE INDEX IF NOT EXISTS idx_purchase_bills_business_date ON purchase_bills(business_id, purchase_date DESC);
CREATE INDEX IF NOT EXISTS idx_purchase_items_bill ON purchase_items(purchase_bill_id, row_order);
CREATE INDEX IF NOT EXISTS idx_purchase_order_items_order ON purchase_order_items(purchase_order_id, row_order);
CREATE INDEX IF NOT EXISTS idx_supplier_payments_bill ON supplier_payments(purchase_bill_id, paid_at DESC);
CREATE INDEX IF NOT EXISTS idx_supplier_returns_bill ON supplier_returns(purchase_bill_id, return_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_movements_business_date ON stock_movements(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_movements_product_date ON stock_movements(product_id, created_at DESC);
"""


# Double-entry general ledger and period controls added in v0.6.0.
ACCOUNTING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chart_of_accounts (
    account_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    account_code TEXT NOT NULL COLLATE NOCASE,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('asset','liability','equity','income','expense')),
    normal_side TEXT NOT NULL CHECK (normal_side IN ('debit','credit')),
    account_key TEXT,
    description TEXT NOT NULL DEFAULT '',
    is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0,1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, account_code),
    UNIQUE(business_id, account_key)
);
CREATE INDEX IF NOT EXISTS idx_coa_business_type ON chart_of_accounts(business_id, account_type, account_code);

CREATE TABLE IF NOT EXISTS journal_entries (
    entry_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    entry_number TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    narration TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_event TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'posted' CHECK (status IN ('posted','reversed')),
    reversal_of_entry_id TEXT REFERENCES journal_entries(entry_id) ON DELETE RESTRICT,
    total_debit TEXT NOT NULL DEFAULT '0.00',
    total_credit TEXT NOT NULL DEFAULT '0.00',
    created_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    UNIQUE(business_id, entry_number),
    UNIQUE(business_id, source_type, source_id, source_event)
);
CREATE INDEX IF NOT EXISTS idx_journal_entries_business_date ON journal_entries(business_id, entry_date DESC, entry_number DESC);
CREATE INDEX IF NOT EXISTS idx_journal_entries_source ON journal_entries(business_id, source_type, source_id);

CREATE TABLE IF NOT EXISTS journal_lines (
    journal_line_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    entry_id TEXT NOT NULL REFERENCES journal_entries(entry_id) ON DELETE RESTRICT,
    account_id TEXT NOT NULL REFERENCES chart_of_accounts(account_id) ON DELETE RESTRICT,
    line_number INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    debit TEXT NOT NULL DEFAULT '0.00',
    credit TEXT NOT NULL DEFAULT '0.00',
    created_at TEXT NOT NULL,
    UNIQUE(entry_id, line_number)
);
CREATE INDEX IF NOT EXISTS idx_journal_lines_account_entry ON journal_lines(business_id, account_id, entry_id);

CREATE TABLE IF NOT EXISTS accounting_period_locks (
    period_lock_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id) ON DELETE RESTRICT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    reason TEXT NOT NULL,
    locked_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    locked_at TEXT NOT NULL,
    unlocked_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    unlocked_at TEXT,
    unlock_reason TEXT NOT NULL DEFAULT '',
    CHECK (start_date <= end_date)
);
CREATE INDEX IF NOT EXISTS idx_accounting_locks_range ON accounting_period_locks(business_id, start_date, end_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounting_locks_active_exact ON accounting_period_locks(business_id, start_date, end_date) WHERE unlocked_at IS NULL;
"""


class Database:
    """Small SQLite boundary; every operation owns and closes its connection."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def initialize(self) -> None:
        """Initialize or migrate the local database without discarding records."""
        try:
            with self.connection() as conn:
                existing_tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing_tables:
                    has_meta = any(row[0] == "app_meta" for row in existing_tables)
                    if not has_meta:
                        raise DatabaseError(
                            "The selected database file is not a recognized KoshFlow database. It was not modified."
                        )
                    existing_app_id = conn.execute(
                        "SELECT meta_value FROM app_meta WHERE meta_key = 'app_id'"
                    ).fetchone()
                    if not existing_app_id or existing_app_id[0] != APP_ID:
                        raise DatabaseError(
                            "This database belongs to a different application and was not opened."
                        )
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                conn.executescript(SCHEMA_SQL)
                conn.executescript(ACCOUNTING_SCHEMA_SQL)
                # Defensive additive migration: preserve any early development bills table.
                bill_columns = {row[1] for row in conn.execute("PRAGMA table_info(bills)").fetchall()}
                if bill_columns and "invoice_discount" not in bill_columns:
                    conn.execute("ALTER TABLE bills ADD COLUMN invoice_discount TEXT NOT NULL DEFAULT '0.00'")
                item_columns = {row[1] for row in conn.execute("PRAGMA table_info(bill_items)").fetchall()}
                if item_columns and "product_id" not in item_columns:
                    conn.execute("ALTER TABLE bill_items ADD COLUMN product_id TEXT REFERENCES products(product_id) ON DELETE RESTRICT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_items_product ON bill_items(product_id)")
                bill_columns = {row[1] for row in conn.execute("PRAGMA table_info(bills)").fetchall()}
                if bill_columns and "customer_id" not in bill_columns:
                    conn.execute("ALTER TABLE bills ADD COLUMN customer_id TEXT REFERENCES customers(customer_id) ON DELETE SET NULL")
                movement_columns = {row[1] for row in conn.execute("PRAGMA table_info(stock_movements)").fetchall()}
                movement_metadata_added = False
                if movement_columns and "quantity_before" not in movement_columns:
                    conn.execute("ALTER TABLE stock_movements ADD COLUMN quantity_before TEXT NOT NULL DEFAULT '0.000'")
                    movement_metadata_added = True
                if movement_columns and "quantity_after" not in movement_columns:
                    conn.execute("ALTER TABLE stock_movements ADD COLUMN quantity_after TEXT NOT NULL DEFAULT '0.000'")
                    movement_metadata_added = True
                if movement_columns and "movement_value" not in movement_columns:
                    conn.execute("ALTER TABLE stock_movements ADD COLUMN movement_value TEXT NOT NULL DEFAULT '0.00'")
                    movement_metadata_added = True
                if movement_metadata_added:
                    # Backfill historical balance snapshots in insertion order, per product.
                    # The source ledger is retained; this only fills additive display metadata.
                    movement_rows = conn.execute("SELECT rowid, business_id, product_id, quantity_delta, unit_cost FROM stock_movements ORDER BY created_at, rowid").fetchall()
                    balances = {}
                    for movement in movement_rows:
                        key = (movement["business_id"], movement["product_id"])
                        before = balances.get(key, 0)
                        delta = float(movement["quantity_delta"] or 0)
                        after = round(before + delta, 3)
                        value = round(abs(delta) * float(movement["unit_cost"] or 0), 2)
                        conn.execute("UPDATE stock_movements SET quantity_before=?, quantity_after=?, movement_value=? WHERE rowid=?",
                                     (f"{before:.3f}", f"{after:.3f}", f"{value:.2f}", movement["rowid"]))
                        balances[key] = after
                return_item_columns = {row[1] for row in conn.execute("PRAGMA table_info(supplier_return_items)").fetchall()}
                if return_item_columns and "discount_percent" not in return_item_columns:
                    conn.execute("ALTER TABLE supplier_return_items ADD COLUMN discount_percent TEXT NOT NULL DEFAULT '0.00'")
                stored_app_id = conn.execute(
                    "SELECT meta_value FROM app_meta WHERE meta_key = 'app_id'"
                ).fetchone()
                if stored_app_id and stored_app_id[0] != APP_ID:
                    raise DatabaseError(
                        "This database belongs to a different application and was not opened."
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO app_meta(meta_key, meta_value) VALUES('app_id', ?)",
                    (APP_ID,),
                )
                conn.execute(
                    "INSERT INTO app_meta(meta_key, meta_value) VALUES('schema_version', ?) "
                    "ON CONFLICT(meta_key) DO UPDATE SET meta_value = excluded.meta_value",
                    (str(SCHEMA_VERSION),),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)",
                    (SCHEMA_VERSION,),
                )
                conn.commit()
        except DatabaseError:
            raise
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(f"Local database initialization failed: {exc}") from exc

    def integrity_check(self) -> str:
        with self.connection() as conn:
            return str(conn.execute("PRAGMA integrity_check").fetchone()[0])

    def has_users(self) -> bool:
        with self.connection() as conn:
            row = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return row is not None

    def get_setting(self, key: str, default: str | None = None,
                    scope: str = "app", scope_id: str = "") -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_scope = ? AND scope_id = ? AND setting_key = ?",
                (scope, scope_id, key),
            ).fetchone()
        return str(row[0]) if row else default

    def set_setting(self, key: str, value: str, scope: str = "app",
                    scope_id: str = "") -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO app_settings(setting_scope, scope_id, setting_key, setting_value, updated_at) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(setting_scope, scope_id, setting_key) DO UPDATE SET "
                "setting_value = excluded.setting_value, updated_at = excluded.updated_at",
                (scope, scope_id, key, value, now),
            )
