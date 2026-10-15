"""Role and navigation permission policy.

Purpose: Centralize UI visibility and action authorization by local membership role.
Project: KoshFlow | Version: 0.6.2
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.6.2 — Removed Services from user-facing navigation and role permissions.
"""

from __future__ import annotations

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": {"*"},
    "admin": {
        "dashboard.view", "billing.view", "billing.create", "billing.edit_draft", "billing.issue",
        "billing.delete_draft", "billing.cancel", "billing.payment", "billing.pdf", "billing.send", "billing.theme_manage",
        "inventory.view", "inventory.manage", "inventory.adjust", "inventory.export",
        "purchasing.view", "purchasing.manage_suppliers", "purchasing.create", "purchasing.post",
        "purchasing.receive", "purchasing.pay", "purchasing.return", "purchasing.report",
        "contacts.view", "contacts.manage", "accounts.view", "accounts.manage", "accounts.journal_manage", "accounts.period_lock", "reports.view", "ai.view",
        "settings.view", "business.edit", "backup.create", "backup.restore",
    },
    "accountant": {
        "dashboard.view", "billing.view", "billing.create", "billing.edit_draft", "billing.issue",
        "billing.delete_draft", "billing.cancel", "billing.payment", "billing.pdf", "billing.send", "billing.theme_manage",
        "inventory.view", "inventory.manage", "inventory.adjust", "inventory.export",
        "purchasing.view", "purchasing.manage_suppliers", "purchasing.create", "purchasing.post",
        "purchasing.receive", "purchasing.pay", "purchasing.return", "purchasing.report",
        "contacts.view", "contacts.manage", "accounts.view", "accounts.manage", "accounts.journal_manage", "accounts.period_lock", "reports.view", "ai.view", "settings.view",
        "business.edit", "backup.create",
    },
    "manager": {
        "dashboard.view", "billing.view", "billing.create", "billing.edit_draft", "billing.issue",
        "billing.delete_draft", "billing.cancel", "billing.payment", "billing.pdf", "billing.send", "billing.theme_manage",
        "inventory.view", "inventory.manage", "inventory.adjust", "inventory.export",
        "purchasing.view", "purchasing.manage_suppliers", "purchasing.create", "purchasing.post",
        "purchasing.receive", "purchasing.pay", "purchasing.return", "purchasing.report",
        "contacts.view", "contacts.manage", "reports.view", "settings.view", "business.edit",
    },
    "cashier": {"dashboard.view", "billing.view", "billing.create", "billing.edit_draft", "billing.issue", "billing.payment", "billing.pdf", "billing.send", "contacts.view"},
    "viewer": {"dashboard.view", "reports.view"},
}

NAV_ITEMS = [
    {"key": "overview", "label": "Overview", "icon": "home", "permission": "dashboard.view"},
    {"key": "billing", "label": "Billing", "icon": "receipt", "permission": "billing.view"},
    {"key": "inventory", "label": "Inventory", "icon": "package", "permission": "inventory.view"},
    {"key": "contacts", "label": "Contacts", "icon": "users", "permission": "contacts.view"},
    {"key": "accounts", "label": "Accounts", "icon": "wallet", "permission": "accounts.view"},
    {"key": "reports", "label": "Reports", "icon": "chart", "permission": "reports.view"},
    {"key": "ai", "label": "AI insights", "icon": "sparkles", "permission": "ai.view"},
    {"key": "settings", "label": "Settings", "icon": "settings", "permission": "settings.view"},
]


def has_permission(role: str, permission: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(role, set())
    return "*" in permissions or permission in permissions


def visible_navigation(role: str) -> list[dict[str, str]]:
    return [item for item in NAV_ITEMS if has_permission(role, item["permission"])]
