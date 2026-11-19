"""LangGraph assembly: nodes, conditional edges, human-in-the-loop interrupt."""

from functools import partial
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from opspilot.nodes import Deps, assess_priority, classify, extract, ingest, sanitize, validate
from opspilot.nodes.drafts import draft_info_request, draft_response
from opspilot.nodes.tasking import (
    after_draft,
    after_ingest,
    archive,
    create_task,
    human_review,
    persist_audit,
    queue_review,
    route_after_priority,
)
from opspilot.schemas.state import OpsState

NODES = {
    "ingest": ingest, "sanitize": sanitize, "classify": classify, "extract": extract, "validate": validate,
    "assess_priority": assess_priority, "draft_response": draft_response, "draft_info_request": draft_info_request,
    "queue_review": queue_review, "human_review": human_review, "create_task": create_task, "archive": archive,
    "audit": persist_audit,
}  # fmt: skip


def build_graph(
    deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    g = StateGraph(OpsState)
    for name, fn in NODES.items():
        g.add_node(name, partial(fn, deps=deps))
    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", after_ingest, {"sanitize": "sanitize", "end": END})
    for a, b in (
        ("sanitize", "classify"),
        ("classify", "extract"),
        ("extract", "validate"),
        ("validate", "assess_priority"),
    ):
        g.add_edge(a, b)
    g.add_conditional_edges(
        "assess_priority",
        route_after_priority,
        {
            "archive": "archive",
            "draft_info_request": "draft_info_request",
            "draft_response": "draft_response",
        },
    )
    for d in ("draft_response", "draft_info_request"):
        g.add_conditional_edges(
            d, after_draft, {"queue_review": "queue_review", "create_task": "create_task"}
        )
    g.add_edge("queue_review", "human_review")
    g.add_edge("human_review", "create_task")
    g.add_edge("create_task", "audit")
    g.add_edge("archive", "audit")
    g.add_edge("audit", END)
    return g.compile(checkpointer=checkpointer)


MERMAID = """flowchart TD
    START([inbound email]) --> ingest
    ingest -->|duplicate| END([stop])
    ingest --> sanitize --> classify --> extract --> validate --> assess_priority
    assess_priority -->|spam| archive --> audit
    assess_priority -->|missing info or issues| draft_info_request
    assess_priority -->|complete| draft_response
    draft_info_request -->|no escalation| create_task
    draft_response -->|no escalation| create_task
    draft_info_request -->|escalation| queue_review
    draft_response -->|escalation| queue_review
    queue_review --> human_review{{human_review: interrupt}}
    human_review -->|approve / edit / reject| create_task
    create_task --> audit --> DONE([end])
"""
