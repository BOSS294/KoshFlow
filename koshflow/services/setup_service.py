"""First-run business and owner registration service.

Purpose: Validate initial setup and write business, owner, membership, settings,
         and audit metadata in a single transaction.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Implemented one-time local owner and business registration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from koshflow.core.database import Database
from koshflow.core.security import (
    hash_password, new_id, normalize_gstin, normalize_pan, normalize_username,
    validate_gstin, validate_pan, validate_username,
)


class SetupError(ValueError):
    """Expected setup validation or registration error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SetupService:
    def __init__(self, database: Database):
        self.database = database

    def complete_setup(self, data: dict[str, str]) -> tuple[str, str]:
        business_name = data.get("legal_name", "").strip()
        display_name = data.get("display_name", "").strip()
        username = normalize_username(data.get("username", ""))
        password = data.get("password", "")
        confirm_password = data.get("confirm_password", "")
        gstin = normalize_gstin(data.get("gstin", ""))
        pan = normalize_pan(data.get("pan", ""))

        if not business_name:
            raise SetupError("Enter your legal or registered business name.")
        if not display_name:
            raise SetupError("Enter the owner's name.")
        if error := validate_username(username):
            raise SetupError(error)
        if len(password) < 10:
            raise SetupError("Use a password with at least 10 characters.")
        if password != confirm_password:
            raise SetupError("The passwords do not match.")
        if error := validate_gstin(gstin):
            raise SetupError(error)
        if error := validate_pan(pan):
            raise SetupError(error)

        password_hash = hash_password(password)
        business_id = new_id("BIZ")
        user_id = new_id("USR")
        membership_id = new_id("MBR")
        now = utc_now()

        try:
            with self.database.transaction() as conn:
                if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                    raise SetupError("Initial setup is already complete. Please sign in.")
                conn.execute(
                    "INSERT INTO businesses(business_id, legal_name, trade_name, business_type, "
                    "state, phone, email, gstin, pan, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        business_id,
                        business_name,
                        data.get("trade_name", "").strip(),
                        data.get("business_type", "Other").strip() or "Other",
                        data.get("state", "").strip(),
                        data.get("phone", "").strip(),
                        data.get("email", "").strip().lower(),
                        gstin,
                        pan,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO users(user_id, username, display_name, password_hash, created_at) "
                    "VALUES(?, ?, ?, ?, ?)",
                    (user_id, username, display_name, password_hash, now),
                )
                conn.execute(
                    "INSERT INTO user_businesses(membership_id, user_id, business_id, role, is_default, created_at) "
                    "VALUES(?, ?, ?, 'owner', 1, ?)",
                    (membership_id, user_id, business_id, now),
                )
                conn.execute(
                    "INSERT INTO app_settings(setting_scope, scope_id, setting_key, setting_value, updated_at) "
                    "VALUES('app', '', 'theme', 'light', ?) "
                    "ON CONFLICT(setting_scope, scope_id, setting_key) DO NOTHING",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO audit_logs(audit_id, business_id, actor_user_id, action, entity_type, entity_id, details_json, created_at) "
                    "VALUES(?, ?, ?, 'workspace.created', 'business', ?, ?, ?)",
                    (new_id("AUD"), business_id, user_id, business_id,
                     json.dumps({"source": "first_run_setup"}), now),
                )
        except SetupError:
            raise
        except Exception as exc:
            if "UNIQUE constraint failed: users.username" in str(exc):
                raise SetupError("That username is already in use.") from exc
            raise SetupError(f"Could not complete setup: {exc}") from exc
        return user_id, business_id
