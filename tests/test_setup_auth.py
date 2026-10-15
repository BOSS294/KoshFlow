"""Tests for initial setup and local authentication.

Purpose: Verify owner registration is atomic and passwords are stored as hashes.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added registration, login and repeat-setup tests.
"""

import pytest

from koshflow.services.auth_service import AuthService, AuthenticationError
from koshflow.services.setup_service import SetupError, SetupService
from tests.helpers import valid_setup


def test_initial_setup_creates_business_and_owner(database):
    user_id, business_id = SetupService(database).complete_setup(valid_setup())
    with database.connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        business = conn.execute("SELECT * FROM businesses WHERE business_id = ?", (business_id,)).fetchone()
        membership = conn.execute("SELECT * FROM user_businesses WHERE user_id = ?", (user_id,)).fetchone()
    assert user is not None
    assert user["password_hash"] != "Strong-Local-Password-10"
    assert user["password_hash"].startswith("$argon2")
    assert business["legal_name"] == "Example Trading House"
    assert membership["role"] == "owner"
    assert database.get_setting("theme") == "light"


def test_local_login_returns_session(database):
    SetupService(database).complete_setup(valid_setup())
    session = AuthService(database).authenticate("AARAV.OWNER", "Strong-Local-Password-10")
    assert session.username == "aarav.owner"
    assert session.role == "owner"
    assert session.business_id.startswith("BIZ-")


def test_wrong_password_is_rejected(database):
    SetupService(database).complete_setup(valid_setup())
    with pytest.raises(AuthenticationError, match="incorrect"):
        AuthService(database).authenticate("aarav.owner", "wrong-password")


def test_setup_cannot_be_repeated(database):
    service = SetupService(database)
    service.complete_setup(valid_setup())
    with pytest.raises(SetupError, match="already complete"):
        service.complete_setup(valid_setup(username="another.owner"))


def test_invalid_password_confirmation_does_not_create_records(database):
    data = valid_setup(confirm_password="does-not-match")
    with pytest.raises(SetupError, match="do not match"):
        SetupService(database).complete_setup(data)
    assert not database.has_users()
