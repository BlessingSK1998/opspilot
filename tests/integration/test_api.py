import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from opspilot.api.app import create_app
from opspilot.api.container import build_container
from opspilot.db.seed import load_reference
from opspilot.db.seed_data import OUT_DIR
from opspilot.graph.serde import make_serde
from opspilot.settings import Settings
from tests.unit.conftest import make_raw, ref_rows

pytestmark = pytest.mark.integration
H = {"X-API-Key": "test-key"}


@pytest.fixture(scope="module")
def client(migrated_engine: Engine, pg_url: str) -> Iterator[TestClient]:
    with Session(migrated_engine) as s:
        load_reference(s, OUT_DIR)
        s.commit()
    settings = Settings(_env_file=None, database_url=pg_url, api_key="test-key")  # type: ignore[call-arg,arg-type]
    app = create_app(
        lambda st: build_container(st, InMemorySaver(serde=make_serde()), migrated_engine), settings
    )
    with TestClient(app) as c:
        yield c


def payload(subject: str, body: str, idx: int = 0) -> dict[str, Any]:
    cust = ref_rows("customers")[idx]
    return json.loads(make_raw(cust, subject, body).model_dump_json())


ESCALATING = "Our production line has been stopped since this morning. This is unacceptable!"


def test_health_is_open_but_everything_else_needs_key(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/tasks").status_code == 401
    assert client.get("/tasks", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/tasks", headers=H).status_code == 200


def test_root_redirects_to_docs(client: TestClient) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/docs"


def test_openapi_is_typed(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in (
        "/ingest",
        "/ingest/batch",
        "/runs/{run_id}",
        "/tasks",
        "/tasks/{task_id}",
        "/reviews/{run_id}",
        "/metrics",
        "/health",
    ):
        assert path in spec["paths"], path
    assert (
        "IngestResponse" in spec["components"]["schemas"]
        and "Metrics" in spec["components"]["schemas"]
    )


def test_ingest_json_non_escalated_and_run_detail(client: TestClient) -> None:
    sku = min(ref_rows("products"), key=lambda p: p["unit_price"])["sku"]
    body = f"We would like to place an order:\n- 5 x {sku} (x)\nDelivery address: Hafenstraße 1, 20457 Hamburg\nRequested delivery: 2030-01-15 API"
    res = client.post("/ingest", json=payload("Bestellung API", body), headers=H)
    assert res.status_code == 200, res.text
    out = res.json()
    assert (
        out["status"] == "completed"
        and out["task_status"] == "ready_to_send"
        and out["category"] == "order_request"
    )
    run = client.get(f"/runs/{out['run_id']}", headers=H).json()
    assert [a["node"] for a in run["audit"]][:3] == ["ingest", "sanitize", "classify"] and run[
        "audit"
    ][-1]["node"] == "audit"
    assert run["fields"]["product_skus"]["source_span"] and run["draft"]["sent"] is False
    assert (
        run["task"]["id"] == out["task_id"] and run["classification"]["category"] == "order_request"
    )


def test_ingest_duplicate_and_validation_errors(client: TestClient) -> None:
    p = payload("Frage API dup", "Could you send us your current product catalogue?")
    first = client.post("/ingest", json=p, headers=H).json()
    second = client.post("/ingest", json=p, headers=H).json()
    assert not first["duplicate"] and second["duplicate"] and second["task_id"] is None
    assert client.post("/ingest", json={"subject": "no sender"}, headers=H).status_code == 422
    assert client.get(f"/runs/{uuid.uuid4()}", headers=H).status_code == 404
    assert client.get("/runs/not-a-uuid", headers=H).status_code == 422


def test_ingest_eml_upload(client: TestClient) -> None:
    eml = b"From: Anna Klein <anna.klein@isar-gruppe.de>\nTo: ops@northwind-supply.de\nSubject: Frage eml upload\nMIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\nWhat are your opening hours over Christmas?\n"
    res = client.post("/ingest", files={"file": ("x.eml", eml, "message/rfc822")}, headers=H)
    assert res.status_code == 200 and res.json()["category"] == "general_inquiry"
    assert client.post("/ingest", files={"other": ("x.eml", eml)}, headers=H).status_code == 422


def test_batch_ingest(client: TestClient) -> None:
    emails = [
        payload(f"Frage batch {i}", f"Could you send us your current product catalogue? #{i}")
        for i in range(3)
    ]
    res = client.post("/ingest/batch", json={"emails": emails}, headers=H)
    assert res.status_code == 200 and len(res.json()["results"]) == 3
    assert client.post("/ingest/batch", json={"emails": []}, headers=H).status_code == 422


def test_review_flow_approve_updates_task_and_queue(client: TestClient) -> None:
    out = client.post(
        "/ingest", json=payload("Beschwerde API approve", ESCALATING), headers=H
    ).json()
    assert (
        out["status"] == "interrupted"
        and out["priority"] == "P1"
        and "high_severity_complaint" in out["escalation_reasons"]
    )
    pending = client.get("/reviews/pending", headers=H).json()
    mine = next(p for p in pending if p["task"]["run_id"] == out["run_id"])
    assert mine["task"]["status"] == "pending_review" and mine["draft"]["body"]
    # a task in review cannot be patched around the human gate
    assert (
        client.patch(f"/tasks/{out['task_id']}", json={"status": "closed"}, headers=H).status_code
        == 409
    )
    done = client.post(
        f"/reviews/{out['run_id']}", json={"action": "approve", "reviewer": "ops.lead"}, headers=H
    )
    assert done.status_code == 200 and done.json()["task_status"] == "ready_to_send"
    assert not any(
        p["task"]["run_id"] == out["run_id"]
        for p in client.get("/reviews/pending", headers=H).json()
    )
    run = client.get(f"/runs/{out['run_id']}", headers=H).json()
    assert run["reviews"][0]["reviewer"] == "ops.lead" and run["status"] == "completed"
    assert (
        client.post(
            f"/reviews/{out['run_id']}", json={"action": "approve", "reviewer": "x"}, headers=H
        ).status_code
        == 409
    )


def test_review_edit_reject_and_validation(client: TestClient) -> None:
    a = client.post(
        "/ingest", json=payload("Beschwerde API edit", ESCALATING + " edit"), headers=H
    ).json()
    assert (
        client.post(
            f"/reviews/{a['run_id']}", json={"action": "edit", "reviewer": "r"}, headers=H
        ).status_code
        == 422
    )
    ok = client.post(
        f"/reviews/{a['run_id']}",
        json={"action": "edit", "reviewer": "r", "edited_body": "Hello, edited."},
        headers=H,
    )
    assert ok.status_code == 200
    run = client.get(f"/runs/{a['run_id']}", headers=H).json()
    assert run["draft"]["body"] == "Hello, edited." and run["reviews"][0]["edits_diff"]
    b = client.post(
        "/ingest", json=payload("Beschwerde API reject", ESCALATING + " reject"), headers=H
    ).json()
    assert (
        client.post(
            f"/reviews/{b['run_id']}", json={"action": "reject", "reviewer": "r"}, headers=H
        ).status_code
        == 422
    )
    rej = client.post(
        f"/reviews/{b['run_id']}",
        json={"action": "reject", "reviewer": "r", "reason": "duplicate case"},
        headers=H,
    )
    assert rej.json()["task_status"] == "rejected"


def test_tasks_filters_and_patch(client: TestClient) -> None:
    out = client.post(
        "/ingest",
        json=payload("Frage API patch", "What are your opening hours over Christmas? patch"),
        headers=H,
    ).json()
    tasks = client.get(
        "/tasks", params={"category": "general_inquiry", "status": "ready_to_send"}, headers=H
    ).json()
    assert any(t["id"] == out["task_id"] for t in tasks) and all(
        t["category"] == "general_inquiry" for t in tasks
    )
    assert (
        client.get("/tasks", params={"priority": "P1", "escalated": True}, headers=H).status_code
        == 200
    )
    assert client.get("/tasks", params={"status": "bogus"}, headers=H).status_code == 422
    patched = client.patch(
        f"/tasks/{out['task_id']}", json={"status": "closed", "assignee_team": "Finance"}, headers=H
    )
    assert (
        patched.status_code == 200
        and patched.json()["status"] == "closed"
        and patched.json()["assignee_team"] == "Finance"
    )
    run = client.get(f"/runs/{out['run_id']}", headers=H).json()
    assert run["audit"][-1]["node"] == "task_update"  # manual changes are audited
    assert (
        client.patch(f"/tasks/{uuid.uuid4()}", json={"status": "closed"}, headers=H).status_code
        == 404
    )


def test_metrics_shape_and_consistency(client: TestClient) -> None:
    m = client.get("/metrics", headers=H).json()
    assert m["messages_processed"] >= 5 and 0 <= m["auto_resolved_pct"] <= 100
    assert sum(m["priority_distribution"].values()) == m["messages_processed"]
    assert m["estimated_hours_saved"] >= 0 and m["assumptions"]["manual_minutes_per_message"] > 0
    assert m["volume_by_category"] and m["sla"]["open"] >= 0


def test_samples_simulate_stream_graph_and_eval(
    client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    samples = client.get("/samples", headers=H).json()
    assert len(samples) == 80
    raw = client.get(f"/samples/{samples[0]['id']}", headers=H).json()
    assert raw["from_email"] and client.get("/samples/nope", headers=H).status_code == 404
    raw["subject"] += " streamed"
    with client.stream("POST", "/simulate/stream", json=raw, headers=H) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert events[0]["event"] == "start" and events[-1]["event"] == "done"
    assert next(e["node"] for e in events if e["event"] == "node") == "ingest"
    assert "flowchart" in client.get("/graph", headers=H).json()["mermaid"]
    monkeypatch.setattr("opspilot.api.app.REPORTS_DIR", tmp_path)
    assert client.get("/eval/latest", headers=H).status_code == 404
    (tmp_path / "eval_20260101_000000.json").write_text('{"ok": true}')
    assert client.get("/eval/latest", headers=H).json()["report"] == {"ok": True}


def test_batch_ingest_survives_one_failing_email(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import opspilot.runner as runner

    real = runner.Pipeline.start

    def flaky(self: runner.Pipeline, raw: Any, run_id: str | None = None) -> Any:
        if "boom" in raw.subject:
            raise RuntimeError("provider exploded")
        return real(self, raw, run_id)

    monkeypatch.setattr(runner.Pipeline, "start", flaky)
    emails = [
        payload("Frage batch ok", "Could you send us your current product catalogue? ok"),
        payload("Frage boom", "boom"),
    ]
    res = client.post("/ingest/batch", json={"emails": emails}, headers=H)
    assert res.status_code == 200
    statuses = [r["status"] for r in res.json()["results"]]
    assert statuses == ["completed", "failed"]
