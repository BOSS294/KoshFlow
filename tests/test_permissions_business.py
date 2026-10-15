"""Tests for role permissions and business-profile validation.

Purpose: Confirm role rules are explicit and profile writes are audited.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added permission matrix and profile update tests.
"""

import pytest

from koshflow.core.permissions import has_permission, visible_navigation
from koshflow.services.auth_service import AuthService
from koshflow.services.business_service import BusinessProfileError, BusinessService
from koshflow.services.setup_service import SetupService
from tests.helpers import valid_setup


def test_permissions_filter_navigation():
    assert has_permission("owner", "ai.view")
    assert has_permission("cashier", "billing.view")
    assert not has_permission("cashier", "accounts.view")
    assert {item["key"] for item in visible_navigation("viewer")} == {"overview", "reports"}


def test_business_profile_updates_and_audit(database):
    SetupService(database).complete_setup(valid_setup())
    session = AuthService(database).authenticate("aarav.owner", "Strong-Local-Password-10")
    service = BusinessService(database)
    profile = service.update_profile(session, {
        "legal_name": "Example Trading House Pvt Ltd",
        "trade_name": "Example House",
        "business_type": "Wholesale",
        "state": "Chhattisgarh",
        "gstin": "",
        "pan": "",
        "email": "office@example.test",
        "phone": "9876543210",
        "address": "Station Road",
        "city": "Bilaspur",
        "pincode": "495001",
    })
    assert profile["legal_name"] == "Example Trading House Pvt Ltd"
    with database.connection() as conn:
        audit = conn.execute("SELECT 1 FROM audit_logs WHERE action = 'business.profile_updated' LIMIT 1").fetchone()
    assert audit is not None


def test_invalid_gstin_is_rejected(database):
    SetupService(database).complete_setup(valid_setup())
    session = AuthService(database).authenticate("aarav.owner", "Strong-Local-Password-10")
    with pytest.raises(BusinessProfileError, match="valid 15-character GSTIN"):
        BusinessService(database).update_profile(session, {
            "legal_name": "Updated Name",
            "gstin": "BADGSTIN",
        })
