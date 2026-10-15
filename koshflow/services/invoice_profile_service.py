"""Business-scoped invoice branding and payment settings.

Purpose: Persist the optional logo, website, bank details, UPI ID and payment QR used by PDF invoices.
Project: KoshFlow | Version: 0.5.4
Canonical path: koshflow/services/invoice_profile_service.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Use load_invoice_profile(Database, business_id) and save_invoice_profile(...).
Changelog: v0.5.4 — Added reusable local invoice identity and payment settings.
"""
from __future__ import annotations

from typing import Any
from koshflow.core.database import Database

DEFAULTS: dict[str, str] = {
    "website": "",
    "logo_path": "",
    "bank_account_name": "",
    "bank_name": "",
    "account_number": "",
    "ifsc": "",
    "branch": "",
    "upi_id": "",
    "qr_code_path": "",
    "show_bank": "1",
    "show_upi": "1",
    "show_qr": "1",
}


def load_invoice_profile(database: Database, business_id: str) -> dict[str, Any]:
    """Return the business invoice profile with safe defaults for pre-v0.5.4 databases."""
    result: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        value = database.get_setting(f"invoice_{key}", default, scope="business", scope_id=business_id)
        result[key] = str(value if value is not None else default)
    for key in ("show_bank", "show_upi", "show_qr"):
        result[key] = result[key] not in {"0", "false", "False", "no", "No"}
    return result


def save_invoice_profile(database: Database, business_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """Save only known fields in the current business scope."""
    for key, default in DEFAULTS.items():
        if key not in values:
            continue
        value = values[key]
        if key in {"show_bank", "show_upi", "show_qr"}:
            normalized = "1" if bool(value) else "0"
        else:
            normalized = str(value if value is not None else "").strip()
            if key == "website" and normalized and not normalized.startswith(("https://", "http://")):
                normalized = "https://" + normalized
        database.set_setting(f"invoice_{key}", normalized, scope="business", scope_id=business_id)
    return load_invoice_profile(database, business_id)
