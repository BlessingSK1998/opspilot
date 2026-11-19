"""Typed graph state shared by every node."""

import operator
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from opspilot.schemas.enums import Category, DraftKind, Priority, TaskStatus
from opspilot.schemas.llm import ClassificationResult, DraftResult, RiskAssessment


class AttachmentIn(BaseModel):
    filename: str
    content_type: str
    content_b64: str


class RawEmail(BaseModel):
    """Inbound email as accepted by `POST /ingest`."""

    message_id: str | None = None
    thread_id: str | None = None
    from_name: str | None = None
    from_email: str
    to: str = "ops@northwind-supply.de"
    subject: str
    body: str
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    thread_message_count: int = 1
    attachments: list[AttachmentIn] = Field(default_factory=list)


class NormalizedMessage(BaseModel):
    external_id: str | None
    thread_id: str
    sender: str
    sender_name: str | None
    subject: str
    body: str
    received_at: datetime
    thread_message_count: int
    content_hash: str
    attachments: list[dict[str, Any]] = Field(
        default_factory=list
    )  # filename, content_type, size_bytes, text


class AuditEntry(BaseModel):
    node: str
    input_hash: str
    output_summary: str
    model: str | None = None
    prompt_version: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_eur: float = 0.0
    latency_ms: int = 0
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OpsState(BaseModel):
    run_id: str
    raw: RawEmail | None = None

    # ingest
    message: NormalizedMessage | None = None
    message_id: str | None = None
    duplicate: bool = False
    email_text: str = ""

    # sanitize
    safe_text: str = ""
    pii_map: dict[str, str] = Field(default_factory=dict)
    injection_flags: list[str] = Field(default_factory=list)

    # classify / extract
    classification: ClassificationResult | None = None
    fields: dict[str, dict[str, Any]] = Field(
        default_factory=dict
    )  # name -> {value, confidence, source_span}

    # validate
    missing_fields: list[str] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    records: dict[str, Any] = Field(
        default_factory=dict
    )  # customer / order / invoice found in the DB
    risk_amount: float | None = None

    # priority
    risk: RiskAssessment | None = None
    priority: Priority | None = None
    escalation_reasons: list[str] = Field(default_factory=list)

    # routing / outputs
    route: str | None = None
    draft_kind: DraftKind | None = None
    draft: DraftResult | None = None
    review: dict[str, Any] | None = None
    task_id: str | None = None
    assignee_team: str | None = None
    sla_due_at: datetime | None = None
    task_status: TaskStatus | None = None

    audit: Annotated[list[AuditEntry], operator.add] = Field(default_factory=list)

    @property
    def category(self) -> Category | None:
        return self.classification.category if self.classification else None

    def flat_fields(self) -> dict[str, Any]:
        return {k: v["value"] for k, v in self.fields.items() if v.get("value") is not None}
