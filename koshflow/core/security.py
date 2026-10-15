"""Local credential hashing and input validation.

Purpose: Keep password handling out of UI code and standardize generated IDs.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Argon2 password hashing and practical registration validators.
"""

from __future__ import annotations

import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_PASSWORD_HASHER = PasswordHasher()
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,31}$")


def new_id(prefix: str) -> str:
    """Create a readable, entity-prefixed opaque identifier."""
    return f"{prefix.upper()}-{secrets.token_hex(8).upper()}"


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Use a password with at least 10 characters.")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str | None:
    if not USERNAME_PATTERN.fullmatch(username.strip()):
        return "Username must be 3–32 characters and use letters, numbers, dots, dashes or underscores."
    return None


def normalize_gstin(gstin: str) -> str:
    return gstin.strip().upper().replace(" ", "")


def validate_gstin(gstin: str) -> str | None:
    value = normalize_gstin(gstin)
    if value and not GSTIN_PATTERN.fullmatch(value):
        return "Enter a valid 15-character GSTIN, or leave this field empty for now."
    return None


def normalize_pan(pan: str) -> str:
    return pan.strip().upper().replace(" ", "")


def validate_pan(pan: str) -> str | None:
    value = normalize_pan(pan)
    if value and not PAN_PATTERN.fullmatch(value):
        return "Enter a valid 10-character PAN, or leave this field empty for now."
    return None
