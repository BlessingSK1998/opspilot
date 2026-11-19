import uuid
from typing import Any

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from opspilot.db.models import (
    AuditEvent,
    Draft,
    Extraction,
    Message,
    Notification,
    ReviewDecision,
    Run,
    Task,
)
from opspilot.db.seed import load_reference
from opspilot.db.seed_data import OUT_DIR
from opspilot.db.sql_sink import SqlSink
from opspilot.llm import MockProvider
from opspilot.nodes import Deps
from opspilot.runner import Pipeline
from opspilot.schemas.enums import ReviewAction, RunStatus, TaskStatus
from opspilot.tools.reference import SqlReference
from opspilot.tools.sink import Backend
from tests.unit.conftest import make_raw, ref_rows

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def factory(migrated_engine: Engine) -> sessionmaker[Session]:
    f = sessionmaker(migrated_engine, expire_on_commit=False)
    with f() as s:
        load_reference(s, OUT_DIR)
        s.commit()
    return f


@pytest.fixture(scope="module")
def dsn(pg_url: str) -> str:
    return pg_url.replace("postgresql+psycopg://", "postgresql://", 1)


def make_pipeline(factory: sessionmaker[Session], saver: PostgresSaver) -> Pipeline:
    return Pipeline(
        Deps(MockProvider(), Backend(SqlReference(factory), SqlSink(factory, "mock"))), saver
    )


@pytest.fixture
def customer_row() -> dict[str, Any]:
    return ref_rows("customers")[0]


def test_interrupted_run_survives_restart_and_resumes(
    factory: sessionmaker[Session], dsn: str, customer_row: dict[str, Any]
) -> None:
    raw = make_raw(
        customer_row,
        "Beschwerde",
        "Our production line has been stopped since 6am. This is unacceptable!",
    )
    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()
        res = make_pipeline(factory, saver).start(raw)
    assert res.status is RunStatus.INTERRUPTED
    run_id = res.run_id

    with Session(factory.kw["bind"]) as s:  # queue state visible in the DB while paused
        task = s.scalar(select(Task).where(Task.run_id == uuid.UUID(run_id)))
        assert task is not None and task.status is TaskStatus.PENDING_REVIEW
        assert s.get(Run, task.run_id).status is RunStatus.INTERRUPTED  # type: ignore[union-attr]
        assert (
            s.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.run_id == task.run_id)
            )
            == 1
        )

    # "restart": brand-new saver, graph and pipeline objects; only Postgres carries the state
    with PostgresSaver.from_conn_string(dsn) as saver2:
        pipe2 = make_pipeline(factory, saver2)
        assert pipe2.is_interrupted(run_id)
        done = pipe2.resume(run_id, {"action": "approve", "reviewer": "ops.lead", "reason": "ok"})
    assert done.status is RunStatus.COMPLETED

    with Session(factory.kw["bind"]) as s:
        rid = uuid.UUID(run_id)
        task = s.scalar(select(Task).where(Task.run_id == rid))
        assert (
            task is not None
            and task.status is TaskStatus.READY_TO_SEND
            and task.assignee_team == "Customer Service"
        )
        rd = s.scalar(select(ReviewDecision).where(ReviewDecision.run_id == rid))
        assert rd is not None and rd.action is ReviewAction.APPROVE and rd.reviewer == "ops.lead"
        nodes = [
            e.node
            for e in s.scalars(
                select(AuditEvent).where(AuditEvent.run_id == rid).order_by(AuditEvent.id)
            )
        ]
        assert nodes[0] == "ingest" and "human_review" in nodes and nodes[-1] == "audit"
        assert (
            s.scalar(select(func.count()).select_from(Extraction).where(Extraction.run_id == rid))
            == 1
        )
        assert s.scalar(select(func.count()).select_from(Draft).where(Draft.run_id == rid)) == 1
        draft = s.scalar(select(Draft).where(Draft.run_id == rid))
        assert draft is not None and draft.sent is False  # drafts are never auto-sent


def test_duplicate_message_is_idempotent_in_db(
    factory: sessionmaker[Session], dsn: str, customer_row: dict[str, Any]
) -> None:
    raw = make_raw(customer_row, "Frage", "Could you send us your current product catalogue?")
    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()
        pipe = make_pipeline(factory, saver)
        first, second = pipe.start(raw), pipe.start(raw)
    assert first.state.task_id and second.state.duplicate
    with Session(factory.kw["bind"]) as s:
        assert (
            s.scalar(select(func.count()).select_from(Message).where(Message.subject == "Frage"))
            == 1
        )
        assert s.get(Run, uuid.UUID(second.run_id)).status is RunStatus.COMPLETED  # type: ignore[union-attr]


def test_non_escalated_run_completes_in_db(
    factory: sessionmaker[Session], dsn: str, customer_row: dict[str, Any]
) -> None:
    sku = min(ref_rows("products"), key=lambda p: p["unit_price"])["sku"]
    raw = make_raw(
        customer_row,
        "Bestellung",
        f"We would like to place an order:\n- 5 x {sku} (x)\nDelivery address: Hafenstraße 1, 20457 Hamburg\nRequested delivery: 2030-01-15",
    )
    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()
        res = make_pipeline(factory, saver).start(raw)
    assert res.status is RunStatus.COMPLETED
    with Session(factory.kw["bind"]) as s:
        t = s.scalar(select(Task).where(Task.run_id == uuid.UUID(res.run_id)))
        assert t is not None and t.status is TaskStatus.READY_TO_SEND
