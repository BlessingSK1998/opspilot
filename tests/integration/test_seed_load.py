from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from opspilot.db.models import Customer, Invoice, Order, Product, SlaPolicy
from opspilot.db.seed import load_reference
from opspilot.db.seed_data import generate

pytestmark = pytest.mark.integration


def test_load_is_idempotent(migrated_engine: Engine, tmp_path: Path) -> None:
    generate(tmp_path)
    for _ in range(2):  # second run must not duplicate or fail
        with Session(migrated_engine) as s:
            counts = load_reference(s, tmp_path)
            s.commit()
    assert counts["orders"] == 300
    with Session(migrated_engine) as s:
        for model, n in (
            (Customer, 40),
            (Product, 120),
            (Order, 300),
            (Invoice, 200),
            (SlaPolicy, 4),
        ):
            assert s.scalar(select(func.count()).select_from(model)) == n
        assert s.scalar(select(func.count()).select_from(Customer).where(Customer.vip)) == 5
