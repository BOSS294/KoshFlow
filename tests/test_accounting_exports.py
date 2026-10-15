"""Trading account and accounting PDF export regression tests.

Purpose: Ensure ledger-backed trading statements and PDF exports are generated without fabricated figures.
Project: KoshFlow | Version: 0.6.2
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.6.2 — Retained trading account, journal register and branded accounting PDF export coverage.
"""
from pathlib import Path

from koshflow.services.accounting_service import AccountingService
from koshflow.services.accounting_export_service import generate_accounting_report_pdf
from koshflow.services.bill_service import BillService
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


def test_trading_account_uses_sales_and_ledger_cogs(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    accounting = AccountingService(database)
    billing = BillService(database)
    billing.ensure_starter_templates(business_id)
    bill_id = billing.create_bill(business_id, user_id, {
        "customer_type": "B2C", "document_type": "tax_invoice", "customer_name": "Trading Customer",
        "invoice_date": "2026-10-14", "due_date": "2026-10-28", "invoice_discount": "0",
        "items": [{"description": "Consulting", "quantity": "1", "unit": "job", "unit_price": "1250.00",
                    "discount_percent": "0", "tax_rate": "0"}],
    })
    billing.issue_bill(business_id, user_id, bill_id)

    report = accounting.trading_account(business_id, "2026-10-01", "2026-10-31")
    assert report["net_sales"] == "1250.00"
    assert report["cost_of_goods_sold"] == "0.00"
    assert report["gross_profit"] == "1250.00"
    assert report["basis"].startswith("Perpetual inventory")
    assert any("context only" in row["particulars"] for row in report["rows"])


def test_journal_register_date_filters_and_balances(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    accounting = AccountingService(database)
    accounts = {row["account_key"]: row for row in accounting.list_accounts(business_id)}
    accounting.create_manual_journal(business_id, user_id, "2026-10-14", "Capital introduced", "CAP-EXPORT-001", [
        {"account_id": accounts["cash"]["account_id"], "debit": "9876.54", "credit": "0"},
        {"account_id": accounts["owners_capital"]["account_id"], "debit": "0", "credit": "9876.54"},
    ])
    report = accounting.journal_register(business_id, "2026-10-01", "2026-10-31")
    assert report["count"] == 1
    assert report["balanced"] is True
    assert report["total_debit"] == report["total_credit"] == "9876.54"
    assert accounting.journal_register(business_id, "2026-09-01", "2026-09-30")["count"] == 0


def test_accounting_report_pdf_creates_valid_pdf_with_header_and_table(database, tmp_path):
    _, business_id = SetupService(database).complete_setup(valid_setup())
    path = tmp_path / "trading-account.pdf"
    result = generate_accounting_report_pdf(
        database, business_id, path, "Trading Account", "01 Oct 2026 to 31 Oct 2026",
        ["Section", "Code", "Particulars", "Amount"],
        [["Trading", "4000", "Net sales", "₹ 1,250.00"],
         ["Trading", "5000", "Cost of goods sold", "₹ 0.00"],
         ["Trading", "", "GROSS PROFIT / (LOSS)", "₹ 1,250.00"]],
    )
    assert result == path.resolve()
    assert path.is_file()
    raw = path.read_bytes()
    assert raw.startswith(b"%PDF-")
    assert len(raw) > 1500


def test_trading_account_uses_cogs_and_inventory_memo_balances(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    accounting = AccountingService(database)
    accounts = {row["account_key"]: row for row in accounting.list_accounts(business_id)}

    def account_line(key, debit="0", credit="0"):
        return {"account_id": accounts[key]["account_id"], "debit": debit, "credit": credit}

    accounting.create_manual_journal(business_id, user_id, "2026-09-30", "Opening inventory", "OPEN-INV-01", [
        account_line("inventory", debit="2000.00"), account_line("opening_equity", credit="2000.00"),
    ])
    accounting.create_manual_journal(business_id, user_id, "2026-10-14", "Sale on account", "SALE-TRADE-01", [
        account_line("accounts_receivable", debit="1300.00"), account_line("sales_revenue", credit="1300.00"),
    ])
    accounting.create_manual_journal(business_id, user_id, "2026-10-14", "Cost of sale", "COGS-TRADE-01", [
        account_line("cogs", debit="300.00"), account_line("inventory", credit="300.00"),
    ])

    report = accounting.trading_account(business_id, "2026-10-01", "2026-10-31")
    assert report["net_sales"] == "1300.00"
    assert report["cost_of_goods_sold"] == "300.00"
    assert report["gross_profit"] == "1000.00"
    assert report["opening_inventory"] == "2000.00"
    assert report["closing_inventory"] == "1700.00"
