"""Alembic environment. The URL comes from settings unless a connection is injected."""

from alembic import context
from sqlalchemy import create_engine

from opspilot.db.models import Base
from opspilot.settings import get_settings

target_metadata = Base.metadata


def run_migrations_online() -> None:
    injected = context.config.attributes.get("connection")
    if injected is not None:
        context.configure(connection=injected, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
