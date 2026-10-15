"""Integration tests for live Overview values and local desktop notification source data.

Purpose: Ensure dashboard figures and alert events come from saved business transactions.
Project: KoshFlow | Version: 0.6.2
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.6.2 — Added dashboard aggregation and notification lifecycle integration tests.
"""
from datetime import date
from decimal import Decimal

from koshflow.services.bill_service import BillService
from koshflow.services.dashboard_service import DashboardService
from koshflow.services.customer_service import CustomerService
from koshflow.services.inventory_service import InventoryService
from koshflow.services.notification_service import NotificationService
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


def test_dashboard_snapshot_uses_real_sales_inventory_and_contacts(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    inventory = InventoryService(database)
    product_id = inventory.create_product(business_id, user_id, {
        "sku": "DASH-001", "name": "Dashboard Product", "category": "Office", "unit": "pcs",
        "purchase_price": "20", "selling_price": "100", "tax_rate": "0", "reorder_level": "5", "opening_quantity": "8",
    })
    customer_id = CustomerService(database).create_customer(business_id, user_id, {
        "name": "Dashboard Customer", "phone": "9876500000", "customer_type": "individual",
    })
    billing = BillService(database)
    billing.ensure_starter_templates(business_id)
    bill_id = billing.create_bill(business_id, user_id, {
        "customer_id": customer_id, "customer_type": "B2C", "document_type": "tax_invoice", "customer_name": "Dashboard Customer",
        "customer_phone": "9876500000", "invoice_date": "2026-10-14", "due_date": "2026-10-14", "invoice_discount": "0",
        "items": [{"product_id": product_id, "description": "Dashboard Product", "quantity": "2", "unit": "pcs", "unit_price": "100", "discount_percent": "0", "tax_rate": "0"}],
    })
    billing.issue_bill(business_id, user_id, bill_id)
    billing.record_payment(business_id, user_id, bill_id, "50", "Cash", "DASH-REC-1", "2026-10-14")

    snapshot = DashboardService(database).snapshot(business_id, "Financial year", date(2026, 10, 15))
    assert snapshot["invoice_count"] == 1
    assert snapshot["net_sales"] == "200.00"
    assert snapshot["customer_receipts"] == "50.00"
    assert snapshot["receivables"] == "150.00"
    assert snapshot["product_count"] == 1
    assert snapshot["customer_count"] == 1
    assert snapshot["top_products"][0]["name"] == "Dashboard Product"
    assert snapshot["recent_invoices"][0]["number"].startswith("KF-")


def test_notification_service_deduplicates_overdue_invoice_and_stock_alerts(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    inventory = InventoryService(database)
    product_id = inventory.create_product(business_id, user_id, {
        "sku": "ALERT-001", "name": "Alert Product", "category": "Office", "unit": "pcs",
        "purchase_price": "20", "selling_price": "100", "tax_rate": "0", "reorder_level": "5", "opening_quantity": "1",
    })
    billing = BillService(database)
    billing.ensure_starter_templates(business_id)
    bill_id = billing.create_bill(business_id, user_id, {
        "customer_type": "B2C", "document_type": "tax_invoice", "customer_name": "Overdue Customer",
        "invoice_date": "2026-10-01", "due_date": "2026-10-10", "invoice_discount": "0",
        "items": [{"product_id": product_id, "description": "Alert Product", "quantity": "1", "unit": "pcs", "unit_price": "100", "discount_percent": "0", "tax_rate": "0"}],
    })
    billing.issue_bill(business_id, user_id, bill_id)
    notifications = NotificationService(database)
    first = notifications.scan_business(business_id, date(2026, 10, 15))
    assert any(row["category"] == "receivables" and row["severity"] == "critical" for row in first)
    assert any(row["category"] == "inventory" and row["severity"] == "critical" for row in first)
    assert notifications.unread_count(business_id) >= 2
    assert notifications.scan_business(business_id, date(2026, 10, 15)) == []

    inbox = notifications.list_notifications(business_id)
    notifications.mark_read(business_id, inbox[0]["notification_id"])
    assert notifications.unread_count(business_id) == len([r for r in inbox if not r["is_read"]]) - 1
    notifications.dismiss(business_id, inbox[-1]["notification_id"])
    assert all(r["notification_id"] != inbox[-1]["notification_id"] for r in notifications.list_notifications(business_id))


def test_dashboard_includes_fully_paid_invoices_in_selected_period(database):
    """Fully paid invoices remain part of period sales and receipt metrics."""
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    inventory = InventoryService(database)
    product_id = inventory.create_product(business_id, user_id, {
        "sku": "LEGACY-STATUS-001", "name": "Legacy Status Product", "category": "Office", "unit": "pcs",
        "purchase_price": "20", "selling_price": "100", "tax_rate": "0", "reorder_level": "0", "opening_quantity": "10",
    })
    customer_id = CustomerService(database).create_customer(business_id, user_id, {
        "name": "Legacy Customer", "phone": "9876500001", "customer_type": "individual",
    })
    billing = BillService(database)
    billing.ensure_starter_templates(business_id)
    bill_id = billing.create_bill(business_id, user_id, {
        "customer_id": customer_id, "customer_type": "B2C", "document_type": "tax_invoice", "customer_name": "Legacy Customer",
        "invoice_date": "2026-10-14", "due_date": "2026-10-20", "invoice_discount": "0",
        "items": [{"product_id": product_id, "description": "Legacy Status Product", "quantity": "2", "unit": "pcs", "unit_price": "100", "discount_percent": "0", "tax_rate": "0"}],
    })
    billing.issue_bill(business_id, user_id, bill_id)
    billing.record_payment(business_id, user_id, bill_id, "200", "Cash", "LEGACY-REC-1", "2026-10-14")
    # Some imported records can retain the source system's ISO timestamp rather than YYYY-MM-DD.
    with database.transaction() as conn:
        conn.execute("UPDATE bills SET invoice_date='2026-10-14T10:15:00' WHERE business_id=? AND bill_id=?", (business_id, bill_id))
    snapshot = DashboardService(database).snapshot(business_id, "This quarter", date(2026, 10, 15))
    assert snapshot["invoice_count"] == 1
    assert snapshot["net_sales"] == "200.00"
    assert snapshot["customer_receipts"] == "200.00"
    assert snapshot["recent_invoices"][0]["number"].startswith("KF-")
    assert sum((Decimal(row["value"]) for row in snapshot["revenue_series"]), Decimal("0")) == Decimal("200.00")


def test_test_notification_creates_persistent_unread_inbox_entry(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    service = NotificationService(database)
    result = service.create_test_notification(business_id)
    assert result["title"] == "KoshFlow notification test"
    assert service.unread_count(business_id) == 1
    saved = service.list_notifications(business_id)
    assert len(saved) == 1
    assert saved[0]["notification_id"] == result["notification_id"]
    assert saved[0]["is_read"] == 0
