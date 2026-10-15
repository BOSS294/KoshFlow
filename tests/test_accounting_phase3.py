"""Phase 3 accounting ledger and statement regression tests.

Purpose: Verify double-entry posting, source integration, financial statements and period locks.
Project: KoshFlow | Version: 0.6.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.6.0 — Tests for chart, journals, sales/purchase posting, statements and closed periods.
"""
from decimal import Decimal
from datetime import date

import pytest

from koshflow.services.accounting_service import AccountingError, AccountingService
from koshflow.services.bill_service import BillService
from koshflow.services.inventory_service import InventoryService
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


@pytest.fixture
def accounting_workspace(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    accounting = AccountingService(database)
    accounting.ensure_chart(business_id)
    return database, user_id, business_id, accounting


def test_chart_of_accounts_is_seeded_and_business_scoped(accounting_workspace):
    _, _, business_id, accounting = accounting_workspace
    accounts = accounting.list_accounts(business_id)
    assert len(accounts) >= 25
    assert any(row["account_key"] == "accounts_receivable" for row in accounts)
    assert any(row["account_key"] == "output_igst" for row in accounts)
    assert all(row["business_id"] == business_id for row in accounts)


def test_manual_journal_must_balance_and_trial_balance_reconciles(accounting_workspace):
    _, user_id, business_id, accounting = accounting_workspace
    accounts = {row["account_key"]: row for row in accounting.list_accounts(business_id)}
    entry_id = accounting.create_manual_journal(
        business_id, user_id, "2026-10-14", "Owner funds introduced", "CAP-001",
        [
            {"account_id": accounts["cash"]["account_id"], "debit": "12500.00", "credit": "0"},
            {"account_id": accounts["owners_capital"]["account_id"], "debit": "0", "credit": "12500.00"},
        ],
    )
    entry = accounting.get_entry(business_id, entry_id)
    assert entry and entry["status"] == "posted"
    assert entry["total_debit"] == entry["total_credit"] == "12500.00"
    trial_balance = accounting.trial_balance(business_id, "2026-10-14")
    assert trial_balance["balanced"] is True
    assert trial_balance["total_debit"] == trial_balance["total_credit"] == "12500.00"

    with pytest.raises(AccountingError, match="not balanced"):
        accounting.create_manual_journal(
            business_id, user_id, "2026-10-14", "Unbalanced attempt", "BAD-001",
            [
                {"account_id": accounts["cash"]["account_id"], "debit": "100.00", "credit": "0"},
                {"account_id": accounts["owners_capital"]["account_id"], "debit": "0", "credit": "99.00"},
            ],
        )


def test_sales_invoice_payment_and_statements_are_posted_automatically(accounting_workspace):
    _, user_id, business_id, accounting = accounting_workspace
    billing = BillService(accounting.database)
    billing.ensure_starter_templates(business_id)
    bill_id = billing.create_bill(business_id, user_id, {
        "customer_type": "B2C", "document_type": "tax_invoice", "customer_name": "Report Customer",
        "invoice_date": "2026-10-14", "due_date": "2026-10-28", "invoice_discount": "0",
        "items": [{"description": "Consulting work", "quantity": "1", "unit": "job",
                    "unit_price": "1000", "discount_percent": "0", "tax_rate": "18"}],
    })
    billing.issue_bill(business_id, user_id, bill_id)

    entries = accounting.list_entries(business_id)
    assert any(row["source_type"] == "bill" and row["source_event"] == "issued" for row in entries)
    pl = accounting.profit_and_loss(business_id, "2026-10-01", "2026-10-31")
    assert pl["revenue"] == "1000.00"
    assert pl["expenses"] == "0.00"
    assert pl["net_profit"] == "1000.00"
    bs = accounting.balance_sheet(business_id, "2026-10-14")
    assert bs["balanced"] is True
    assert bs["total_assets"] == "1180.00"
    assert bs["total_liabilities"] == "180.00"
    assert bs["total_equity"] == "1000.00"
    gst = accounting.gst_summary(business_id, "2026-10-01", "2026-10-31")
    assert gst["output_tax"] == "180.00"
    assert gst["net_payable"] == "180.00"
    hsn = accounting.hsn_sac_summary(business_id, "2026-10-01", "2026-10-31")
    assert hsn["taxable_total"] == "1000.00"
    assert hsn["tax_total"] == "180.00"
    cash_flow = accounting.cash_flow_statement(business_id, "2026-10-01", "2026-10-31")
    assert cash_flow["opening_cash_bank"] == "0.00"
    assert cash_flow["inflows"] == "0.00"  # Issuing an invoice is not cash collection.
    assert cash_flow["closing_cash_bank"] == "0.00"

    billing.record_payment(business_id, user_id, bill_id, "1180", "Cash", "RCPT-001", "2026-10-14")
    trial_balance = accounting.trial_balance(business_id, "2026-10-14")
    assert trial_balance["balanced"] is True
    assert trial_balance["total_debit"] == trial_balance["total_credit"]
    bs_paid = accounting.balance_sheet(business_id, "2026-10-14")
    assert bs_paid["balanced"] is True
    assert bs_paid["total_assets"] == "1180.00"
    paid_cash_flow = accounting.cash_flow_statement(business_id, "2026-10-01", "2026-10-31")
    assert paid_cash_flow["inflows"] == "1180.00"
    assert paid_cash_flow["outflows"] == "0.00"
    assert paid_cash_flow["net_change"] == "1180.00"


def test_cancelled_invoice_posts_an_auditable_reversal(accounting_workspace):
    _, user_id, business_id, accounting = accounting_workspace
    billing = BillService(accounting.database)
    billing.ensure_starter_templates(business_id)
    bill_id = billing.create_bill(business_id, user_id, {
        "customer_type": "B2C", "document_type": "tax_invoice", "customer_name": "Cancel Customer",
        "invoice_date": "2026-10-14", "items": [{"description": "Work", "quantity": "1", "unit": "job",
        "unit_price": "500", "discount_percent": "0", "tax_rate": "0"}],
    })
    # Issue in September, then cancel in October: the HSN support report retains
    # the original sale in September and applies a negative row in the cancellation period.
    with accounting.database.transaction() as conn:
        conn.execute("UPDATE bills SET invoice_date='2026-09-30' WHERE business_id=? AND bill_id=?", (business_id, bill_id))
    billing.issue_bill(business_id, user_id, bill_id)
    billing.cancel_bill(business_id, user_id, bill_id, "Created against wrong customer")
    september_hsn = accounting.hsn_sac_summary(business_id, "2026-09-01", "2026-09-30")
    october_hsn = accounting.hsn_sac_summary(business_id, "2026-10-01", "2026-10-31")
    assert september_hsn["taxable_total"] == "500.00"
    assert october_hsn["taxable_total"] == "-500.00"
    entries = accounting.list_entries(business_id)
    assert any(row["source_type"] == "bill" and row["source_event"] == "issued" for row in entries)
    assert any(row["source_type"] == "bill" and row["source_event"] == "cancelled" for row in entries)
    tb = accounting.trial_balance(business_id, date.today().isoformat())
    assert tb["balanced"] is True
    assert tb["total_debit"] == "0.00"
    assert tb["total_credit"] == "0.00"


def test_purchase_bill_and_supplier_payment_post_without_double_counting_stock(accounting_workspace):
    database, user_id, business_id, accounting = accounting_workspace
    inventory = InventoryService(database)
    supplier_id = inventory.create_supplier(business_id, user_id, {
        "supplier_code": "SUP-ACC-001", "name": "Ledger Supplier", "phone": "9876543210",
    })
    product_id = inventory.create_product(business_id, user_id, {
        "sku": "ACC-PROD-001", "name": "Ledger Item", "category": "General", "unit": "pcs",
        "purchase_price": "100", "selling_price": "150", "tax_rate": "18", "reorder_level": "0",
        "opening_quantity": "0",
    })
    purchase_id = inventory.create_purchase_bill(business_id, user_id, {
        "supplier_id": supplier_id, "document_date": "2026-10-14", "due_date": "2026-10-28",
        "supplier_invoice_number": "SUP-INV-ACC-001", "items": [{"product_id": product_id,
        "quantity": "5", "unit_cost": "100", "tax_rate": "18", "discount_percent": "0"}],
    })
    inventory.post_purchase_bill(business_id, user_id, purchase_id)
    assert inventory.get_product(business_id, product_id)["quantity_on_hand"] == "5.000"
    tb = accounting.trial_balance(business_id, "2026-10-14")
    assert tb["balanced"] is True
    bs = accounting.balance_sheet(business_id, "2026-10-14")
    assert bs["balanced"] is True
    assert bs["total_assets"] == "590.00"
    assert bs["total_liabilities"] == "590.00"

    inventory.record_supplier_payment(business_id, user_id, purchase_id, "100", "Bank transfer", "BANK-001", "2026-10-14")
    tb_after_payment = accounting.trial_balance(business_id, "2026-10-14")
    assert tb_after_payment["balanced"] is True
    bs_after_payment = accounting.balance_sheet(business_id, "2026-10-14")
    assert bs_after_payment["balanced"] is True
    assert bs_after_payment["total_assets"] == "490.00"
    assert bs_after_payment["total_liabilities"] == "490.00"


def test_period_lock_blocks_backdated_journal_and_overlapping_lock(accounting_workspace):
    _, user_id, business_id, accounting = accounting_workspace
    accounting.lock_period(business_id, user_id, "2026-07-01", "2026-07-31", "Quarter close review")
    with pytest.raises(AccountingError, match="locked"):
        accounting.create_manual_journal(
            business_id, user_id, "2026-07-15", "Backdated correction", "JRN-LOCK",
            [
                {"account_key": "cash", "debit": "10.00", "credit": "0"},
                {"account_key": "owners_capital", "debit": "0", "credit": "10.00"},
            ],
        )
    with pytest.raises(AccountingError, match="overlaps"):
        accounting.lock_period(business_id, user_id, "2026-07-15", "2026-08-15", "Overlapping lock")
    lock = accounting.list_period_locks(business_id)[0]
    accounting.unlock_period(business_id, user_id, lock["period_lock_id"], "Adjustment approved by owner")
    assert accounting.list_period_locks(business_id)[0]["unlocked_at"]
    # A reopened period accepts a corrected journal and preserves the reopen audit history.
    accounting.create_manual_journal(
        business_id, user_id, "2026-07-15", "Approved historical adjustment", "JRN-REOPEN",
        [
            {"account_key": "cash", "debit": "10.00", "credit": "0"},
            {"account_key": "owners_capital", "debit": "0", "credit": "10.00"},
        ],
    )
    assert accounting.trial_balance(business_id, "2026-07-31")["balanced"] is True
