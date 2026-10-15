"""Data accuracy tests for the connected business Reports workspace.

Purpose: Verify operational report tables contain transaction-backed figures and filter by date/business.
Project: KoshFlow | Version: 0.6.2
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.6.2 — Added tests for inventory, customer/supplier balances and payment report data.
"""
from decimal import Decimal

from koshflow.services.bill_service import BillService
from koshflow.services.accounting_export_service import generate_accounting_report_pdf
from koshflow.services.inventory_service import InventoryService
from koshflow.services.operational_report_service import OperationalReportService
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


def test_all_operational_reports_are_business_scoped_and_return_matching_headers(database, tmp_path):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    inventory = InventoryService(database)
    product_id = inventory.create_product(business_id, user_id, {
        "sku": "SKU-REPORT-1", "name": "Report Product", "category": "Tools", "unit": "pcs",
        "purchase_price": "20.00", "selling_price": "35.00", "tax_rate": "18",
        "reorder_level": "20", "opening_quantity": "10",
    })
    supplier_id = inventory.create_supplier(business_id, user_id, {
        "supplier_code": "SUP-REPORT-1", "name": "Report Supplier", "phone": "9876543210",
        "payment_terms_days": 14,
    })
    purchase_id = inventory.create_purchase_bill(business_id, user_id, {
        "supplier_id": supplier_id, "document_date": "2026-10-14", "due_date": "2026-10-14",
        "supplier_invoice_number": "SUP-REPORT-INV-1",
        "items": [{"product_id": product_id, "quantity": "3", "unit_cost": "22", "tax_rate": "18", "discount_percent": "0"}],
    })
    inventory.post_purchase_bill(business_id, user_id, purchase_id)
    inventory.record_supplier_payment(business_id, user_id, purchase_id, "25", "UPI", "SUP-UTR-1", "2026-10-14")

    billing = BillService(database)
    billing.ensure_starter_templates(business_id)
    bill_id = billing.create_bill(business_id, user_id, {
        "customer_type": "B2C", "document_type": "tax_invoice", "customer_name": "Report Customer",
        "customer_phone": "9876500000", "invoice_date": "2026-10-14", "due_date": "2026-10-14",
        "invoice_discount": "0", "items": [{"product_id": product_id, "description": "Report Product", "hsn_sac": "", "quantity": "2", "unit": "pcs", "unit_price": "35", "discount_percent": "0", "tax_rate": "18"}],
    })
    billing.issue_bill(business_id, user_id, bill_id)
    billing.record_payment(business_id, user_id, bill_id, "20", "Cash", "RCPT-REPORT-1", "2026-10-14")

    reports = OperationalReportService(database)
    for kind in sorted(reports.REPORTS):
        report = reports.report(kind, business_id, "2026-10-01", "2026-10-31")
        assert report["report_type"] == kind
        assert len(report["headers"]) == len(reports.HEADERS[kind])
        assert report["summary"]
        assert all(len(row) == len(report["headers"]) for row in report["rows"]), kind

    valuation = reports.report("Inventory valuation", business_id, "2026-10-01", "2026-10-31")
    assert any(row[0] == "SKU-REPORT-1" for row in valuation["rows"])
    low_stock = reports.report("Low stock report", business_id, "2026-10-01", "2026-10-31")
    assert any(row[0] == "SKU-REPORT-1" and row[-1] == "LOW STOCK" for row in low_stock["rows"])
    top_sellers = reports.report("Top selling products", business_id, "2026-10-01", "2026-10-31")
    product_row = next(row for row in top_sellers["rows"] if row[0] == "SKU-REPORT-1")
    assert Decimal(product_row[2]) == Decimal("2")
    assert Decimal(product_row[3].replace(",", "")) == Decimal("70.00")
    customer_payments = reports.report("Customer payment register", business_id, "2026-10-01", "2026-10-31")
    assert any(row[2] and row[3] == "Report Customer" for row in customer_payments["rows"])
    supplier_payments = reports.report("Supplier payment register", business_id, "2026-10-01", "2026-10-31")
    assert any(row[3] == "Report Supplier" for row in supplier_payments["rows"])
    customer_balances = reports.report("Customer balances", business_id, "2026-10-01", "2026-10-31")
    assert any(row[0] == "Report Customer" for row in customer_balances["rows"])
    supplier_payables = reports.report("Supplier payables", business_id, "2026-10-01", "2026-10-31")
    supplier_row = next(row for row in supplier_payables["rows"] if row[0] == "Report Supplier")
    assert Decimal(supplier_row[6].replace(",", "")) > 0  # Payable column follows credits/returns.

    pdf_path = tmp_path / "top-selling-products.pdf"
    generate_accounting_report_pdf(
        database, business_id, pdf_path, top_sellers["report_type"], top_sellers["summary"],
        top_sellers["headers"], top_sellers["rows"],
    )
    assert pdf_path.read_bytes().startswith(b"%PDF-")
    assert pdf_path.stat().st_size > 1000


def test_operational_reports_reject_reverse_date_range_and_unknown_type(database):
    _, business_id = SetupService(database).complete_setup(valid_setup())
    reports = OperationalReportService(database)
    try:
        reports.report("Inventory valuation", business_id, "2026-10-31", "2026-10-01")
    except ValueError as exc:
        assert "start date" in str(exc)
    else:
        raise AssertionError("Reverse date range should be rejected")
    try:
        reports.report("Secret report", business_id, "2026-10-01", "2026-10-31")
    except ValueError as exc:
        assert "Unsupported" in str(exc)
    else:
        raise AssertionError("Unknown report type should be rejected")
