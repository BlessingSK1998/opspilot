"""Routing, human review (LangGraph interrupt), task creation, archive, audit persistence."""

import difflib
import time
from datetime import timedelta
from typing import Any

from langgraph.types import interrupt

from opspilot.nodes.common import Deps, finish
from opspilot.schemas.enums import Category, DraftKind, Priority, ReviewAction, TaskStatus
from opspilot.schemas.llm import DraftResult
from opspilot.schemas.state import OpsState
from opspilot.tools.agent_tools import GetSlaPolicyArgs, get_sla_policy

TEAM_BY_CATEGORY = {
    Category.ORDER_REQUEST: "Sales Operations", Category.INVOICE_QUERY: "Finance",
    Category.REFUND_OR_RETURN: "Customer Service", Category.COMPLAINT: "Customer Service",
    Category.SUPPLIER_DOCUMENT: "Accounts Payable", Category.ACCESS_OR_IT_REQUEST: "IT Service Desk",
    Category.GENERAL_INQUIRY: "Customer Service", Category.SPAM_OR_IRRELEVANT: "Archive",
}  # fmt: skip


# ---- routing (pure functions used as conditional edges) ---------------------
def after_ingest(state: OpsState) -> str:
    return "end" if state.duplicate else "sanitize"


def route_after_priority(state: OpsState) -> str:
    if (
        state.category is Category.SPAM_OR_IRRELEVANT
        and "prompt_injection" not in state.escalation_reasons
    ):
        return "archive"
    if state.missing_fields or state.validation_issues:
        return "draft_info_request"
    return "draft_response"


def after_draft(state: OpsState) -> str:
    return "queue_review" if state.escalation_reasons else "create_task"


# ---- nodes -------------------------------------------------------------------
def queue_review(state: OpsState, deps: Deps) -> dict[str, Any]:
    """Create the pending_review task *before* interrupting, so the queue shows it. Idempotent."""
    t0 = time.perf_counter()
    pending = state.model_copy(
        update={"task_status": TaskStatus.PENDING_REVIEW, **_task_fields(state, deps)}
    )
    task_id = deps.backend.sink.save_outcome(pending)
    sev = "critical" if state.priority is Priority.P1 else "warning"
    deps.backend.sink.notify(
        state.run_id,
        sev,
        f"[{state.priority.value if state.priority else '?'}] review needed: {', '.join(state.escalation_reasons)}",
    )
    deps.backend.sink.save_audit(state.run_id, state.audit)
    return finish("queue_review", state, t0, f"task {task_id} pending review", {"task_id": task_id, "task_status": TaskStatus.PENDING_REVIEW, **_task_fields(state, deps)})  # fmt: skip


def human_review(state: OpsState, deps: Deps) -> dict[str, Any]:
    """Pause the graph until a human approves / edits / rejects. Resume with Command(resume=decision)."""
    payload = {
        "run_id": state.run_id, "escalation_reasons": state.escalation_reasons, "priority": state.priority.value if state.priority else None,
        "draft": state.draft.model_dump() if state.draft else None,
    }  # fmt: skip
    decision: dict[str, Any] = interrupt(
        payload
    )  # first pass: raises and checkpoints; resume: returns the decision
    t0 = time.perf_counter()
    action = ReviewAction(decision["action"])
    draft = state.draft
    diff: str | None = None
    if action is ReviewAction.EDIT and draft is not None:
        new = DraftResult(
            subject=decision.get("edited_subject") or draft.subject,
            body=decision.get("edited_body") or draft.body,
        )
        diff = "\n".join(
            difflib.unified_diff(
                draft.body.splitlines(), new.body.splitlines(), "original", "edited", lineterm=""
            )
        )
        if new.subject != draft.subject:
            diff = f"subject: {draft.subject!r} -> {new.subject!r}\n{diff}"
        draft = new
    deps.backend.sink.save_review(
        state.run_id, decision["reviewer"], action.value, diff, decision.get("reason")
    )
    review = {
        "action": action.value,
        "reviewer": decision["reviewer"],
        "reason": decision.get("reason"),
        "edits_diff": diff,
    }
    return finish(
        "human_review",
        state,
        t0,
        f"{action.value} by {decision['reviewer']}",
        {"review": review, "draft": draft},
    )


def _task_fields(state: OpsState, deps: Deps) -> dict[str, Any]:
    assert (
        state.classification is not None
        and state.priority is not None
        and state.message is not None
    )
    sla = get_sla_policy(deps.backend.reference, GetSlaPolicyArgs(priority=state.priority.value))
    return {
        "assignee_team": TEAM_BY_CATEGORY[state.classification.category],
        "sla_due_at": state.message.received_at + timedelta(hours=sla["first_response_hours"]),
    }


def _final_status(state: OpsState) -> TaskStatus:
    if state.review and state.review["action"] == ReviewAction.REJECT.value:
        return TaskStatus.REJECTED
    return (
        TaskStatus.AWAITING_CUSTOMER
        if state.draft_kind is DraftKind.INFO_REQUEST
        else TaskStatus.READY_TO_SEND
    )


def create_task(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    fields = _task_fields(state, deps)
    status = _final_status(state)
    final = state.model_copy(update={"task_status": status, **fields})
    task_id = deps.backend.sink.save_outcome(final)
    return finish("create_task", state, t0, f"task {task_id}: {status.value}, {fields['assignee_team']}, SLA {fields['sla_due_at']:%Y-%m-%d %H:%M}", {"task_id": task_id, "task_status": status, **fields})  # fmt: skip


def archive(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    fields = _task_fields(state, deps)
    final = state.model_copy(update={"task_status": TaskStatus.ARCHIVED, **fields})
    task_id = deps.backend.sink.save_outcome(final)
    return finish(
        "archive",
        state,
        t0,
        "spam/irrelevant archived",
        {"task_id": task_id, "task_status": TaskStatus.ARCHIVED, **fields},
    )


def persist_audit(state: OpsState, deps: Deps) -> dict[str, Any]:
    """Final node: store the complete audit trail. (Every node already appended its own event.)"""
    t0 = time.perf_counter()
    out = finish("audit", state, t0, f"{len(state.audit)} event(s) persisted", {})
    deps.backend.sink.save_audit(state.run_id, [*state.audit, *out["audit"]])
    return out
