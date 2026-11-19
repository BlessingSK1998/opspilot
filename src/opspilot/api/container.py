"""Wiring: engine, session factory, checkpointer, pipeline. One instance per process."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from opspilot.db.sql_sink import SqlSink
from opspilot.graph.serde import make_serde
from opspilot.llm import get_provider
from opspilot.nodes.common import Deps
from opspilot.runner import Pipeline
from opspilot.settings import Settings
from opspilot.tools.reference import SqlReference
from opspilot.tools.sink import Backend


@dataclass
class Container:
    settings: Settings
    engine: Engine
    factory: sessionmaker[Session]
    pipeline: Pipeline
    _closer: AbstractContextManager[Any] | None = None

    def close(self) -> None:
        self.engine.dispose()
        if self._closer:
            self._closer.__exit__(None, None, None)


def build_container(
    settings: Settings,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    engine: Engine | None = None,
) -> Container:
    engine = engine or create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    closer: Any = None
    if checkpointer is None:
        dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        pool: ConnectionPool[Any] = ConnectionPool(
            dsn,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            max_size=10,
            open=True,
        )
        saver = PostgresSaver(pool, serde=make_serde())
        saver.setup()
        checkpointer, closer = saver, pool
    provider = get_provider(settings)
    deps = Deps(
        provider,
        Backend(
            SqlReference(factory),
            SqlSink(factory, provider.name, settings.slack_webhook_url or None),
        ),
    )
    c = Container(settings, engine, factory, Pipeline(deps, checkpointer))
    if closer is not None:
        c._closer = _PoolCloser(closer)
    return c


class _PoolCloser:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    def __enter__(self) -> None: ...

    def __exit__(self, *_: object) -> None:
        self.pool.close()
