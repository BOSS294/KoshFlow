"""Business profile persistence and audit helpers.

Purpose: Allow owners and authorized roles to edit their business profile safely.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added allow-listed profile updates and validation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from koshflow.core.database import Database
from koshflow.core.security import new_id, normalize_gstin, normalize_pan, validate_gstin, validate_pan
from koshflow.core.session import Session


class BusinessProfileError(ValueError):
    """Expected business profile validation failure."""


EDITABLE_FIELDS = {
    "legal_name", "trade_name", "business_type", "address", "city", "state",
    "pincode", "phone", "email", "gstin", "pan",
}


class BusinessService:
    def __init__(self, database: Database):
        self.database = database

    def get_profile(self, business_id: str) -> dict[str, str]:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT * FROM businesses WHERE business_id = ?", (business_id,)
            ).fetchone()
        if not row:
            raise BusinessProfileError("The selected business profile could not be found.")
        return dict(row)

    def update_profile(self, session: Session, fields: dict[str, str]) -> dict[str, str]:
        values = {key: str(value or "").strip() for key, value in fields.items() if key in EDITABLE_FIELDS}
        current = self.get_profile(session.business_id)
        effective_legal_name = values.get("legal_name", current.get("legal_name", ""))
        if not effective_legal_name.strip():
            raise BusinessProfileError("Business legal name is required.")
        effective_gstin = normalize_gstin(values.get("gstin", current.get("gstin", "")))
        effective_pan = normalize_pan(values.get("pan", current.get("pan", "")))
        if error := validate_gstin(effective_gstin):
            raise BusinessProfileError(error)
        if error := validate_pan(effective_pan):
            raise BusinessProfileError(error)
        if "gstin" in values:
            values["gstin"] = effective_gstin
        if "pan" in values:
            values["pan"] = effective_pan
        if "email" in values and values["email"] and ("@" not in values["email"] or values["email"].startswith("@")):
            raise BusinessProfileError("Enter a valid email address.")

        if not values:
            return current
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        assignments = ", ".join(f"{field} = ?" for field in values)
        params = list(values.values()) + [now, session.business_id]
        with self.database.transaction() as conn:
            membership = conn.execute(
                "SELECT role FROM user_businesses WHERE user_id = ? AND business_id = ?",
                (session.user_id, session.business_id),
            ).fetchone()
            if not membership or membership["role"] not in {"owner", "admin", "accountant", "manager"}:
                raise BusinessProfileError("Your role does not allow business profile changes.")
            conn.execute(
                f"UPDATE businesses SET {assignments}, updated_at = ? WHERE business_id = ?",
                params,
            )
            conn.execute(
                "INSERT INTO audit_logs(audit_id, business_id, actor_user_id, action, entity_type, entity_id, details_json, created_at) "
                "VALUES(?, ?, ?, 'business.profile_updated', 'business', ?, ?, ?)",
                (new_id("AUD"), session.business_id, session.user_id, session.business_id,
                 json.dumps({"fields": sorted(values.keys())}), now),
            )
        return self.get_profile(session.business_id)
