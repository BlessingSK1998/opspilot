"""Postgres implementation of the write-side `Sink` port."""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from opspilot.db.models import (
    Attachment,
    AuditEvent,
    Draft,
    Extraction,
    Message,
    Notification,
    ReviewDecision,
    Run,
    Task,
)
from opspilot.schemas.enums import ReviewAction, RunStatus
from opspilot.schemas.state import AuditEntry, NormalizedMessage, OpsState

log = logging.getLogger(__name__)


class SqlSink:
    def __init__(
        self, factory: sessionmaker[Session], provider_name: str, slack_webhook: str | None = None
    ) -> None:
        self._factory = factory
        self._provider = provider_name
        self._slack = slack_webhook

    def register_message(self, msg: NormalizedMessage, run_id: str) -> str | None:
        with self._factory() as s:
            existing = s.scalar(select(Message).where(Message.content_hash == msg.content_hash))
            if existing is None:
                m = Message(
                    external_id=msg.external_id, thread_id=msg.thread_id, sender=msg.sender, sender_name=msg.sender_name,
                    subject=msg.subject, body=msg.body, received_at=msg.received_at,
                    thread_message_count=msg.thread_message_count, content_hash=msg.content_hash,
                )  # fmt: skip
                m.attachments = [
                    Attachment(
                        filename=a["filename"],
                        content_type=a["content_type"],
                        size_bytes=a["size_bytes"],
                        extracted_text=a["text"] or None,
                    )
                    for a in msg.attachments
                ]
                s.add(m)
                try:
                    s.flush()
                except IntegrityError:  # lost a race with an identical concurrent message
                    s.rollback()
                    existing = s.scalar(
                        select(Message).where(Message.content_hash == msg.content_hash)
                    )
            if existing is not None:
                s.add(
                    Run(
                        id=uuid.UUID(run_id),
                        message_id=existing.id,
                        status=RunStatus.COMPLETED,
                        provider=self._provider,
                        finished_at=datetime.now(UTC),
                        final_state={"duplicate": True},
                    )
                )
                s.commit()
                return None
            s.add(
                Run(
                    id=uuid.UUID(run_id),
                    message_id=m.id,
                    status=RunStatus.RUNNING,
                    provider=self._provider,
                )
            )
            s.commit()
            return str(m.id)

    def save_outcome(self, state: OpsState) -> str:
        assert (
            state.classification
            and state.priority
            and state.task_status
            and state.sla_due_at
            and state.message_id
        )
        rid = uuid.UUID(state.run_id)
        with self._factory() as s:
            ex = s.scalar(select(Extraction).where(Extraction.run_id == rid)) or Extraction(
                run_id=rid
            )
            ex.category, ex.confidence, ex.rationale = (
                state.classification.category,
                state.classification.confidence,
                state.classification.rationale,
            )
            ex.fields, ex.missing_fields, ex.validation_issues = (
                state.fields,
                state.missing_fields,
                state.validation_issues,
            )
            s.add(ex)
            draft_id: uuid.UUID | None = None
            if state.draft and state.draft_kind:
                d = s.scalar(select(Draft).where(Draft.run_id == rid)) or Draft(run_id=rid)
                d.kind, d.subject, d.body = state.draft_kind, state.draft.subject, state.draft.body
                d.prompt_version = state.audit[-1].prompt_version if state.audit else None
                s.add(d)
                s.flush()
                draft_id = d.id
            t = s.scalar(select(Task).where(Task.run_id == rid)) or Task(
                run_id=rid, message_id=uuid.UUID(state.message_id)
            )
            t.draft_id, t.category, t.priority, t.status = (
                draft_id,
                state.classification.category,
                state.priority,
                state.task_status,
            )
            t.assignee_team, t.sla_due_at, t.escalation_reasons = (
                state.assignee_team or "Customer Service",
                state.sla_due_at,
                state.escalation_reasons,
            )
            s.add(t)
            s.commit()
            return str(t.id)

    def notify(self, run_id: str | None, severity: str, message: str) -> None:
        with self._factory() as s:
            s.add(
                Notification(
                    run_id=uuid.UUID(run_id) if run_id else None,
                    channel="db",
                    severity=severity,
                    message=message,
                )
            )
            s.commit()
        log.info("notify_human", extra={"extra_fields": {"severity": severity, "message": message}})
        if self._slack:
            try:
                httpx.post(
                    self._slack, json={"text": f"OpsPilot [{severity}] {message}"}, timeout=3.0
                )
            except httpx.HTTPError:
                log.warning("slack webhook failed")

    def save_audit(self, run_id: str, events: list[AuditEntry]) -> None:
        rid = uuid.UUID(run_id)
        with self._factory() as s:
            s.execute(delete(AuditEvent).where(AuditEvent.run_id == rid))
            for e in events:
                s.add(AuditEvent(
                    run_id=rid, node=e.node, input_hash=e.input_hash, output_summary=e.output_summary, model=e.model,
                    prompt_version=e.prompt_version, tokens_in=e.tokens_in, tokens_out=e.tokens_out,
                    cost_eur=Decimal(str(e.cost_eur)), latency_ms=e.latency_ms, ts=e.ts,
                ))  # fmt: skip
            s.commit()

    def save_review(
        self, run_id: str, reviewer: str, action: str, edits_diff: str | None, reason: str | None
    ) -> None:
        with self._factory() as s:
            s.add(
                ReviewDecision(
                    run_id=uuid.UUID(run_id),
                    reviewer=reviewer,
                    action=ReviewAction(action),
                    edits_diff=edits_diff,
                    reason=reason,
                )
            )
            s.commit()

    def finish_run(self, run_id: str, status: str, final_state: dict[str, Any] | None) -> None:
        with self._factory() as s:
            run = s.get(Run, uuid.UUID(run_id))
            if run is not None:
                run.status = RunStatus(status)
                run.final_state = final_state
                run.finished_at = (
                    datetime.now(UTC) if status != RunStatus.INTERRUPTED.value else None
                )
                s.commit()
