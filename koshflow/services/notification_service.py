"""Local business notification generation and inbox persistence.

Purpose: Create actionable local alerts for overdue balances, upcoming due dates and stock risks.
Project: KoshFlow | Version: 0.6.3
Canonical path: koshflow/services/notification_service.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: NotificationService(database).scan_business(business_id) returns newly activated alerts.
Changelog: v0.6.3 — Added notification preferences, explicit test notifications, and case-insensitive legacy status handling.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from koshflow.config import DEFAULT_TIMEZONE
from koshflow.core.database import Database
from koshflow.core.security import new_id


def _dec(value: Any) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
        return result if result.is_finite() else Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _now() -> str:
    return datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat(timespec="seconds")


class NotificationService:
    """Database-backed alert lifecycle with transition-based deduplication."""

    TRACKED_CATEGORIES = ("receivables", "payables", "inventory", "purchasing")

    def __init__(self, database: Database):
        self.database = database

    def _collect_current(self, business_id: str, today: date) -> dict[str, dict[str, str]]:
        today_s = today.isoformat()
        soon_s = (today + timedelta(days=7)).isoformat()
        alerts: dict[str, dict[str, str]] = {}
        with self.database.connection() as conn:
            bills = conn.execute(
                "SELECT bill_id,bill_number,customer_name,due_date,grand_total,amount_paid,status FROM bills "
                "WHERE business_id=? AND LOWER(TRIM(status)) IN ('issued','part_paid') AND due_date<>''",
                (business_id,),
            ).fetchall()
            for row in bills:
                balance = (_dec(row["grand_total"]) - _dec(row["amount_paid"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                due = str(row["due_date"] or "")[:10]
                if balance <= 0 or not due:
                    continue
                if due < today_s:
                    severity, title, message = "critical", "Customer invoice overdue", f"{row['bill_number']} · {row['customer_name']} has ₹{balance:,.2f} outstanding since {due}."
                elif due <= soon_s:
                    severity, title, message = "warning", "Customer payment due soon", f"{row['bill_number']} · {row['customer_name']} has ₹{balance:,.2f} due on {due}."
                else:
                    continue
                key = f"sales_due:{row['bill_id']}"
                alerts[key] = {"category": "receivables", "severity": severity, "title": title, "message": message,
                               "related_page": "billing_manage", "related_id": str(row["bill_id"])}

            purchases = conn.execute(
                "SELECT pb.purchase_bill_id,pb.purchase_number,pb.due_date,pb.grand_total,pb.amount_paid,s.name supplier_name "
                "FROM purchase_bills pb JOIN suppliers s ON s.supplier_id=pb.supplier_id "
                "WHERE pb.business_id=? AND LOWER(TRIM(pb.status)) IN ('posted','part_paid') AND pb.due_date<>''",
                (business_id,),
            ).fetchall()
            for row in purchases:
                balance = (_dec(row["grand_total"]) - _dec(row["amount_paid"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                due = str(row["due_date"] or "")[:10]
                if balance <= 0 or not due:
                    continue
                if due < today_s:
                    severity, title, message = "critical", "Supplier payment overdue", f"{row['purchase_number']} · {row['supplier_name']} has ₹{balance:,.2f} payable since {due}."
                elif due <= soon_s:
                    severity, title, message = "warning", "Supplier payment due soon", f"{row['purchase_number']} · {row['supplier_name']} has ₹{balance:,.2f} due on {due}."
                else:
                    continue
                key = f"purchase_due:{row['purchase_bill_id']}"
                alerts[key] = {"category": "payables", "severity": severity, "title": title, "message": message,
                               "related_page": "purchase_bills", "related_id": str(row["purchase_bill_id"])}

            products = conn.execute(
                "SELECT product_id,sku,name,quantity_on_hand,reorder_level FROM products WHERE business_id=? AND is_active=1 AND CAST(reorder_level AS REAL)>0",
                (business_id,),
            ).fetchall()
            for row in products:
                quantity, reorder = _dec(row["quantity_on_hand"]), _dec(row["reorder_level"])
                if quantity > reorder:
                    continue
                if quantity <= 0:
                    severity, title, message = "critical", "Product out of stock", f"{row['sku']} · {row['name']} has no stock. Reorder level is {reorder:g}."
                else:
                    severity, title, message = "warning", "Low stock warning", f"{row['sku']} · {row['name']} has {quantity:g} in stock; reorder level is {reorder:g}."
                key = f"stock_level:{row['product_id']}"
                alerts[key] = {"category": "inventory", "severity": severity, "title": title, "message": message,
                               "related_page": "inventory_low_stock", "related_id": str(row["product_id"])}

            orders = conn.execute(
                "SELECT purchase_order_id,order_number,expected_date,status FROM purchase_orders "
                "WHERE business_id=? AND LOWER(TRIM(status)) IN ('ordered','partially_received') AND expected_date<>''",
                (business_id,),
            ).fetchall()
            for row in orders:
                due = str(row["expected_date"] or "")[:10]
                if not due or due > soon_s:
                    continue
                overdue = due < today_s
                key = f"purchase_order_due:{row['purchase_order_id']}"
                alerts[key] = {"category": "purchasing", "severity": "critical" if overdue else "info",
                               "title": "Purchase order overdue" if overdue else "Purchase order expected soon",
                               "message": f"{row['order_number']} is {'past its expected date' if overdue else 'expected'} on {due}.",
                               "related_page": "purchase_orders", "related_id": str(row["purchase_order_id"])}
        return alerts

    def scan_business(self, business_id: str, today: date | None = None) -> list[dict[str, Any]]:
        """Refresh alert state and return only newly activated or escalated alerts."""
        current = self._collect_current(business_id, today or datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date())
        preference_keys = {
            "receivables": "notify_customer_due", "payables": "notify_supplier_due",
            "inventory": "notify_low_stock", "purchasing": "notify_purchase_order_dates",
        }
        for category, setting_key in preference_keys.items():
            if self.database.get_setting(setting_key, "1", scope="business", scope_id=business_id) == "0":
                current = {key: value for key, value in current.items() if value.get("category") != category}
        now = _now()
        newly_active: list[dict[str, Any]] = []
        with self.database.transaction() as conn:
            existing_rows = conn.execute("SELECT * FROM notifications WHERE business_id=?", (business_id,)).fetchall()
            existing = {str(row["alert_key"]): dict(row) for row in existing_rows}
            # Close alerts which no longer reflect an active condition. This allows a later recurrence to notify again.
            for key, row in existing.items():
                if row["is_active"] and row["category"] in self.TRACKED_CATEGORIES and key not in current:
                    conn.execute("UPDATE notifications SET is_active=0,updated_at=? WHERE notification_id=?", (now, row["notification_id"]))

            for key, alert in current.items():
                prior = existing.get(key)
                if prior is None:
                    notification_id = new_id("NTF")
                    conn.execute(
                        "INSERT INTO notifications(notification_id,business_id,alert_key,category,severity,title,message,related_page,related_id,is_active,is_read,is_dismissed,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,1,0,0,?,?)",
                        (notification_id, business_id, key, alert["category"], alert["severity"], alert["title"], alert["message"], alert["related_page"], alert["related_id"], now, now),
                    )
                    newly_active.append({"notification_id": notification_id, **alert})
                else:
                    escalated = prior["is_active"] and prior["severity"] != alert["severity"] and alert["severity"] == "critical"
                    reactivated = not prior["is_active"]
                    conn.execute(
                        "UPDATE notifications SET category=?,severity=?,title=?,message=?,related_page=?,related_id=?,is_active=1,"
                        "is_read=CASE WHEN ? THEN 0 ELSE is_read END,is_dismissed=CASE WHEN ? THEN 0 ELSE is_dismissed END,updated_at=? WHERE notification_id=?",
                        (alert["category"], alert["severity"], alert["title"], alert["message"], alert["related_page"], alert["related_id"], int(reactivated or escalated), int(reactivated), now, prior["notification_id"]),
                    )
                    if reactivated or escalated:
                        newly_active.append({"notification_id": prior["notification_id"], **alert})
        return newly_active

    def create_test_notification(self, business_id: str) -> dict[str, Any]:
        """Persist a test alert so the settings page can verify inbox plumbing safely."""
        now = _now()
        notification_id = new_id("NTF")
        message = "KoshFlow created this test alert. If desktop notifications are enabled, check your operating-system notification center."
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO notifications(notification_id,business_id,alert_key,category,severity,title,message,related_page,related_id,is_active,is_read,is_dismissed,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,1,0,0,?,?)",
                (notification_id, business_id, f"test:{notification_id}", "system", "info",
                 "KoshFlow notification test", message, "settings", "", now, now),
            )
        return {
            "notification_id": notification_id, "business_id": business_id,
            "category": "system", "severity": "info", "title": "KoshFlow notification test",
            "message": message, "related_page": "settings", "related_id": None,
            "is_active": 1, "is_read": 0, "is_dismissed": 0,
            "created_at": now, "updated_at": now,
        }

    def list_notifications(self, business_id: str, limit: int = 40, include_dismissed: bool = False) -> list[dict[str, Any]]:
        clause = "" if include_dismissed else "AND is_dismissed=0"
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM notifications WHERE business_id=? {clause} ORDER BY is_read ASC, is_active DESC, updated_at DESC LIMIT ?",
                (business_id, max(1, min(200, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def unread_count(self, business_id: str) -> int:
        with self.database.connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM notifications WHERE business_id=? AND is_active=1 AND is_read=0 AND is_dismissed=0", (business_id,)).fetchone()
        return int(row[0] or 0)

    def mark_read(self, business_id: str, notification_id: str) -> None:
        with self.database.transaction() as conn:
            conn.execute("UPDATE notifications SET is_read=1,updated_at=? WHERE business_id=? AND notification_id=?", (_now(), business_id, notification_id))

    def mark_all_read(self, business_id: str) -> None:
        with self.database.transaction() as conn:
            conn.execute("UPDATE notifications SET is_read=1,updated_at=? WHERE business_id=? AND is_active=1 AND is_dismissed=0", (_now(), business_id))

    def dismiss(self, business_id: str, notification_id: str) -> None:
        with self.database.transaction() as conn:
            conn.execute("UPDATE notifications SET is_read=1,is_dismissed=1,updated_at=? WHERE business_id=? AND notification_id=?", (_now(), business_id, notification_id))
