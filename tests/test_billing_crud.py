"""Automated tests for KoshFlow Phase 2 billing and PDF workflows.

Purpose: Verify the bill lifecycle, decimal totals, roles, templates and PDF output.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.3.0 — Added tests for CRUD, audit, payments, B2B validation and PDF rendering.
"""

from pathlib import Path

import pytest

from koshflow.core.security import new_id
from koshflow.services.bill_service import BillError, BillService
from koshflow.services.pdf_service import generate_invoice_pdf
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


@pytest.fixture
def workspace(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    service = BillService(database)
    service.ensure_starter_templates(business_id)
    return database, user_id, business_id, service


def bill_values(template_id=None, **overrides):
    values = {
        "customer_type": "B2C",
        "document_type": "tax_invoice",
        "customer_name": "Walk-in Customer",
        "customer_phone": "+919876543210",
        "invoice_date": "2026-10-14",
        "due_date": "2026-10-29",
        "items": [
            {"description": "Professional service", "hsn_sac": "9983", "quantity": "2",
             "unit": "hour", "unit_price": "500", "discount_percent": "0", "tax_rate": "18"},
        ],
        "invoice_discount": "25.00",
        "template_id": template_id,
    }
    values.update(overrides)
    return values


def test_starter_theme_library_has_twenty_themes(workspace):
    _, _, business_id, service = workspace
    templates = service.list_templates(business_id)
    assert len(templates) == 20
    assert sum(int(item["is_default"]) for item in templates) == 1
    assert templates[0]["template_name"] == "KoshFlow Classic"


def test_create_and_update_draft_uses_deterministic_decimal_totals(workspace):
    _, user_id, business_id, service = workspace
    template_id = service.list_templates(business_id)[0]["template_id"]
    bill_id = service.create_bill(business_id, user_id, bill_values(template_id))
    bill = service.get_bill(business_id, bill_id)
    assert bill["bill_number"] == "KF-2026-00001"
    assert bill["subtotal"] == "1000.00"
    assert bill["invoice_discount"] == "25.00"
    assert bill["discount_total"] == "25.00"
    assert bill["taxable_total"] == "975.00"
    assert bill["tax_total"] == "175.50"
    assert bill["grand_total"] == "1150.50"
    assert bill["status"] == "draft"
    assert bill["items"][0]["line_total"] == "1150.50"

    service.update_draft(business_id, user_id, bill_id, bill_values(template_id, customer_name="Updated Customer"))
    updated = service.get_bill(business_id, bill_id)
    assert updated["customer_name"] == "Updated Customer"
    assert updated["invoice_discount"] == "25.00"
    assert updated["grand_total"] == "1150.50"


def test_issued_bill_cannot_be_edited_or_deleted(workspace):
    _, user_id, business_id, service = workspace
    bill_id = service.create_bill(business_id, user_id, bill_values())
    service.issue_bill(business_id, user_id, bill_id)
    with pytest.raises(BillError, match="Only draft bills can be edited"):
        service.update_draft(business_id, user_id, bill_id, bill_values(customer_name="Altered"))
    with pytest.raises(BillError, match="Only draft bills can be deleted"):
        service.delete_draft(business_id, user_id, bill_id)


def test_issue_requires_positive_item_total(workspace):
    _, user_id, business_id, service = workspace
    bill_id = service.create_bill(business_id, user_id, bill_values(items=[] , invoice_discount="0"))
    with pytest.raises(BillError, match="at least one bill item"):
        service.issue_bill(business_id, user_id, bill_id)


def test_partial_and_full_payments_update_balance(workspace):
    _, user_id, business_id, service = workspace
    bill_id = service.create_bill(business_id, user_id, bill_values(invoice_discount="0"))
    service.issue_bill(business_id, user_id, bill_id)
    service.record_payment(business_id, user_id, bill_id, "500", "UPI", "UTR-A")
    bill = service.get_bill(business_id, bill_id)
    assert bill["status"] == "part_paid"
    assert bill["balance_due"] == "680.00"
    with pytest.raises(BillError, match="exceeds the outstanding balance"):
        service.record_payment(business_id, user_id, bill_id, "700", "Cash")
    service.record_payment(business_id, user_id, bill_id, "680", "Bank transfer", "NEFT-42")
    paid = service.get_bill(business_id, bill_id)
    assert paid["status"] == "paid"
    assert paid["balance_due"] == "0.00"
    assert len(paid["payments"]) == 2
    assert any(payment["payment_method"] == "Bank transfer" for payment in paid["payments"])


def test_only_unpaid_issued_bill_can_be_cancelled(workspace):
    database, user_id, business_id, service = workspace
    bill_id = service.create_bill(business_id, user_id, bill_values(invoice_discount="0"))
    service.issue_bill(business_id, user_id, bill_id)
    service.cancel_bill(business_id, user_id, bill_id, "Customer order withdrawn")
    bill = service.get_bill(business_id, bill_id)
    assert bill["status"] == "cancelled"
    with database.connection() as conn:
        row = conn.execute(
            "SELECT details_json FROM audit_logs WHERE entity_type='bill' AND entity_id=? AND action='bill.cancelled'",
            (bill_id,),
        ).fetchone()
    assert "Customer order withdrawn" in row["details_json"]


def test_b2b_requires_valid_gstin_and_bill_list_is_business_scoped(workspace):
    database, user_id, business_id, service = workspace
    with pytest.raises(BillError, match="GSTIN is required"):
        service.create_bill(business_id, user_id, bill_values(customer_type="B2B", customer_gstin=""))
    with pytest.raises(BillError, match="valid 15-character GSTIN"):
        service.create_bill(business_id, user_id, bill_values(customer_type="B2B", customer_gstin="BADGSTIN"))
    bill_id = service.create_bill(business_id, user_id, bill_values(invoice_discount="0"))
    second_business = "BIZ-NOT-THIS-WORKSPACE"
    assert service.get_bill(second_business, bill_id) is None
    assert service.list_bills(second_business) == []


def test_template_crud_and_role_permissions(workspace):
    database, user_id, business_id, service = workspace
    template_id = service.save_template(business_id, user_id, {
        "template_name": "Cedar Custom", "page_size": "A4", "accent_color": "#315B43",
        "font_family": "Unicode Sans", "font_size": 10, "show_business_contact": True,
        "show_gstin": True, "is_default": False, "footer_text": "Payment appreciated.",
    })
    custom = next(item for item in service.list_templates(business_id) if item["template_id"] == template_id)
    assert custom["template_name"] == "Cedar Custom"
    assert custom["accent_color"] == "#315B43"

    with database.transaction() as conn:
        conn.execute("UPDATE user_businesses SET role='cashier' WHERE user_id=? AND business_id=?", (user_id, business_id))
    with pytest.raises(BillError, match="does not allow this billing action"):
        service.save_template(business_id, user_id, {
            "template_name": "Blocked Theme", "accent_color": "#C9E86A", "is_default": False,
        })
    with database.transaction() as conn:
        conn.execute("UPDATE user_businesses SET role='owner' WHERE user_id=? AND business_id=?", (user_id, business_id))
    service.delete_template(business_id, user_id, template_id)
    assert all(item["template_id"] != template_id for item in service.list_templates(business_id))


def test_pdf_generator_creates_nonempty_invoice_pdf(workspace, tmp_path):
    database, user_id, business_id, service = workspace
    template_id = service.list_templates(business_id)[0]["template_id"]
    bill_id = service.create_bill(business_id, user_id, bill_values(template_id, invoice_discount="0"))
    output = generate_invoice_pdf(database, business_id, bill_id, tmp_path / "bill.pdf", template_id)
    assert output.exists()
    assert output.stat().st_size > 1000
    assert output.read_bytes().startswith(b"%PDF-")


def test_default_theme_cannot_be_unset_without_replacement(workspace):
    _, user_id, business_id, service = workspace
    default = service.list_templates(business_id)[0]
    values = {
        "template_name": default["template_name"],
        "page_size": default["page_size"],
        "accent_color": default["accent_color"],
        "font_family": default["font_family"],
        "font_size": default["font_size"],
        "show_business_contact": bool(default["show_business_contact"]),
        "show_gstin": bool(default["show_gstin"]),
        "is_default": False,
        "footer_text": default["footer_text"],
    }
    with pytest.raises(BillError, match="current default flag"):
        service.save_template(business_id, user_id, values, default["template_id"])
    assert sum(int(item["is_default"]) for item in service.list_templates(business_id)) == 1


def test_default_theme_recovery_reuses_existing_classic(workspace):
    database, _, business_id, service = workspace
    templates = service.list_templates(business_id)
    classic_id = next(item["template_id"] for item in templates if item["template_name"] == "KoshFlow Classic")
    with database.transaction() as conn:
        conn.execute("UPDATE pdf_templates SET is_default = 0 WHERE business_id = ?", (business_id,))
    recovered = service.ensure_default_template(business_id)
    assert recovered == classic_id
    refreshed = service.list_templates(business_id)
    assert sum(int(item["is_default"]) for item in refreshed) == 1
