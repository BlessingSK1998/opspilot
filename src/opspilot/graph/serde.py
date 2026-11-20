"""Checkpoint serializer that explicitly allow-lists OpsPilot's own state types, so resume keeps
working when LangGraph blocks deserialisation of unregistered types (it warns this is coming)."""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import dict_row

ALLOWED: list[tuple[str, str]] = [
    ("opspilot.schemas.state", "RawEmail"), ("opspilot.schemas.state", "AttachmentIn"),
    ("opspilot.schemas.state", "NormalizedMessage"), ("opspilot.schemas.state", "AuditEntry"),
    ("opspilot.schemas.state", "OpsState"),
    ("opspilot.schemas.llm", "ClassificationResult"), ("opspilot.schemas.llm", "RiskAssessment"),
    ("opspilot.schemas.llm", "DraftResult"), ("opspilot.schemas.llm", "Usage"),
    ("opspilot.schemas.enums", "Category"), ("opspilot.schemas.enums", "Priority"),
    ("opspilot.schemas.enums", "TaskStatus"), ("opspilot.schemas.enums", "DraftKind"),
    ("opspilot.schemas.enums", "ReviewAction"), ("opspilot.schemas.enums", "Profile"),
]  # fmt: skip


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED)


@contextmanager
def postgres_saver(dsn: str) -> Iterator[PostgresSaver]:
    """A PostgresSaver (own connection) using the allow-listed serializer. Used by tests and scripts."""
    with Connection.connect(
        dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as conn:
        saver = PostgresSaver(conn, serde=make_serde())
        saver.setup()
        yield saver
