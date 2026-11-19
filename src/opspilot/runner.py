"""Pipeline service: runs the graph, resumes interrupted runs, reports status."""

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from opspilot.graph.build import build_graph
from opspilot.logging_setup import run_id_var
from opspilot.nodes.common import Deps
from opspilot.schemas.enums import RunStatus
from opspilot.schemas.state import OpsState, RawEmail

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: str
    status: RunStatus
    state: OpsState


class Pipeline:
    def __init__(self, deps: Deps, checkpointer: BaseCheckpointSaver[Any]) -> None:
        self.deps = deps
        self.graph = build_graph(deps, checkpointer)

    @staticmethod
    def _cfg(run_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": run_id}}

    def _result(self, run_id: str) -> RunResult:
        snap = self.graph.get_state(self._cfg(run_id))
        state = OpsState.model_validate(snap.values)
        status = RunStatus.INTERRUPTED if snap.next else RunStatus.COMPLETED
        self.deps.backend.sink.finish_run(
            run_id, status.value, state.model_dump(mode="json", exclude={"raw"})
        )
        return RunResult(run_id, status, state)

    def start(self, raw: RawEmail, run_id: str | None = None) -> RunResult:
        run_id = run_id or str(uuid.uuid4())
        token = run_id_var.set(run_id)
        try:
            self.graph.invoke({"run_id": run_id, "raw": raw}, self._cfg(run_id))
            return self._result(run_id)
        except Exception:
            log.exception("run failed")
            self.deps.backend.sink.finish_run(run_id, RunStatus.FAILED.value, None)
            raise
        finally:
            run_id_var.reset(token)

    def stream(self, raw: RawEmail, run_id: str | None = None) -> Iterator[dict[str, Any]]:
        """Yield one event per completed node (used by the Simulate page)."""
        run_id = run_id or str(uuid.uuid4())
        yield {"event": "start", "run_id": run_id}
        for chunk in self.graph.stream(
            {"run_id": run_id, "raw": raw}, self._cfg(run_id), stream_mode="updates"
        ):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    yield {"event": "interrupt", "run_id": run_id}
                    continue
                audit = (update or {}).get("audit") or []
                last = audit[-1] if audit else None
                yield {"event": "node", "node": node, "summary": last.output_summary if last else "", "latency_ms": last.latency_ms if last else 0,
                       "tokens": (last.tokens_in + last.tokens_out) if last else 0}  # fmt: skip
        res = self._result(run_id)
        yield {"event": "done", "run_id": run_id, "status": res.status.value, "priority": res.state.priority.value if res.state.priority else None,
               "task_status": res.state.task_status.value if res.state.task_status else None}  # fmt: skip

    def resume(self, run_id: str, decision: dict[str, Any]) -> RunResult:
        token = run_id_var.set(run_id)
        try:
            command: Command[Any] = Command(resume=decision)
            self.graph.invoke(command, self._cfg(run_id))
            return self._result(run_id)
        finally:
            run_id_var.reset(token)

    def is_interrupted(self, run_id: str) -> bool:
        return bool(self.graph.get_state(self._cfg(run_id)).next)
