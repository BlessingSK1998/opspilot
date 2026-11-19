"""`make seed`: migrate the database, then load reference data (idempotent).

Inbound emails are NOT inserted here: they enter through the pipeline (`POST /ingest`),
so messages, runs, tasks and audit rows are produced by the real system.
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from opspilot.db.models import Customer, Invoice, Order, Product, SlaPolicy
from opspilot.db.seed_data import OUT_DIR, generate
from opspilot.db.session import get_engine, session_scope
from opspilot.schemas.enums import InvoiceStatus, OrderStatus, Priority

log = logging.getLogger(__name__)


def migrate(engine: Engine | None = None) -> None:
    cfg = Config("alembic.ini")
    if engine is None:
        command.upgrade(cfg, "head")
        return
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def _rows(base: Path, name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((base / "reference" / f"{name}.json").read_text())
    return data


def load_reference(session: Session, base: Path = OUT_DIR) -> dict[str, int]:
    """Upsert reference tables in FK order. Safe to run repeatedly."""
    for r in _rows(base, "customers"):
        session.merge(Customer(**r))
    for r in _rows(base, "products"):
        session.merge(Product(**r))
    for r in _rows(base, "sla_policies"):
        session.merge(SlaPolicy(**{**r, "priority": Priority(r["priority"])}))
    session.flush()
    for r in _rows(base, "orders"):
        session.merge(
            Order(
                **{
                    **r,
                    "order_date": date.fromisoformat(r["order_date"]),
                    "status": OrderStatus(r["status"]),
                }
            )
        )
    session.flush()
    for r in _rows(base, "invoices"):
        session.merge(
            Invoice(
                **{
                    **r,
                    "issued_date": date.fromisoformat(r["issued_date"]),
                    "due_date": date.fromisoformat(r["due_date"]),
                    "status": InvoiceStatus(r["status"]),
                }
            )
        )
    session.flush()
    return {
        name: len(_rows(base, name))
        for name in ("customers", "products", "orders", "invoices", "sla_policies")
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not (OUT_DIR / "ground_truth.jsonl").exists():
        log.info("generating synthetic data: %s", generate())
    engine = get_engine()
    migrate()
    with session_scope(engine) as session:
        counts = load_reference(session)
    n_emails = len(list((OUT_DIR / "emails").glob("*.json")))
    log.info("loaded reference data %s; %d sample emails ready to ingest", counts, n_emails)


if __name__ == "__main__":
    main()
