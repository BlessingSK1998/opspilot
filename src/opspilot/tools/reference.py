"""Read-only access to Northwind's reference data (stand-in for the ERP)."""

import json
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from opspilot.db.models import Customer, Invoice, Order, Product, SlaPolicy


class Reference(Protocol):
    def find_customer(
        self, *, name: str | None = None, email: str | None = None
    ) -> dict[str, Any] | None: ...
    def get_order(self, order_number: str) -> dict[str, Any] | None: ...
    def get_invoice(self, invoice_number: str) -> dict[str, Any] | None: ...
    def get_product(self, sku: str) -> dict[str, Any] | None: ...
    def get_sla(self, priority: str) -> dict[str, Any]: ...


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


class MemoryReference:
    """Backed by the seed JSON files; used by tests and the offline eval."""

    def __init__(self, base: Path) -> None:
        def load(n: str) -> list[dict[str, Any]]:
            data: list[dict[str, Any]] = json.loads((base / "reference" / f"{n}.json").read_text())
            return data

        self._customers = load("customers")
        self._orders = {o["order_number"]: o for o in load("orders")}
        self._invoices = {i["invoice_number"]: i for i in load("invoices")}
        self._products = {p["sku"]: p for p in load("products")}
        self._sla = {s["priority"]: s for s in load("sla_policies")}

    def find_customer(
        self, *, name: str | None = None, email: str | None = None
    ) -> dict[str, Any] | None:
        if name:
            for c in self._customers:
                if c["name"].lower() == name.strip().lower():
                    return c
        if email:
            for c in self._customers:
                if c["contact_email"].lower() == email.lower():
                    return c
            for c in self._customers:
                if c["email_domain"] == _domain(email):
                    return c
        return None

    def get_order(self, order_number: str) -> dict[str, Any] | None:
        return self._orders.get(order_number)

    def get_invoice(self, invoice_number: str) -> dict[str, Any] | None:
        return self._invoices.get(invoice_number)

    def get_product(self, sku: str) -> dict[str, Any] | None:
        return self._products.get(sku)

    def get_sla(self, priority: str) -> dict[str, Any]:
        return self._sla[priority]


def _row(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        out[col.name] = (
            v.value
            if hasattr(v, "value")
            else (float(v) if col.type.python_type.__name__ == "Decimal" else v)
        )
    return out


class SqlReference:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def find_customer(
        self, *, name: str | None = None, email: str | None = None
    ) -> dict[str, Any] | None:
        from sqlalchemy import func, select

        with self._factory() as s:
            if name:
                c = s.scalar(
                    select(Customer).where(func.lower(Customer.name) == name.strip().lower())
                )
                if c:
                    return _row(c)
            if email:
                c = s.scalar(
                    select(Customer).where(func.lower(Customer.contact_email) == email.lower())
                ) or s.scalar(select(Customer).where(Customer.email_domain == _domain(email)))
                if c:
                    return _row(c)
        return None

    def _get(self, model: type[Any], key: str) -> dict[str, Any] | None:
        with self._factory() as s:
            obj = s.get(model, key)
            return _row(obj) if obj else None

    def get_order(self, order_number: str) -> dict[str, Any] | None:
        return self._get(Order, order_number)

    def get_invoice(self, invoice_number: str) -> dict[str, Any] | None:
        return self._get(Invoice, invoice_number)

    def get_product(self, sku: str) -> dict[str, Any] | None:
        return self._get(Product, sku)

    def get_sla(self, priority: str) -> dict[str, Any]:
        from opspilot.schemas.enums import Priority

        with self._factory() as s:
            obj = s.get(SlaPolicy, Priority(priority))
            assert obj is not None, f"missing SLA policy {priority}"
            return _row(obj)
