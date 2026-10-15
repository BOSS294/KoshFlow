"""Inventory and purchasing workflow regression tests.

Purpose: Check stock math, purchase lifecycle, supplier balances, access control and audit safety.
Project: KoshFlow | Version: 0.5.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.5.0 — Added SKU assistance, auto purchase bills, contacts, Quick Billing and movement snapshot coverage.
"""

from decimal import Decimal

import pytest

from koshflow.core.security import new_id
from koshflow.services.bill_service import BillError, BillService
from koshflow.services.inventory_service import InventoryError, InventoryService
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


@pytest.fixture
def stock_workspace(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    service = InventoryService(database)
    supplier_id = service.create_supplier(business_id, user_id, {
        "supplier_code": "SUP-001", "name": "Test Supplier", "phone": "9876543210",
        "payment_terms_days": 14,
    })
    product_id = service.create_product(business_id, user_id, {
        "sku": "SKU-001", "name": "Test Product", "category": "General", "unit": "pcs",
        "purchase_price": "100", "selling_price": "150", "tax_rate": "18",
        "reorder_level": "2", "opening_quantity": "10",
    })
    return database, user_id, business_id, service, supplier_id, product_id


def line(product_id, quantity, unit_cost="100", tax_rate="18", discount_percent="0"):
    return {"product_id": product_id, "quantity": str(quantity), "unit_cost": str(unit_cost),
            "tax_rate": str(tax_rate), "discount_percent": str(discount_percent)}


def purchase_values(supplier_id, items, **overrides):
    data = {"supplier_id": supplier_id, "document_date": "2026-10-14", "due_date": "2026-10-28",
            "supplier_invoice_number": "INV-TEST-01", "items": items, "notes": "Test purchase"}
    data.update(overrides)
    return data


def test_product_opening_stock_is_audited_and_appears_in_movement_ledger(stock_workspace):
    _, _, business_id, service, _, product_id = stock_workspace
    product = service.get_product(business_id, product_id)
    assert product["quantity_on_hand"] == "10.000"
    assert product["average_cost"] == "100.00"
    movements = service.list_stock_movements(business_id, "SKU-001")
    assert len(movements) == 1
    assert movements[0]["movement_type"] == "opening"
    assert movements[0]["quantity_delta"] == "10.000"


def test_purchase_bill_posting_updates_stock_once_and_averages_cost(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    purchase_id = service.create_purchase_bill(business_id, user_id, purchase_values(supplier_id, [line(product_id, 5, "120")]))
    draft = service.get_purchase_bill(business_id, purchase_id)
    assert draft["grand_total"] == "708.00"
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "10.000"
    service.post_purchase_bill(business_id, user_id, purchase_id)
    saved = service.get_product(business_id, product_id)
    assert saved["quantity_on_hand"] == "15.000"
    assert saved["average_cost"] == "106.67"
    with pytest.raises(InventoryError, match="Only draft purchase bills can be posted"):
        service.post_purchase_bill(business_id, user_id, purchase_id)
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "15.000"


def test_purchase_order_partial_receipts_and_linked_invoice_prevent_double_stock(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    order_id = service.create_purchase_order(business_id, user_id, {
        "supplier_id": supplier_id, "document_date": "2026-10-14", "due_date": "2026-10-22",
        "items": [line(product_id, 4, "110", "0")],
    })
    order = service.get_purchase_order(business_id, order_id)
    service.order_purchase_order(business_id, user_id, order_id)
    item_id = order["items"][0]["purchase_order_item_id"]
    partial_bill_id = service.receive_purchase_order(
        business_id, user_id, order_id,
        [{"purchase_order_item_id": item_id, "quantity": "1.5"}],
    )
    partial = service.get_purchase_order(business_id, order_id)
    assert partial["status"] == "partially_received"
    assert partial_bill_id
    partial_bill = service.get_purchase_bill(business_id, partial_bill_id)
    assert partial_bill["status"] == "draft"
    assert partial_bill["items"][0]["quantity"] == "1.500"
    assert partial_bill["grand_total"] == "165.00"
    with pytest.raises(InventoryError, match="not fully received"):
        service.post_purchase_bill(business_id, user_id, partial_bill_id)
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "11.500"
    with pytest.raises(InventoryError, match="exceeds the remaining quantity"):
        service.receive_purchase_order(business_id, user_id, order_id, [{"purchase_order_item_id": item_id, "quantity": "3"}])
    updated_bill_id = service.receive_purchase_order(
        business_id, user_id, order_id,
        [{"purchase_order_item_id": item_id, "quantity": "2.5"}],
    )
    assert service.get_purchase_order(business_id, order_id)["status"] == "received"
    assert updated_bill_id == partial_bill_id
    full_bill = service.get_purchase_bill(business_id, partial_bill_id)
    assert full_bill["items"][0]["quantity"] == "4.000"
    assert full_bill["grand_total"] == "440.00"
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "14.000"

    bill_id = service.create_purchase_bill(business_id, user_id, purchase_values(
        supplier_id, [line(product_id, 4, "110", "0")], source_purchase_order_id=order_id,
    ))
    assert bill_id == partial_bill_id
    service.post_purchase_bill(business_id, user_id, bill_id)
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "14.000"


def test_purchase_payment_and_supplier_return_update_payable_and_stock(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    bill_id = service.create_purchase_bill(business_id, user_id, purchase_values(supplier_id, [line(product_id, 5, "100", "18")]))
    service.post_purchase_bill(business_id, user_id, bill_id)
    bill = service.get_purchase_bill(business_id, bill_id)
    assert bill["grand_total"] == "590.00"
    service.record_supplier_payment(business_id, user_id, bill_id, "200", "UPI", "UTR-0001", "2026-10-14")
    assert service.get_purchase_bill(business_id, bill_id)["balance_due"] == "390.00"
    item_id = service.get_purchase_bill(business_id, bill_id)["items"][0]["purchase_item_id"]
    return_id = service.create_supplier_return(business_id, user_id, bill_id, item_id, "1", "Damaged item", "2026-10-14")
    service.post_supplier_return(business_id, user_id, return_id)
    updated = service.get_purchase_bill(business_id, bill_id)
    assert updated["balance_due"] == "272.00"
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "14.000"
    supplier = service.get_supplier(business_id, supplier_id)
    assert supplier["outstanding_balance"] == "272.00"


def test_return_reservation_prevents_over_return_and_stock_cannot_go_negative(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    bill_id = service.create_purchase_bill(business_id, user_id, purchase_values(supplier_id, [line(product_id, 2, "100", "0")]))
    service.post_purchase_bill(business_id, user_id, bill_id)
    item_id = service.get_purchase_bill(business_id, bill_id)["items"][0]["purchase_item_id"]
    service.create_supplier_return(business_id, user_id, bill_id, item_id, "1.5", "Damaged", "2026-10-14")
    with pytest.raises(InventoryError, match="unreturned purchased quantity"):
        service.create_supplier_return(business_id, user_id, bill_id, item_id, "1", "Damaged", "2026-10-14")
    with pytest.raises(InventoryError, match="cannot be archived"):
        service.archive_product(business_id, user_id, product_id)


def test_stock_adjustment_requires_reason_and_never_allows_negative_stock(stock_workspace):
    _, user_id, business_id, service, _, product_id = stock_workspace
    with pytest.raises(InventoryError, match="requires a reason"):
        service.adjust_stock(business_id, user_id, product_id, "remove", "1", "")
    with pytest.raises(InventoryError, match="Stock would become negative"):
        service.adjust_stock(business_id, user_id, product_id, "remove", "100", "Bad count")
    service.adjust_stock(business_id, user_id, product_id, "set", "7.5", "Physical stock count")
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "7.500"
    assert service.list_stock_movements(business_id, "Physical stock count")[0]["quantity_delta"] == "-2.500"


def test_business_scoping_duplicate_codes_and_roles_are_enforced(stock_workspace):
    database, user_id, business_id, service, supplier_id, product_id = stock_workspace
    with pytest.raises(InventoryError, match="SKU or barcode already exists"):
        service.create_product(business_id, user_id, {"sku":"SKU-001","name":"Duplicate","purchase_price":"0","selling_price":"0"})
    assert service.get_product("OTHER-BUSINESS", product_id) is None
    assert service.list_suppliers("OTHER-BUSINESS") == []
    with database.transaction() as conn:
        conn.execute("UPDATE user_businesses SET role='cashier' WHERE user_id=? AND business_id=?", (user_id,business_id))
    with pytest.raises(InventoryError, match="does not allow"):
        service.adjust_stock(business_id,user_id,product_id,"add","1","No permission")


def test_database_schema_has_inventory_purchasing_tables(database):
    with database.connection() as conn:
        tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required={"products","suppliers","purchase_orders","purchase_order_items","purchase_bills","purchase_items","supplier_payments","supplier_returns","supplier_return_items","stock_movements"}
    assert required <= tables



def sales_bill_values(product_id, quantity):
    return {
        "customer_type": "B2C",
        "document_type": "tax_invoice",
        "customer_name": "Counter Customer",
        "invoice_date": "2026-10-14",
        "due_date": "2026-10-20",
        "invoice_discount": "0",
        "items": [{
            "product_id": product_id,
            "description": "Test Product",
            "hsn_sac": "",
            "quantity": str(quantity),
            "unit": "pcs",
            "unit_price": "150",
            "discount_percent": "0",
            "tax_rate": "18",
        }],
    }


def test_issued_catalog_bill_deducts_stock_and_cancellation_restores_it(stock_workspace):
    database, user_id, business_id, inventory, _, product_id = stock_workspace
    billing = BillService(database)
    bill_id = billing.create_bill(business_id, user_id, sales_bill_values(product_id, 2))

    billing.issue_bill(business_id, user_id, bill_id)
    assert inventory.get_product(business_id, product_id)["quantity_on_hand"] == "8.000"
    movements = inventory.list_stock_movements(business_id, "SKU-001")
    sale_moves = [movement for movement in movements if movement["movement_type"] == "sale"]
    assert len(sale_moves) == 1
    assert sale_moves[0]["quantity_delta"] == "-2.000"

    billing.cancel_bill(business_id, user_id, bill_id, "Customer withdrew the unpaid order")
    assert inventory.get_product(business_id, product_id)["quantity_on_hand"] == "10.000"
    movements = inventory.list_stock_movements(business_id, "SKU-001")
    return_moves = [movement for movement in movements if movement["movement_type"] == "sale_return"]
    assert len(return_moves) == 1
    assert return_moves[0]["quantity_delta"] == "2.000"


def test_catalog_bill_issue_is_atomic_when_stock_is_insufficient(stock_workspace):
    database, user_id, business_id, inventory, _, product_id = stock_workspace
    billing = BillService(database)
    # The second line would fail after the first line has been processed if the
    # service did not roll the full issue operation back transactionally.
    values = sales_bill_values(product_id, 6)
    values["items"].append({
        "product_id": product_id,
        "description": "Test Product second line",
        "hsn_sac": "",
        "quantity": "6",
        "unit": "pcs",
        "unit_price": "150",
        "discount_percent": "0",
        "tax_rate": "18",
    })
    bill_id = billing.create_bill(business_id, user_id, values)

    with pytest.raises(BillError, match="Insufficient stock"):
        billing.issue_bill(business_id, user_id, bill_id)

    assert inventory.get_product(business_id, product_id)["quantity_on_hand"] == "10.000"
    assert billing.get_bill(business_id, bill_id)["status"] == "draft"
    assert not any(movement["movement_type"] == "sale" for movement in inventory.list_stock_movements(business_id, "SKU-001"))


def test_linked_purchase_bill_rejects_price_variance_after_stock_was_received(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    order_id = service.create_purchase_order(business_id, user_id, {
        "supplier_id": supplier_id, "document_date": "2026-10-14", "due_date": "2026-10-22",
        "items": [line(product_id, 2, "110", "18", "5")],
    })
    order = service.get_purchase_order(business_id, order_id)
    service.order_purchase_order(business_id, user_id, order_id)
    service.receive_purchase_order(business_id, user_id, order_id, [{
        "purchase_order_item_id": order["items"][0]["purchase_order_item_id"], "quantity": "2",
    }])
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "12.000"

    with pytest.raises(InventoryError, match="unit cost must match"):
        service.create_purchase_bill(business_id, user_id, purchase_values(
            supplier_id, [line(product_id, 2, "112", "18", "5")], source_purchase_order_id=order_id,
        ))
    with pytest.raises(InventoryError, match="discount must match"):
        service.create_purchase_bill(business_id, user_id, purchase_values(
            supplier_id, [line(product_id, 2, "110", "18", "0")], source_purchase_order_id=order_id,
        ))
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "12.000"


def test_supplier_return_respects_original_discount_and_tax(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    bill_id = service.create_purchase_bill(business_id, user_id, purchase_values(
        supplier_id, [line(product_id, 2, "100", "18", "10")],
    ))
    service.post_purchase_bill(business_id, user_id, bill_id)
    bill = service.get_purchase_bill(business_id, bill_id)
    assert bill["grand_total"] == "212.40"
    item_id = bill["items"][0]["purchase_item_id"]
    return_id = service.create_supplier_return(business_id, user_id, bill_id, item_id, "1", "Damaged discounted item", "2026-10-14")
    service.post_supplier_return(business_id, user_id, return_id)
    updated = service.get_purchase_bill(business_id, bill_id)
    assert updated["balance_due"] == "106.20"
    assert updated["returns"][0]["grand_total"] == "106.20"
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "11.000"


def test_supplier_cannot_be_archived_with_open_purchase_documents(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    service.create_purchase_order(business_id, user_id, {
        "supplier_id": supplier_id, "document_date": "2026-10-14", "due_date": "2026-10-22",
        "items": [line(product_id, 1)],
    })
    with pytest.raises(InventoryError, match="open purchase order"):
        service.archive_supplier(business_id, user_id, supplier_id)


def test_duplicate_supplier_invoice_reference_is_rejected(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    first = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_id, [line(product_id, 1)], supplier_invoice_number="SUP-INV-778"),
    )
    assert service.get_purchase_bill(business_id, first)["status"] == "draft"
    with pytest.raises(InventoryError, match="already recorded"):
        service.create_purchase_bill(
            business_id, user_id,
            purchase_values(supplier_id, [line(product_id, 2)], supplier_invoice_number="sup-inv-778"),
        )


def test_received_purchase_order_can_link_to_only_one_supplier_bill(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    order_id = service.create_purchase_order(business_id, user_id, {
        "supplier_id": supplier_id,
        "document_date": "2026-10-14",
        "due_date": "2026-10-22",
        "items": [line(product_id, 2, "110", "18", "5")],
    })
    order = service.get_purchase_order(business_id, order_id)
    service.order_purchase_order(business_id, user_id, order_id)
    service.receive_purchase_order(business_id, user_id, order_id, [{
        "purchase_order_item_id": order["items"][0]["purchase_order_item_id"], "quantity": "2",
    }])
    first = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_id, [line(product_id, 2, "110", "18", "5")],
                        source_purchase_order_id=order_id, supplier_invoice_number="INV-LINK-A"),
    )
    # Updating the existing linked draft must exclude itself from the duplicate check.
    service.update_purchase_bill(
        business_id, user_id, first,
        purchase_values(supplier_id, [line(product_id, 2, "110", "18", "5")],
                        source_purchase_order_id=order_id, supplier_invoice_number="INV-LINK-A"),
    )
    with pytest.raises(InventoryError, match="already linked to supplier bill"):
        service.create_purchase_bill(
            business_id, user_id,
            purchase_values(supplier_id, [line(product_id, 2, "110", "18", "5")],
                            source_purchase_order_id=order_id, supplier_invoice_number="INV-LINK-B"),
        )
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "12.000"


def test_purchase_document_rejects_duplicate_product_lines(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    with pytest.raises(InventoryError, match="already on the document"):
        service.create_purchase_bill(
            business_id, user_id,
            purchase_values(supplier_id, [line(product_id, 1), line(product_id, 2)],
                            supplier_invoice_number="INV-DUP-LINE"),
        )
    assert service.get_product(business_id, product_id)["quantity_on_hand"] == "10.000"


def test_catalog_bill_rejects_mismatched_unit(stock_workspace):
    database, user_id, business_id, inventory, _, product_id = stock_workspace
    billing = BillService(database)
    values = sales_bill_values(product_id, 1)
    values["items"][0]["unit"] = "kg"
    with pytest.raises(BillError, match="Unit conversion is not supported"):
        billing.create_bill(business_id, user_id, values)
    assert inventory.get_product(business_id, product_id)["quantity_on_hand"] == "10.000"


def test_schema_upgrade_adds_supplier_return_discount_without_losing_records(database):
    # Simulate an older schema and ensure all v0.5.0 additive migrations are applied.
    with database.connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(supplier_return_items)").fetchall()}
        assert "discount_percent" in columns
        conn.execute("ALTER TABLE supplier_return_items DROP COLUMN discount_percent")
        conn.execute("UPDATE app_meta SET meta_value='3' WHERE meta_key='schema_version'")
        conn.execute("DELETE FROM schema_migrations WHERE version=4")
        conn.commit()

    database.initialize()
    with database.connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(supplier_return_items)").fetchall()}
        version = conn.execute("SELECT meta_value FROM app_meta WHERE meta_key='schema_version'").fetchone()[0]
    assert "discount_percent" in columns
    assert version == "7"
    assert database.integrity_check() == "ok"


def test_supplier_credit_prevents_archiving_supplier(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    bill_id = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_id, [line(product_id, 1, "100", "0")], supplier_invoice_number="INV-CREDIT-1"),
    )
    service.post_purchase_bill(business_id, user_id, bill_id)
    bill = service.get_purchase_bill(business_id, bill_id)
    service.record_supplier_payment(business_id, user_id, bill_id, bill["grand_total"], "Bank transfer", "BANK-1", "2026-10-14")
    purchase_item = service.get_purchase_bill(business_id, bill_id)["items"][0]
    return_id = service.create_supplier_return(
        business_id, user_id, bill_id, purchase_item["purchase_item_id"], "1", "Supplier agreed full credit", "2026-10-14"
    )
    service.post_supplier_return(business_id, user_id, return_id)
    supplier = service.get_supplier(business_id, supplier_id)
    assert supplier["outstanding_balance"] == "-100.00"
    with pytest.raises(InventoryError, match="unused supplier credit"):
        service.archive_supplier(business_id, user_id, supplier_id)


def test_supplier_payables_and_credits_are_not_netted_across_suppliers(stock_workspace):
    _, user_id, business_id, service, supplier_a, product_id = stock_workspace
    supplier_b = service.create_supplier(business_id, user_id, {
        "supplier_code": "SUP-002", "name": "Credit Supplier", "payment_terms_days": 0,
    })
    bill_a = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_a, [line(product_id, 1, "100", "0")], supplier_invoice_number="BAL-A"),
    )
    service.post_purchase_bill(business_id, user_id, bill_a)

    bill_b = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_b, [line(product_id, 1, "100", "0")], supplier_invoice_number="BAL-B"),
    )
    service.post_purchase_bill(business_id, user_id, bill_b)
    total_b = service.get_purchase_bill(business_id, bill_b)["grand_total"]
    service.record_supplier_payment(business_id, user_id, bill_b, total_b, "Bank transfer", "BAL-PAY-B", "2026-10-14")
    item_b = service.get_purchase_bill(business_id, bill_b)["items"][0]
    ret_b = service.create_supplier_return(
        business_id, user_id, bill_b, item_b["purchase_item_id"], "1", "Credit note", "2026-10-14",
    )
    service.post_supplier_return(business_id, user_id, ret_b)

    summary = service.purchasing_summary(business_id)
    assert summary["supplier_payables"] == "100.00"
    assert summary["supplier_credits"] == "100.00"


def test_discounted_purchase_cost_drives_average_and_last_purchase_price(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    bill_id = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_id, [line(product_id, 5, "120", "18", "10")], supplier_invoice_number="DISC-COST-1"),
    )
    service.post_purchase_bill(business_id, user_id, bill_id)
    product = service.get_product(business_id, product_id)
    # 10 units @ 100 plus 5 units @ 108 after the 10% line discount, before recoverable GST.
    assert product["quantity_on_hand"] == "15.000"
    assert product["average_cost"] == "102.67"
    assert product["last_purchase_price"] == "108.00"


def test_catalog_unit_cannot_change_after_stock_history(stock_workspace):
    _, user_id, business_id, service, _, product_id = stock_workspace
    product = service.get_product(business_id, product_id)
    with pytest.raises(InventoryError, match="unit or SKU cannot be changed|unit cannot be changed"):
        service.update_product(business_id, user_id, product_id, {
            "sku": product["sku"], "name": product["name"], "unit": "kg",
            "purchase_price": product["last_purchase_price"], "selling_price": product["selling_price"],
            "tax_rate": product["tax_rate"], "reorder_level": product["reorder_level"],
        })
    assert service.get_product(business_id, product_id)["unit"] == "pcs"


def test_stock_linked_sales_reject_more_than_three_quantity_decimals(stock_workspace):
    database, user_id, business_id, inventory, _, product_id = stock_workspace
    billing = BillService(database)
    values = sales_bill_values(product_id, "0.0004")
    with pytest.raises(BillError, match="at most three decimal places"):
        billing.create_bill(business_id, user_id, values)
    assert inventory.get_product(business_id, product_id)["quantity_on_hand"] == "10.000"


def test_inventory_and_purchasing_theme_tokens_include_light_and_dark():
    # Parse the theme dictionary without importing Qt, which is optional in CI.
    import ast
    from pathlib import Path

    source = Path(__file__).parents[1] / "koshflow" / "ui" / "styles.py"
    module = ast.parse(source.read_text(encoding="utf-8").replace('"accent": ACCENT', '"accent": "#C9E86A"'))
    assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "THEMES" for target in node.targets)
    )
    themes = ast.literal_eval(assignment.value)
    assert {"light", "dark"} <= set(themes)
    for theme in ("light", "dark"):
        tokens = themes[theme]
        assert tokens["window"]
        assert tokens["surface"]
        assert tokens["text"]
        assert tokens["border"]
        assert tokens["accent"] == "#C9E86A"


