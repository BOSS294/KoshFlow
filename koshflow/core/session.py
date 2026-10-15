"""Authenticated in-memory session model.

Purpose: Pass validated identity and role context to the desktop UI without storing
         a plaintext password or persistent authentication token.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Introduced immutable session data.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Session:
    user_id: str
    username: str
    display_name: str
    role: str
    business_id: str
