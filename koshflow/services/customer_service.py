"""Customer directory and account activity service.

Purpose: Provide business-scoped customer CRUD, quick-sale contact resolution and customer statements.
Project: KoshFlow | Version: 0.5.0
Canonical path: koshflow/services/customer_service.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Use CustomerService(Database) from Contacts and Quick Billing screens.
Changelog: v0.5.0 — Added customer records, phone-based quick-sale resolution, balances and activity history.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import StringIO
from typing import Any

from koshflow.core.database import Database
from koshflow.core.permissions import has_permission
from koshflow.core.security import new_id, normalize_gstin, normalize_pan, validate_gstin, validate_pan


class CustomerError(ValueError):
    """User-safe customer validation and workflow error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CustomerError("Enter a valid monetary amount.") from exc
    if not result.is_finite() or result < 0:
        raise CustomerError("Monetary amounts cannot be negative or non-finite.")
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _phone_key(value: str) -> str:
    """Normalize common Indian phone input styles for duplicate-contact matching."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


class CustomerService:
    def __init__(self, database: Database):
        self.database = database

    def next_customer_code(self, business_id: str) -> str:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT customer_code FROM customers WHERE business_id=?", (business_id,)).fetchall()
        highest = 0
        for row in rows:
            match = re.fullmatch(r"CUS-(\d+)", str(row["customer_code"] or ""), re.I)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"CUS-{highest + 1:06d}"

    def create_customer(self, business_id: str, actor_user_id: str, values: dict[str, Any]) -> str:
        data = self._validate(values)
        now = _now()
        customer_id = new_id("CUS")
        try:
            with self.database.transaction() as conn:
                self._assert_actor(conn, business_id, actor_user_id, "contacts.manage")
                if not data["customer_code"]:
                    data["customer_code"] = self._next_code(conn, business_id)
                conn.execute(
                    "INSERT INTO customers(customer_id,business_id,customer_code,name,customer_type,contact_person,phone,alternate_phone,email,gstin,pan,address,city,state,pincode,credit_limit,payment_terms_days,notes,is_active,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (customer_id, business_id, data["customer_code"], data["name"], data["customer_type"],
                     data["contact_person"], data["phone"], data["alternate_phone"], data["email"], data["gstin"],
                     data["pan"], data["address"], data["city"], data["state"], data["pincode"],
                     f"{data['credit_limit']:.2f}", data["payment_terms_days"], data["notes"], now, now),
                )
                self._audit(conn, business_id, actor_user_id, "contacts.customer.created", "customer", customer_id,
                            {"customer_code": data["customer_code"], "name": data["name"]}, now)
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise CustomerError("A customer with this code already exists in this business.") from exc
            raise
        return customer_id

    def update_customer(self, business_id: str, actor_user_id: str, customer_id: str, values: dict[str, Any]) -> None:
        data = self._validate(values)
        now = _now()
        try:
            with self.database.transaction() as conn:
                self._assert_actor(conn, business_id, actor_user_id, "contacts.manage")
                old = conn.execute("SELECT * FROM customers WHERE business_id=? AND customer_id=?", (business_id, customer_id)).fetchone()
                if not old:
                    raise CustomerError("Customer not found in this business.")
                code = data["customer_code"] or str(old["customer_code"])
                conn.execute(
                    "UPDATE customers SET customer_code=?,name=?,customer_type=?,contact_person=?,phone=?,alternate_phone=?,email=?,gstin=?,pan=?,address=?,city=?,state=?,pincode=?,credit_limit=?,payment_terms_days=?,notes=?,updated_at=? WHERE business_id=? AND customer_id=?",
                    (code, data["name"], data["customer_type"], data["contact_person"], data["phone"],
                     data["alternate_phone"], data["email"], data["gstin"], data["pan"], data["address"],
                     data["city"], data["state"], data["pincode"], f"{data['credit_limit']:.2f}",
                     data["payment_terms_days"], data["notes"], now, business_id, customer_id),
                )
                self._audit(conn, business_id, actor_user_id, "contacts.customer.updated", "customer", customer_id,
                            {"customer_code": code, "name": data["name"]}, now)
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise CustomerError("A customer with this code already exists in this business.") from exc
            raise

    def archive_customer(self, business_id: str, actor_user_id: str, customer_id: str) -> None:
        now = _now()
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "contacts.manage")
            row = conn.execute("SELECT 1 FROM customers WHERE business_id=? AND customer_id=? AND is_active=1", (business_id, customer_id)).fetchone()
            if not row:
                raise CustomerError("Active customer not found in this business.")
            outstanding = self._outstanding(conn, business_id, customer_id)
            if outstanding > Decimal("0.00"):
                raise CustomerError("This customer has outstanding invoices. Settle or formally resolve the balance before archiving.")
            conn.execute("UPDATE customers SET is_active=0,updated_at=? WHERE business_id=? AND customer_id=?", (now, business_id, customer_id))
            self._audit(conn, business_id, actor_user_id, "contacts.customer.archived", "customer", customer_id, {}, now)

    def get_customer(self, business_id: str, customer_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM customers WHERE business_id=? AND customer_id=?", (business_id, customer_id)).fetchone()
            if not row:
                return None
            data = dict(row)
            data.update(self._aggregate(conn, business_id, customer_id))
            return data

    def list_customers(self, business_id: str, search: str = "", *, active_only: bool = True) -> list[dict[str, Any]]:
        clauses = ["c.business_id=?"]
        params: list[Any] = [business_id]
        if active_only:
            clauses.append("c.is_active=1")
        if search.strip():
            pattern = f"%{search.strip()}%"
            clauses.append("(c.name LIKE ? OR c.customer_code LIKE ? OR c.phone LIKE ? OR c.email LIKE ? OR c.gstin LIKE ? OR c.city LIKE ?)")
            params.extend([pattern] * 6)
        with self.database.connection() as conn:
            rows = conn.execute(f"SELECT c.* FROM customers c WHERE {' AND '.join(clauses)} ORDER BY c.name COLLATE NOCASE", params).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item.update(self._aggregate(conn, business_id, str(row["customer_id"])))
                result.append(item)
        return result

    def search_phone(self, business_id: str, phone: str) -> dict[str, Any] | None:
        key = _phone_key(phone)
        if len(key) < 7:
            return None
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM customers WHERE business_id=? AND is_active=1", (business_id,)).fetchall()
        match = next((row for row in rows if _phone_key(str(row["phone"])) == key), None)
        return dict(match) if match else None

    def resolve_or_create_for_sale(self, business_id: str, actor_user_id: str, values: dict[str, Any],
                                   *, existing_customer_id: str = "") -> str | None:
        """Resolve or save the customer for a completed counter sale.

        Phone is the strongest matching key. If no usable phone is supplied, an exact
        name match is reused only when the stored record also has no phone. This keeps
        repeated anonymous walk-in sales attached to one reusable contact without
        merging two separately identified customers who happen to share a name.
        """
        with self.database.transaction() as conn:
            self._assert_actor(conn, business_id, actor_user_id, "billing.create")
            if existing_customer_id:
                row = conn.execute("SELECT * FROM customers WHERE business_id=? AND customer_id=? AND is_active=1",
                                   (business_id, existing_customer_id)).fetchone()
                if not row:
                    raise CustomerError("The selected customer is no longer active in this business.")
                return str(row["customer_id"])
            name = str(values.get("name", "")).strip()
            phone = str(values.get("phone", "")).strip()
            if not name:
                return None
            key = _phone_key(phone)
            rows = conn.execute(
                "SELECT customer_id, name, phone FROM customers WHERE business_id=? AND is_active=1 ORDER BY created_at, customer_code",
                (business_id,),
            ).fetchall()
            if key and len(key) >= 7:
                match = next((row for row in rows if _phone_key(str(row["phone"])) == key), None)
                if match:
                    # Do not silently overwrite maintained customer details from the counter.
                    return str(match["customer_id"])
            else:
                normalized_name = " ".join(name.casefold().split())
                match = next((row for row in rows
                              if not _phone_key(str(row["phone"]))
                              and " ".join(str(row["name"]).casefold().split()) == normalized_name), None)
                if match:
                    return str(match["customer_id"])
            # Quick billing may add a customer because billing.create is independently authorized.
            data = self._validate({**values, "customer_code": ""})
            customer_id = new_id("CUS")
            now = _now()
            data["customer_code"] = self._next_code(conn, business_id)
            conn.execute(
                "INSERT INTO customers(customer_id,business_id,customer_code,name,customer_type,contact_person,phone,alternate_phone,email,gstin,pan,address,city,state,pincode,credit_limit,payment_terms_days,notes,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                (customer_id, business_id, data["customer_code"], data["name"], data["customer_type"], data["contact_person"],
                 data["phone"], data["alternate_phone"], data["email"], data["gstin"], data["pan"], data["address"],
                 data["city"], data["state"], data["pincode"], f"{data['credit_limit']:.2f}", data["payment_terms_days"], data["notes"], now, now),
            )
            self._audit(conn, business_id, actor_user_id, "contacts.customer.created_from_sale", "customer", customer_id,
                        {"customer_code": data["customer_code"], "name": data["name"]}, now)
            return customer_id

    def customer_activity(self, business_id: str, customer_id: str) -> dict[str, Any]:
        with self.database.connection() as conn:
            customer = conn.execute("SELECT 1 FROM customers WHERE business_id=? AND customer_id=?", (business_id, customer_id)).fetchone()
            if not customer:
                raise CustomerError("Customer not found in this business.")
            bills = [dict(r) for r in conn.execute(
                "SELECT bill_id,bill_number,invoice_date,status,grand_total,amount_paid,customer_name FROM bills WHERE business_id=? AND customer_id=? ORDER BY invoice_date DESC,created_at DESC",
                (business_id, customer_id),
            ).fetchall()]
            payments = [dict(r) for r in conn.execute(
                "SELECT p.payment_id,p.amount,p.payment_method,p.reference,p.paid_at,b.bill_number FROM bill_payments p JOIN bills b ON b.bill_id=p.bill_id WHERE p.business_id=? AND b.customer_id=? ORDER BY p.paid_at DESC",
                (business_id, customer_id),
            ).fetchall()]
        return {"bills": bills, "payments": payments}

    def export_csv(self, business_id: str) -> str:
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Customer code", "Name", "Type", "Phone", "Email", "GSTIN", "City", "State", "Invoices", "Sales total", "Collected", "Outstanding", "Active"])
        for row in self.list_customers(business_id, active_only=False):
            writer.writerow([row["customer_code"], row["name"], row["customer_type"], row["phone"], row["email"], row["gstin"], row["city"], row["state"], row["invoice_count"], row["sales_total"], row["collected_total"], row["outstanding_balance"], "Yes" if row["is_active"] else "No"])
        return output.getvalue()

    @staticmethod
    def _validate(values: dict[str, Any]) -> dict[str, Any]:
        name = str(values.get("name", "")).strip()
        if not name:
            raise CustomerError("Customer name is required.")
        customer_type = str(values.get("customer_type", "individual")).strip().lower()
        if customer_type not in {"individual", "business"}:
            raise CustomerError("Customer type must be Individual or Business.")
        gstin = normalize_gstin(str(values.get("gstin", "")))
        if gstin and (error := validate_gstin(gstin)):
            raise CustomerError(error)
        pan = normalize_pan(str(values.get("pan", "")))
        if pan and (error := validate_pan(pan)):
            raise CustomerError(error)
        try:
            terms = int(values.get("payment_terms_days", 0) or 0)
        except (ValueError, TypeError) as exc:
            raise CustomerError("Payment terms must be a whole number of days.") from exc
        if not 0 <= terms <= 365:
            raise CustomerError("Payment terms must be between 0 and 365 days.")
        email = str(values.get("email", "")).strip()
        if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
            raise CustomerError("Enter a valid email address.")
        return {
            "customer_code": str(values.get("customer_code", "")).strip()[:80], "name": name[:180],
            "customer_type": customer_type, "contact_person": str(values.get("contact_person", "")).strip()[:180],
            "phone": str(values.get("phone", "")).strip()[:40], "alternate_phone": str(values.get("alternate_phone", "")).strip()[:40],
            "email": email[:180], "gstin": gstin, "pan": pan, "address": str(values.get("address", "")).strip()[:1000],
            "city": str(values.get("city", "")).strip()[:100], "state": str(values.get("state", "")).strip()[:100],
            "pincode": str(values.get("pincode", "")).strip()[:10], "credit_limit": _money(values.get("credit_limit", "0")),
            "payment_terms_days": terms, "notes": str(values.get("notes", "")).strip()[:2000],
        }

    @staticmethod
    def _next_code(conn, business_id: str) -> str:
        rows = conn.execute("SELECT customer_code FROM customers WHERE business_id=?", (business_id,)).fetchall()
        highest = 0
        for row in rows:
            match = re.fullmatch(r"CUS-(\d+)", str(row["customer_code"] or ""), re.I)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"CUS-{highest + 1:06d}"

    @staticmethod
    def _assert_actor(conn, business_id: str, actor_user_id: str, permission: str) -> None:
        row = conn.execute("SELECT role FROM user_businesses WHERE user_id=? AND business_id=?", (actor_user_id, business_id)).fetchone()
        if not row or not has_permission(str(row["role"]), permission):
            raise CustomerError("Your role does not allow this customer operation.")

    @staticmethod
    def _outstanding(conn, business_id: str, customer_id: str) -> Decimal:
        rows = conn.execute("SELECT grand_total,amount_paid,status FROM bills WHERE business_id=? AND customer_id=? AND status IN ('issued','part_paid')", (business_id, customer_id)).fetchall()
        return sum((max(Decimal("0.00"), Decimal(r["grand_total"]) - Decimal(r["amount_paid"])) for r in rows), Decimal("0.00"))

    @classmethod
    def _aggregate(cls, conn, business_id: str, customer_id: str) -> dict[str, Any]:
        rows = conn.execute("SELECT grand_total,amount_paid,status FROM bills WHERE business_id=? AND customer_id=? AND status<>'cancelled'", (business_id, customer_id)).fetchall()
        sales_total = sum((Decimal(r["grand_total"]) for r in rows), Decimal("0.00"))
        collected = sum((Decimal(r["amount_paid"]) for r in rows), Decimal("0.00"))
        outstanding = cls._outstanding(conn, business_id, customer_id)
        return {"invoice_count": len(rows), "sales_total": f"{sales_total:.2f}", "collected_total": f"{collected:.2f}", "outstanding_balance": f"{outstanding:.2f}"}

    @staticmethod
    def _audit(conn, business_id: str, actor_user_id: str, action: str, entity_type: str, entity_id: str, details: dict[str, Any], now: str) -> None:
        import json
        from koshflow.core.security import new_id
        conn.execute("INSERT INTO audit_logs(audit_id,business_id,actor_user_id,action,entity_type,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (new_id("AUD"), business_id, actor_user_id, action, entity_type, entity_id, json.dumps(details, sort_keys=True), now))
