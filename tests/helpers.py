"""Shared test data for setup and authentication flows.

Purpose: Avoid duplicating valid first-run registration fixtures.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added reusable setup form data.
"""


def valid_setup(**overrides):
    data = {
        "legal_name": "Example Trading House",
        "trade_name": "Example Trade",
        "business_type": "Retail",
        "state": "Chhattisgarh",
        "gstin": "",
        "pan": "",
        "display_name": "Aarav Sharma",
        "username": "aarav.owner",
        "password": "Strong-Local-Password-10",
        "confirm_password": "Strong-Local-Password-10",
    }
    data.update(overrides)
    return data
