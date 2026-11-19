from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from dashboard.helpers import fields_table, fmt_dt, highlight, pct, reason_chips, sla_label
from streamlit.testing.v1 import AppTest

NOW = datetime.now(UTC)
VIEWS = Path(__file__).resolve().parents[2] / "dashboard" / "views"


def task(**kw: Any) -> dict[str, Any]:
    base = {"id": "t1", "run_id": "r1", "subject": "Beschwerde Lieferung", "sender": "anna@firma.de", "received_at": NOW.isoformat(),
            "category": "complaint", "priority": "P1", "status": "pending_review", "assignee_team": "Customer Service",
            "sla_due_at": (NOW + timedelta(hours=1)).isoformat(), "escalation_reasons": ["high_severity_complaint"], "confidence": 0.9, "has_draft": True}  # fmt: skip
    return base | kw


RUN = {
    "run_id": "r1", "status": "interrupted", "provider": "mock", "started_at": NOW.isoformat(), "finished_at": None,
    "message": {"id": "m", "subject": "Beschwerde Lieferung", "sender": "anna@firma.de", "sender_name": "Anna", "body": "Production line stopped!\nOrder SO-2026-00001",
                "received_at": NOW.isoformat(), "thread_message_count": 1, "attachments": [{"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 1, "text": "hello"}]},
    "task": task(), "draft": {"kind": "response", "subject": "Re: Beschwerde", "body": "Hello Anna,\n\nsorry.", "sent": False},
    "classification": {"category": "complaint", "confidence": 0.9, "rationale": "r"},
    "fields": {"order_number": {"value": "SO-2026-00001", "confidence": 0.97, "source_span": "SO-2026-00001"}},
    "missing_fields": ["company"], "validation_issues": ["order_not_found"], "warnings": ["w"], "injection_flags": ["override_instructions"],
    "reviews": [{"reviewer": "x", "action": "approve", "edits_diff": None, "reason": "ok", "created_at": NOW.isoformat()}],
    "audit": [{"node": "ingest", "input_hash": "abc", "output_summary": "ok", "model": None, "prompt_version": None, "tokens_in": 0, "tokens_out": 0, "cost_eur": 0.0, "latency_ms": 3, "ts": NOW.isoformat()},
              {"node": "classify", "input_hash": "def", "output_summary": "complaint", "model": "mock", "prompt_version": "classify.v1", "tokens_in": 10, "tokens_out": 5, "cost_eur": 0.001, "latency_ms": 7, "ts": NOW.isoformat()}],
}  # fmt: skip
METRICS = {
    "messages_processed": 10, "auto_resolved_pct": 50.0, "needs_info_pct": 20.0, "escalated_pct": 30.0, "median_processing_seconds": 0.4,
    "estimated_hours_saved": 0.7, "llm_cost_per_message_eur": 0.0, "pending_reviews": 2,
    "volume_by_category": [{"date": "2026-11-18", "category": "complaint", "count": 3}, {"date": "2026-11-19", "category": "order_request", "count": 7}],
    "priority_distribution": {"P1": 1, "P2": 3, "P3": 4, "P4": 2}, "status_distribution": {}, "sla": {"open": 5, "breached": 1, "at_risk": 2},
    "assumptions": {"manual_minutes_per_message": 6.0, "review_minutes_per_escalation": 4.0, "info_request_minutes": 2.0},
}  # fmt: skip
EVAL = {
    "name": "eval_x", "markdown": "# Report", "report": {
        "provider": "mock", "n_messages": 80,
        "classification": {"accuracy": 0.95, "macro_f1": 0.94, "labels": ["a", "b"], "confusion": [[5, 1], [0, 4]]},
        "escalation": {"recall": 1.0, "precision": 0.9, "false_negatives": []},
        "missing_info": {"precision": 0.9, "recall": 0.95}, "injection": {"attempts": 3, "resisted": 3},
        "extraction": {"complaint": {"precision": 1.0, "recall": 0.9, "f1": 0.95}},
        "latency_ms": {"classify": {"p50": 1, "p95": 2}}, "tokens_per_message": 300, "cost_per_message_eur": 0.0,
        "error_analysis": [{"id": "EM-001", "category": "order_request", "reason": "wrong sku"}],
    },
}  # fmt: skip


def fake_request(method: str, path: str, **kw: Any) -> Any:
    routes: dict[str, Any] = {
        "/health": {"status": "ok", "version": "0", "llm_provider": "mock"},
        "/metrics": METRICS,
        "/tasks": [
            task(),
            task(
                id="t2", run_id="r2", status="ready_to_send", priority="P3", escalation_reasons=[]
            ),
        ],
        "/reviews/pending": [{"task": task(), "draft": RUN["draft"]}],
        "/graph": {"mermaid": "flowchart TD\n a-->b"},
        "/eval/latest": EVAL,
        "/samples": [{"id": "EM-001", "subject": "Frage", "from_email": "a@b.de"}],
        "/samples/EM-001": {"from_email": "a@b.de", "subject": "Frage", "body": "Hi?"},
    }
    if path.startswith("/runs/"):
        return RUN
    if path.startswith("/reviews/") and method == "POST":
        return {"task_status": "ready_to_send"}
    return routes[path]


def empty_request(method: str, path: str, **kw: Any) -> Any:
    if path == "/eval/latest":
        from dashboard.api import ApiError

        raise ApiError("404: no report")
    return {
        "/metrics": {**METRICS, "messages_processed": 0},
        "/tasks": [],
        "/reviews/pending": [],
        "/graph": {"mermaid": ""},
    }.get(path, {})


def run_page(name: str, req: Any = fake_request) -> AppTest:
    with patch("dashboard.api.request", req):
        at = AppTest.from_file(str(VIEWS / f"{name}.py"), default_timeout=90).run()
    return at


@pytest.mark.parametrize(
    "page", ["overview", "inbox", "review", "inspector", "evaluation", "simulate"]
)
def test_every_page_renders_without_exception(page: str) -> None:
    at = run_page(page)
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("page", ["overview", "inbox", "review", "inspector", "evaluation"])
def test_empty_states_render_cleanly(page: str) -> None:
    at = run_page(page, empty_request)
    assert not at.exception, [e.value for e in at.exception]


def test_overview_shows_kpis() -> None:
    at = run_page("overview")
    html = " ".join(m.value for m in at.markdown)
    assert "Messages processed" in html and "Estimated hours saved" in html and "50%" in html


def test_review_page_buttons_post_decision() -> None:
    calls: list[tuple[str, str, Any]] = []

    def rec(method: str, path: str, **kw: Any) -> Any:
        calls.append((method, path, kw.get("json")))
        return fake_request(method, path, **kw)

    with patch("dashboard.api.request", rec):
        at = AppTest.from_file(str(VIEWS / "review.py"), default_timeout=90).run()
        approve = next(b for b in at.button if b.label == "Approve")
        approve.click().run()
    posts = [c for c in calls if c[0] == "POST"]
    assert posts and posts[0][1] == "/reviews/r1" and posts[0][2]["action"] == "approve"


def test_helpers() -> None:
    assert highlight("Order <SO-1> now", ["SO-1"]) == "Order &lt;<mark>SO-1</mark>&gt; now"
    assert highlight("a\nb", [""]) == "a<br>b"
    assert pct(50.0) == "50%" and pct(33.33) == "33.3%"
    assert "Legal language" in reason_chips(["legal_language"]) and "none" in reason_chips([])
    assert fmt_dt(None) == "-" and fmt_dt("2026-11-19T09:05:00+00:00") == "19 Nov 09:05"
    assert sla_label((NOW + timedelta(hours=3, minutes=5)).isoformat(), NOW).startswith("in 3h")
    assert sla_label((NOW - timedelta(hours=5)).isoformat(), NOW) == "overdue 5h"
    assert sla_label((NOW - timedelta(days=4)).isoformat(), NOW) == "overdue 4d"
    assert (
        fields_table({"items": {"value": ["a", "b"], "confidence": 0.5, "source_span": None}})[0][
            "Value"
        ]
        == "a, b"
    )
