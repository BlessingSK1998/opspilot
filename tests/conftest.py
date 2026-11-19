"""Shared fixtures. Integration tests use an embedded real Postgres (pgserver) unless
TEST_DATABASE_URL points at one (CI / docker compose)."""

import os
import tempfile
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        yield explicit
        return
    import pgserver

    server = pgserver.get_server(tempfile.mkdtemp(prefix="opspilot-pg-"), cleanup_mode="stop")
    yield server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    server.cleanup()


@pytest.fixture(scope="session")
def migrated_engine(pg_url: str) -> Iterator[Engine]:
    engine = create_engine(pg_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    yield engine
    engine.dispose()
