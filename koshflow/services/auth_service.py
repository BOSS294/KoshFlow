"""Local authentication service with hashed credentials and lockout protection.

Purpose: Authenticate an owner or local team member and issue an in-memory session.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added Argon2 verification, temporary failed-login throttling,
           audit records, and password rehash support.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from argon2 import PasswordHasher

from koshflow.core.database import Database
from koshflow.core.security import new_id, normalize_username, password_needs_rehash, hash_password, verify_password
from koshflow.core.session import Session


class AuthenticationError(ValueError):
    """Expected authentication failure suitable for a UI message."""


class AuthService:
    MAX_ATTEMPTS = 5
    LOCK_SECONDS = 30

    def __init__(self, database: Database):
        self.database = database
        self._failures: dict[str, list[float]] = {}

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def authenticate(self, username: str, password: str) -> Session:
        key = normalize_username(username)
        now_tick = time.monotonic()
        recent = [stamp for stamp in self._failures.get(key, []) if now_tick - stamp < self.LOCK_SECONDS]
        self._failures[key] = recent
        if len(recent) >= self.MAX_ATTEMPTS:
            remaining = max(1, int(self.LOCK_SECONDS - (now_tick - recent[0])))
            raise AuthenticationError(f"Too many attempts. Try again in about {remaining} seconds.")

        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT u.user_id, u.username, u.display_name, u.password_hash, u.is_active, "
                "m.business_id, m.role FROM users u "
                "JOIN user_businesses m ON m.user_id = u.user_id "
                "WHERE u.username = ? COLLATE NOCASE AND m.is_default = 1 LIMIT 1",
                (key,),
            ).fetchone()

        if not row or not row["is_active"] or not verify_password(row["password_hash"], password):
            recent.append(now_tick)
            self._failures[key] = recent
            raise AuthenticationError("The username or password is incorrect.")

        self._failures.pop(key, None)
        with self.database.transaction() as conn:
            current = conn.execute(
                "SELECT password_hash FROM users WHERE user_id = ?", (row["user_id"],)
            ).fetchone()
            if current and password_needs_rehash(current["password_hash"]):
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE user_id = ?",
                    (hash_password(password), row["user_id"]),
                )
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?",
                (self._utc_now(), row["user_id"]),
            )
            conn.execute(
                "INSERT INTO audit_logs(audit_id, business_id, actor_user_id, action, entity_type, entity_id, details_json, created_at) "
                "VALUES(?, ?, ?, 'auth.login', 'user', ?, ?, ?)",
                (new_id("AUD"), row["business_id"], row["user_id"], row["user_id"],
                 json.dumps({"method": "local_password"}), self._utc_now()),
            )

        return Session(
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            role=row["role"],
            business_id=row["business_id"],
        )
