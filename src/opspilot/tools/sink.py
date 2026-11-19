"""Write-side port. `SqlSink` (db/sql_sink.py) persists to Postgres; `MemorySink` keeps everything
in memory (unit tests and the offline eval)."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from opspilot.schemas.state import AuditEntry, NormalizedMessage, OpsState


class Sink(Protocol):
    def register_message(self, msg: NormalizedMessage, run_id: str) -> str | None:
        """Persist message + run row. Returns the message id, or None if identical content was seen."""

    def save_outcome(self, state: OpsState) -> str:
        """Upsert extraction, draft and task for a run; returns the task id."""

    def notify(self, run_id: str | None, severity: str, message: str) -> None: ...

    def save_audit(self, run_id: str, events: list[AuditEntry]) -> None:
        """Replace the stored audit trail for the run."""

    def save_review(
        self, run_id: str, reviewer: str, action: str, edits_diff: str | None, reason: str | None
    ) -> None: ...

    def finish_run(self, run_id: str, status: str, final_state: dict[str, Any] | None) -> None: ...


@dataclass
class MemorySink:
    hashes: dict[str, str] = field(default_factory=dict)
    outcomes: dict[str, OpsState] = field(default_factory=dict)  # task_id -> state snapshot
    task_by_run: dict[str, str] = field(default_factory=dict)
    notifications: list[tuple[str | None, str, str]] = field(default_factory=list)
    audits: dict[str, list[AuditEntry]] = field(default_factory=dict)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    runs: dict[str, str] = field(default_factory=dict)

    def register_message(self, msg: NormalizedMessage, run_id: str) -> str | None:
        self.runs[run_id] = "running"
        if msg.content_hash in self.hashes:
            self.runs[run_id] = "completed"
            return None
        mid = f"msg-{len(self.hashes) + 1}"
        self.hashes[msg.content_hash] = mid
        return mid

    def save_outcome(self, state: OpsState) -> str:
        task_id = self.task_by_run.setdefault(state.run_id, f"task-{len(self.task_by_run) + 1}")
        self.outcomes[task_id] = state
        return task_id

    def notify(self, run_id: str | None, severity: str, message: str) -> None:
        self.notifications.append((run_id, severity, message))

    def save_audit(self, run_id: str, events: list[AuditEntry]) -> None:
        self.audits[run_id] = list(events)

    def save_review(
        self, run_id: str, reviewer: str, action: str, edits_diff: str | None, reason: str | None
    ) -> None:
        self.reviews.append(
            {
                "run_id": run_id,
                "reviewer": reviewer,
                "action": action,
                "edits_diff": edits_diff,
                "reason": reason,
            }
        )

    def finish_run(self, run_id: str, status: str, final_state: dict[str, Any] | None) -> None:
        self.runs[run_id] = status


@dataclass
class Backend:
    reference: Any
    sink: Any