def test_cancelling_sale_after_a_later_purchase_restores_original_cost_basis(stock_workspace):
    database, user_id, business_id, inventory, supplier_id, product_id = stock_workspace
    billing = BillService(database)
    sale_id = billing.create_bill(business_id, user_id, sales_bill_values(product_id, 2))
    billing.issue_bill(business_id, user_id, sale_id)

    purchase_id = inventory.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_id, [line(product_id, 10, "200", "0")], supplier_invoice_number="COST-REVERSAL-1"),
    )
    inventory.post_purchase_bill(business_id, user_id, purchase_id)
    assert inventory.get_product(business_id, product_id)["average_cost"] == "155.56"

    billing.cancel_bill(business_id, user_id, sale_id, "Unpaid order cancelled after restock")
    product = inventory.get_product(business_id, product_id)
    assert product["quantity_on_hand"] == "20.000"
    assert product["average_cost"] == "150.00"
    movements = inventory.list_stock_movements(business_id, "SKU-001")
    cancellation = next(m for m in movements if m["movement_type"] == "sale_return")
    assert cancellation["unit_cost"] == "100.00"


def test_purchase_order_receipt_uses_discounted_cost_basis(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    order_id = service.create_purchase_order(business_id, user_id, {
        "supplier_id": supplier_id, "document_date": "2026-10-14", "due_date": "2026-10-22",
        "items": [line(product_id, 5, "120", "18", "10")],
    })
    order = service.get_purchase_order(business_id, order_id)
    service.order_purchase_order(business_id, user_id, order_id)
    service.receive_purchase_order(business_id, user_id, order_id, [{
        "purchase_order_item_id": order["items"][0]["purchase_order_item_id"], "quantity": "5",
    }])
    product = service.get_product(business_id, product_id)
    assert product["quantity_on_hand"] == "15.000"
    assert product["average_cost"] == "102.67"
    assert product["last_purchase_price"] == "108.00"


def test_supplier_payment_cannot_exceed_balance_or_pay_draft(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    draft = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_id, [line(product_id, 1, "100", "0")], supplier_invoice_number="PAY-GUARD-1"),
    )
    with pytest.raises(InventoryError, match="only be recorded against posted purchase bills"):
        service.record_supplier_payment(business_id, user_id, draft, "1", "UPI", "DRAFT-PAY", "2026-10-14")
    service.post_purchase_bill(business_id, user_id, draft)
    with pytest.raises(InventoryError, match="exceeds the outstanding supplier balance"):
        service.record_supplier_payment(business_id, user_id, draft, "100.01", "UPI", "OVERPAY-1", "2026-10-14")
    assert service.get_purchase_bill(business_id, draft)["amount_paid"] == "0.00"


def test_supplier_return_must_reference_item_from_same_purchase_bill(stock_workspace):
    _, user_id, business_id, service, supplier_id, product_id = stock_workspace
    first = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_id, [line(product_id, 1, "100", "0")], supplier_invoice_number="RETURN-SCOPE-A"),
    )
    service.post_purchase_bill(business_id, user_id, first)
    first_item = service.get_purchase_bill(business_id, first)["items"][0]["purchase_item_id"]
    second = service.create_purchase_bill(
        business_id, user_id,
        purchase_values(supplier_id, [line(product_id, 1, "100", "0")], supplier_invoice_number="RETURN-SCOPE-B"),
    )
    service.post_purchase_bill(business_id, user_id, second)
    with pytest.raises(InventoryError, match="does not belong to this bill"):
        service.create_supplier_return(business_id, user_id, second, first_item, "1", "Wrong document", "2026-10-14")
