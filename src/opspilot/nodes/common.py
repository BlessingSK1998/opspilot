"""Shared plumbing for nodes: dependency bundle and audit helper."""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from opspilot.llm.base import LLMProvider
from opspilot.schemas.llm import Usage
from opspilot.schemas.state import AuditEntry, OpsState
from opspilot.tools.sink import Backend


@dataclass
class Deps:
    provider: LLMProvider
    backend: Backend


def state_hash(state: OpsState) -> str:
    return hashlib.sha256(state.model_dump_json(exclude={"audit"}).encode()).hexdigest()[:16]


def finish(
    node: str,
    state: OpsState,
    started: float,
    summary: str,
    updates: dict[str, Any],
    usage: Usage | None = None,
) -> dict[str, Any]:
    """Attach an audit event to a node's state update."""
    entry = AuditEntry(
        node=node, input_hash=state_hash(state), output_summary=summary[:500],
        model=usage.model if usage else None, prompt_version=usage.prompt_version if usage else None,
        tokens_in=usage.tokens_in if usage else 0, tokens_out=usage.tokens_out if usage else 0,
        cost_eur=usage.cost_eur if usage else 0.0, latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
    )  # fmt: skip
    return {**updates, "audit": [entry]}


Node = Callable[[OpsState, Deps], dict[str, Any]]
