"""Regression coverage for KoshFlow v0.5.0 workflows.

Purpose: Validate SKU/HSN assistance, automatic purchase bills, customer identity,
         rich stock-movement snapshots and stock-linked quick-sale behavior.
Project: KoshFlow | Version: 0.5.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.5.0 — Added end-to-end checks for inventory/purchasing/contact workflows.
"""

from koshflow.services.bill_service import BillService
from koshflow.services.customer_service import CustomerService
from koshflow.services.inventory_service import InventoryService
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


def _purchase_line(product_id, quantity, unit_cost="100", tax_rate="0", discount_percent="0"):
    return {
        "product_id": product_id,
        "quantity": str(quantity),
        "unit_cost": str(unit_cost),
        "tax_rate": str(tax_rate),
        "discount_percent": str(discount_percent),
    }


def _sales_values(product_id, quantity, customer_id=None):
    values = {
        "customer_type": "B2C",
        "document_type": "tax_invoice",
        "customer_name": "Quick Counter Customer",
        "customer_phone": "9876543210",
        "invoice_date": "2026-10-14",
        "due_date": "2026-10-14",
        "invoice_discount": "0",
        "items": [{
            "product_id": product_id,
            "description": "Quick Sale Product",
            "hsn_sac": "",
            "quantity": str(quantity),
            "unit": "pcs",
            "unit_price": "150",
            "discount_percent": "0",
            "tax_rate": "0",
        }],
    }
    if customer_id:
        values["customer_id"] = customer_id
    return values


def test_missing_sku_is_generated_atomically_and_hsn_suggestion_is_conservative(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    inventory = InventoryService(database)
    first = inventory.create_product(business_id, user_id, {
        "name": "USB Printer", "sku": "", "category": "Electronics", "unit": "pcs",
        "purchase_price": "100", "selling_price": "150", "opening_quantity": "0",
    })
    second = inventory.create_product(business_id, user_id, {
        "name": "Office Notebook", "sku": "", "category": "Stationery", "unit": "pcs",
        "purchase_price": "20", "selling_price": "30", "opening_quantity": "0",
    })
    assert inventory.get_product(business_id, first)["sku"] == "SKU-000001"
    assert inventory.get_product(business_id, second)["sku"] == "SKU-000002"
    suggestion = inventory.suggest_hsn_code("USB Printer", "Electronics")
    assert suggestion is not None
    assert suggestion["code"] == "8443"
    assert suggestion["verified"] == "false"
    notebook = inventory.suggest_hsn_code("Office Notebook", "Stationery")
    assert notebook is not None and notebook["code"] == "4820"
    assert inventory.suggest_hsn_code("Mystery widget", "Other") is None


def test_fully_received_purchase_order_auto_generates_one_draft_bill_without_double_stock(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    inventory = InventoryService(database)
    supplier_id = inventory.create_supplier(business_id, user_id, {
        "supplier_code": "SUP-001", "name": "Auto Bill Supplier", "payment_terms_days": 14,
    })
    product_id = inventory.create_product(business_id, user_id, {
        "sku": "STOCK-001", "name": "Receipt Product", "category": "General", "unit": "pcs",
        "purchase_price": "20", "selling_price": "40", "opening_quantity": "2",
    })
    order_id = inventory.create_purchase_order(business_id, user_id, {
        "supplier_id": supplier_id,
        "document_date": "2026-10-14",
        "due_date": "2026-10-28",
        "items": [_purchase_line(product_id, 3, unit_cost="25", tax_rate="0")],
    })
    order = inventory.get_purchase_order(business_id, order_id)
    inventory.order_purchase_order(business_id, user_id, order_id)
    generated = inventory.receive_purchase_order(business_id, user_id, order_id, [{
        "purchase_order_item_id": order["items"][0]["purchase_order_item_id"], "quantity": "3",
    }])
    assert generated
    bill = inventory.get_purchase_bill(business_id, generated)
    assert bill["status"] == "draft"
    assert bill["source_purchase_order_id"] == order_id
    assert "Auto-generated" in bill["notes"]
    assert len(bill["items"]) == 1
    assert bill["items"][0]["quantity"] == "3.000"
    assert inventory.get_product(business_id, product_id)["quantity_on_hand"] == "5.000"

    # Repeating the receipt is invalid and cannot create another bill or movement.
    before = len(inventory.list_stock_movements(business_id, "STOCK-001"))
    import pytest
    from koshflow.services.inventory_service import InventoryError
    with pytest.raises(InventoryError, match="Only ordered or partially received"):
        inventory.receive_purchase_order(business_id, user_id, order_id, [{
            "purchase_order_item_id": order["items"][0]["purchase_order_item_id"], "quantity": "1",
        }])
    assert len(inventory.list_stock_movements(business_id, "STOCK-001")) == before


def test_customers_generate_codes_update_and_quick_sale_reuses_phone_identity(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    customers = CustomerService(database)
    customer_id = customers.create_customer(business_id, user_id, {
        "name": "Riya Sharma", "phone": "+91 98765 43210", "email": "riya@example.com",
        "customer_type": "individual", "city": "Bilaspur",
    })
    customer = customers.get_customer(business_id, customer_id)
    assert customer["customer_code"] == "CUS-000001"
    assert customer["invoice_count"] == 0

    resolved_id = customers.resolve_or_create_for_sale(business_id, user_id, {
        "name": "Riya S.", "phone": "9876543210", "customer_type": "individual",
    })
    assert resolved_id == customer_id
    assert len(customers.list_customers(business_id)) == 1
    customers.update_customer(business_id, user_id, customer_id, {
        **customer, "name": "Riya Sharma Updated", "customer_code": customer["customer_code"],
    })
    assert customers.get_customer(business_id, customer_id)["name"] == "Riya Sharma Updated"


def test_quick_sale_bill_link_deducts_exact_quantity_and_movement_contains_audit_context(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    inventory = InventoryService(database)
    product_id = inventory.create_product(business_id, user_id, {
        "sku": "QUICK-001", "name": "Quick Sale Product", "category": "General", "unit": "pcs",
        "purchase_price": "50", "selling_price": "150", "tax_rate": "0", "opening_quantity": "8",
    })
    customer_id = CustomerService(database).create_customer(business_id, user_id, {
        "name": "Walk-in Customer", "phone": "9876543210", "customer_type": "individual",
    })
    billing = BillService(database)
    bill_id = billing.create_bill(business_id, user_id, _sales_values(product_id, 2, customer_id))
    billing.issue_bill(business_id, user_id, bill_id)

    assert inventory.get_product(business_id, product_id)["quantity_on_hand"] == "6.000"
    bill = billing.get_bill(business_id, bill_id)
    assert bill["customer_id"] == customer_id
    sale_movement = next(row for row in inventory.list_stock_movements(business_id, "QUICK-001") if row["movement_type"] == "sale")
    assert sale_movement["quantity_before"] == "8.000"
    assert sale_movement["quantity_after"] == "6.000"
    assert sale_movement["movement_value"] == "100.00"
    assert sale_movement["source_reference"] == bill["bill_number"]
    assert sale_movement["actor_name"]
