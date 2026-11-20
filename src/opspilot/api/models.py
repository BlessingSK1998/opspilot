"""Request / response models for the HTTP API (all fully typed for clean OpenAPI)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from opspilot.schemas.enums import Category, Priority, ReviewAction, RunStatus, TaskStatus
from opspilot.schemas.state import RawEmail


class IngestResponse(BaseModel):
    run_id: str
    status: RunStatus
    duplicate: bool = False
    category: Category | None = None
    priority: Priority | None = None
    task_id: str | None = None
    task_status: TaskStatus | None = None
    escalation_reasons: list[str] = Field(default_factory=list)


class BatchIngestRequest(BaseModel):
    emails: list[RawEmail] = Field(min_length=1, max_length=500)


class BatchIngestResponse(BaseModel):
    results: list[IngestResponse]


class TaskOut(BaseModel):
    id: str
    run_id: str
    subject: str
    sender: str
    received_at: datetime
    category: Category
    priority: Priority
    status: TaskStatus
    assignee_team: str
    sla_due_at: datetime
    escalation_reasons: list[str]
    confidence: float | None = None
    has_draft: bool = False
    profile: Literal["ops", "personal"] = "ops"


class TaskPatch(BaseModel):
    status: Literal["closed", "ready_to_send", "awaiting_customer"] | None = None
    assignee_team: str | None = None


class AuditOut(BaseModel):
    node: str
    input_hash: str
    output_summary: str
    model: str | None
    prompt_version: str | None
    tokens_in: int
    tokens_out: int
    cost_eur: float
    latency_ms: int
    ts: datetime


class DraftOut(BaseModel):
    kind: str
    subject: str
    body: str
    sent: bool


class ReviewOut(BaseModel):
    reviewer: str
    action: ReviewAction
    edits_diff: str | None
    reason: str | None
    created_at: datetime


class MessageOut(BaseModel):
    id: str
    subject: str
    sender: str
    sender_name: str | None
    body: str
    received_at: datetime
    thread_message_count: int
    attachments: list[dict[str, Any]]


class RunDetail(BaseModel):
    run_id: str
    status: RunStatus
    provider: str
    started_at: datetime
    finished_at: datetime | None
    message: MessageOut
    task: TaskOut | None
    draft: DraftOut | None
    classification: dict[str, Any] | None
    fields: dict[str, dict[str, Any]]
    missing_fields: list[str]
    validation_issues: list[str]
    warnings: list[str]
    injection_flags: list[str]
    reviews: list[ReviewOut]
    audit: list[AuditOut]


class ReviewRequest(BaseModel):
    action: ReviewAction
    reviewer: str = Field(min_length=1, max_length=120)
    reason: str | None = None
    edited_subject: str | None = None
    edited_body: str | None = None


class PendingReview(BaseModel):
    task: TaskOut
    draft: DraftOut | None


class Metrics(BaseModel):
    messages_processed: int
    auto_resolved_pct: float
    needs_info_pct: float
    escalated_pct: float
    median_processing_seconds: float | None
    estimated_hours_saved: float
    llm_cost_per_message_eur: float
    pending_reviews: int
    volume_by_category: list[dict[str, Any]]
    priority_distribution: dict[str, int]
    status_distribution: dict[str, int]
    sla: dict[str, int]
    assumptions: dict[str, float]


class SampleOut(BaseModel):
    id: str
    subject: str
    from_email: str


class HealthResponse(BaseModel):
    status: str
    version: str
    llm_provider: str
