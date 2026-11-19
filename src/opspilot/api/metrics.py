"""KPI queries. Definitions are documented in docs/PROCESS_MAP.md."""

import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opspilot.api.models import Metrics
from opspilot.db.models import AuditEvent, Message, ReviewDecision, Run, Task
from opspilot.schemas.enums import RunStatus, TaskStatus

# Planning assumptions (stated openly in the README). Manual figures are Northwind's, not measured here.
MANUAL_MINUTES_PER_MESSAGE = 6.0  # reading, classifying, looking up, routing, drafting by hand
REVIEW_MINUTES_PER_ESCALATION = 4.0  # human time still spent on an escalated case
INFO_REQUEST_MINUTES = 2.0  # human time to check and send an info-request draft
AT_RISK_WINDOW = timedelta(hours=2)
CLOSED = {TaskStatus.CLOSED, TaskStatus.ARCHIVED, TaskStatus.REJECTED}


def compute_metrics(s: Session, now: datetime | None = None) -> Metrics:
    now = now or datetime.now(UTC)
    tasks = list(s.scalars(select(Task)))
    n = len(tasks)
    reviewed = set(s.scalars(select(ReviewDecision.run_id)))

    def pct(x: int) -> float:
        return round(100 * x / n, 1) if n else 0.0

    auto = sum(
        1
        for t in tasks
        if t.status is TaskStatus.ARCHIVED
        or (t.status is TaskStatus.READY_TO_SEND and t.run_id not in reviewed)
    )
    info = sum(1 for t in tasks if t.status is TaskStatus.AWAITING_CUSTOMER)
    esc = sum(1 for t in tasks if t.escalation_reasons)

    runs = list(
        s.scalars(
            select(Run).where(Run.status == RunStatus.COMPLETED, Run.finished_at.is_not(None))
        )
    )
    secs = [
        (r.finished_at - r.started_at).total_seconds()
        for r in runs
        if r.finished_at and not (r.final_state or {}).get("duplicate")
    ]
    cost = float(s.scalar(select(func.coalesce(func.sum(AuditEvent.cost_eur), 0))) or 0)

    human_min = (
        esc * REVIEW_MINUTES_PER_ESCALATION
        + (
            info
            - sum(
                1
                for t in tasks
                if t.status is TaskStatus.AWAITING_CUSTOMER and t.escalation_reasons
            )
        )
        * INFO_REQUEST_MINUTES
    )
    saved = max(0.0, (n * MANUAL_MINUTES_PER_MESSAGE - human_min) / 60)

    by_cat: dict[tuple[str, str], int] = {}
    for received, cat in s.execute(
        select(Message.received_at, Task.category).join(Task, Task.message_id == Message.id)
    ):
        key = (received.date().isoformat(), cat.value)
        by_cat[key] = by_cat.get(key, 0) + 1

    open_tasks = [t for t in tasks if t.status not in CLOSED]
    sla = {
        "open": len(open_tasks),
        "breached": sum(1 for t in open_tasks if t.sla_due_at < now),
        "at_risk": sum(1 for t in open_tasks if now <= t.sla_due_at < now + AT_RISK_WINDOW),
    }
    return Metrics(
        messages_processed=n, auto_resolved_pct=pct(auto), needs_info_pct=pct(info), escalated_pct=pct(esc),
        median_processing_seconds=round(statistics.median(secs), 2) if secs else None,
        estimated_hours_saved=round(saved, 1), llm_cost_per_message_eur=round(cost / n, 6) if n else 0.0,
        pending_reviews=sum(1 for t in tasks if t.status is TaskStatus.PENDING_REVIEW),
        volume_by_category=[{"date": d, "category": c, "count": v} for (d, c), v in sorted(by_cat.items())],
        priority_distribution={p: sum(1 for t in tasks if t.priority.value == p) for p in ("P1", "P2", "P3", "P4")},
        status_distribution={st.value: sum(1 for t in tasks if t.status is st) for st in TaskStatus},
        sla=sla,
        assumptions={"manual_minutes_per_message": MANUAL_MINUTES_PER_MESSAGE, "review_minutes_per_escalation": REVIEW_MINUTES_PER_ESCALATION, "info_request_minutes": INFO_REQUEST_MINUTES},
    )  # fmt: skip
