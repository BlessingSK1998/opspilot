"""Write-side port. `SqlSink` persists to Postgres; `MemorySink` keeps everything in lists
(unit tests and the offline eval)."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from opspilot.schemas.state import AuditEntry, NormalizedMessage


class Sink(Protocol):
    def register_message(self, msg: NormalizedMessage) -> str | None:
        """Persist the message. Returns its id, or None if identical content was seen before."""

    def save_outcome(self, state: Any) -> str:
        """Persist extraction + draft + task for a finished run; returns the task id."""

    def notify(self, run_id: str | None, severity: str, message: str) -> None: ...

    def save_audit(self, run_id: str, events: list[AuditEntry]) -> None: ...

    def save_review(
        self, run_id: str, reviewer: str, action: str, edits_diff: str | None, reason: str | None
    ) -> None: ...


@dataclass
class MemorySink:
    hashes: dict[str, str] = field(default_factory=dict)
    outcomes: dict[str, Any] = field(default_factory=dict)  # task_id -> OpsState snapshot
    notifications: list[tuple[str | None, str, str]] = field(default_factory=list)
    audits: dict[str, list[AuditEntry]] = field(default_factory=dict)
    reviews: list[dict[str, Any]] = field(default_factory=list)

    def register_message(self, msg: NormalizedMessage) -> str | None:
        if msg.content_hash in self.hashes:
            return None
        mid = f"msg-{len(self.hashes) + 1}"
        self.hashes[msg.content_hash] = mid
        return mid

    def save_outcome(self, state: Any) -> str:
        task_id = f"task-{len(self.outcomes) + 1}"
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


@dataclass
class Backend:
    reference: Any
    sink: Any
