import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

pytestmark = pytest.mark.integration

EXPECTED = {
    "messages",
    "attachments",
    "runs",
    "extractions",
    "tasks",
    "drafts",
    "review_decisions",
    "audit_events",
    "notifications",
    "customers",
    "orders",
    "invoices",
    "products",
    "sla_policies",
}


def test_all_tables_created(migrated_engine: Engine) -> None:
    assert set(inspect(migrated_engine).get_table_names()) >= EXPECTED


def test_content_hash_is_unique(migrated_engine: Engine) -> None:
    uniques = inspect(migrated_engine).get_unique_constraints("messages")
    assert any(u["column_names"] == ["content_hash"] for u in uniques)


def test_downgrade_then_upgrade(migrated_engine: Engine) -> None:
    cfg = Config("alembic.ini")
    with migrated_engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    assert "tasks" not in inspect(migrated_engine).get_table_names()
    with migrated_engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    assert "tasks" in inspect(migrated_engine).get_table_names()
