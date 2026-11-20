"""FastAPI application."""

import json
import re
import secrets
import uuid
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot import __version__
from opspilot.api.container import Container, build_container
from opspilot.api.metrics import compute_metrics
from opspilot.api.models import (
    AuditOut,
    BatchIngestRequest,
    BatchIngestResponse,
    DraftOut,
    HealthResponse,
    IngestResponse,
    MessageOut,
    Metrics,
    PendingReview,
    ReviewOut,
    ReviewRequest,
    RunDetail,
    SampleOut,
    TaskOut,
    TaskPatch,
)
from opspilot.db.models import AuditEvent, Draft, Extraction, Message, ReviewDecision, Run, Task
from opspilot.emailio import raw_from_eml, raw_from_seed_json
from opspilot.graph.build import MERMAID
from opspilot.llm.base import LLMUnavailableError
from opspilot.logging_setup import configure_logging
from opspilot.runner import RunResult
from opspilot.schemas.enums import Category, Priority, ReviewAction, RunStatus, TaskStatus
from opspilot.schemas.state import RawEmail
from opspilot.settings import Settings, get_settings

SEED_DIR = Path("data/seed")
SAMPLE_DIRS = {"ops": SEED_DIR, "personal": Path("data/seed_personal")}
REPORTS_DIR = Path("reports")


def _task_out(t: Task, m: Message, confidence: float | None) -> TaskOut:
    return TaskOut(
        id=str(t.id), run_id=str(t.run_id), subject=m.subject, sender=m.sender, received_at=m.received_at,
        category=t.category, priority=t.priority, status=t.status, assignee_team=t.assignee_team, sla_due_at=t.sla_due_at,
        escalation_reasons=list(t.escalation_reasons), confidence=confidence, has_draft=t.draft_id is not None,
    )  # fmt: skip


def _draft_out(d: Draft | None) -> DraftOut | None:
    return DraftOut(kind=d.kind.value, subject=d.subject, body=d.body, sent=d.sent) if d else None


def _ingest_response(res: RunResult) -> IngestResponse:
    s = res.state
    return IngestResponse(
        run_id=res.run_id, status=res.status, duplicate=s.duplicate, category=s.category, priority=s.priority,
        task_id=s.task_id, task_status=s.task_status, escalation_reasons=s.escalation_reasons,
    )  # fmt: skip


def create_app(
    container_factory: Callable[[Settings], Container] | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    holder: dict[str, Container] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        holder["c"] = (container_factory or build_container)(settings)
        yield
        holder["c"].close()

    app = FastAPI(
        title="OpsPilot API", version=__version__, lifespan=lifespan,
        description="AI operations assistant for Northwind Supply GmbH. Turns a messy shared inbox into routed, "
        "validated work items; a human approves anything risky. Authenticate with the `X-API-Key` header.",
        openapi_tags=[{"name": "system"}, {"name": "ingest"}, {"name": "runs"}, {"name": "tasks"}, {"name": "reviews"}, {"name": "insights"}, {"name": "demo"}],
    )  # fmt: skip

    @app.exception_handler(LLMUnavailableError)
    async def llm_unavailable(_: Request, exc: LLMUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": f"LLM provider unavailable: {exc}"})

    def container() -> Container:
        return holder["c"]

    def session(c: Annotated[Container, Depends(container)]) -> Iterator[Session]:
        with c.factory() as s:
            yield s

    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        expected = settings.api_key.get_secret_value()
        if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")

    Auth = Depends(require_key)
    C = Annotated[Container, Depends(container)]
    S = Annotated[Session, Depends(session)]

    # ---- system -----------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/docs")

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__, llm_provider=settings.llm_provider)

    @app.get(
        "/graph",
        tags=["system"],
        dependencies=[Auth],
        summary="Mermaid source of the LangGraph flow",
    )
    def graph() -> dict[str, str]:
        return {"mermaid": MERMAID}

    # ---- ingest -----------------------------------------------------------
    @app.post(
        "/ingest", response_model=IngestResponse, tags=["ingest"], dependencies=[Auth],
        summary="Ingest one e-mail (JSON body, or multipart upload of an .eml file in field `file`)",
        openapi_extra={"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/RawEmail"}},
                                                    "multipart/form-data": {"schema": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}}}}},
    )  # fmt: skip
    async def ingest(request: Request, c: C) -> IngestResponse:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            f = form.get("file")
            if f is None or isinstance(f, str):
                raise HTTPException(422, "multipart upload needs a file field named 'file'")
            raw = raw_from_eml(await f.read())
        else:
            try:
                raw = RawEmail.model_validate(await request.json())
            except ValueError as exc:
                raise HTTPException(422, f"invalid e-mail payload: {exc}") from exc
        return _ingest_response(c.pipeline.start(raw))

    @app.post(
        "/ingest/batch", response_model=BatchIngestResponse, tags=["ingest"], dependencies=[Auth]
    )
    def ingest_batch(body: BatchIngestRequest, c: C) -> BatchIngestResponse:
        results: list[IngestResponse] = []
        for e in body.emails:
            run_id = str(uuid.uuid4())
            try:
                results.append(_ingest_response(c.pipeline.start(e, run_id)))
            except (
                Exception
            ):  # one bad e-mail must not lose the rest of the batch; the run is recorded as failed
                results.append(IngestResponse(run_id=run_id, status=RunStatus.FAILED))
        return BatchIngestResponse(results=results)

    # ---- runs -------------------------------------------------------------
    @app.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"], dependencies=[Auth])
    def get_run(run_id: uuid.UUID, s: S) -> RunDetail:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        msg = s.get(Message, run.message_id)
        assert msg is not None
        task = s.scalar(select(Task).where(Task.run_id == run_id))
        ex = s.scalar(select(Extraction).where(Extraction.run_id == run_id))
        draft = s.scalar(select(Draft).where(Draft.run_id == run_id))
        audit = list(
            s.scalars(select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id))
        )
        reviews = list(
            s.scalars(
                select(ReviewDecision)
                .where(ReviewDecision.run_id == run_id)
                .order_by(ReviewDecision.created_at)
            )
        )
        final = run.final_state or {}
        return RunDetail(
            run_id=str(run.id), status=run.status, provider=run.provider, started_at=run.started_at, finished_at=run.finished_at,
            message=MessageOut(id=str(msg.id), subject=msg.subject, sender=msg.sender, sender_name=msg.sender_name, body=msg.body,
                               received_at=msg.received_at, thread_message_count=msg.thread_message_count,
                               attachments=[{"filename": a.filename, "content_type": a.content_type, "size_bytes": a.size_bytes, "text": a.extracted_text} for a in msg.attachments]),
            task=_task_out(task, msg, ex.confidence if ex else None) if task else None,
            draft=_draft_out(draft),
            classification={"category": ex.category.value, "confidence": ex.confidence, "rationale": ex.rationale} if ex else None,
            fields=dict(ex.fields) if ex else {}, missing_fields=list(ex.missing_fields) if ex else [],
            validation_issues=list(ex.validation_issues) if ex else [], warnings=list(final.get("warnings", [])),
            injection_flags=list(final.get("injection_flags", [])),
            reviews=[ReviewOut(reviewer=r.reviewer, action=r.action, edits_diff=r.edits_diff, reason=r.reason, created_at=r.created_at) for r in reviews],
            audit=[AuditOut(node=a.node, input_hash=a.input_hash, output_summary=a.output_summary, model=a.model, prompt_version=a.prompt_version,
                            tokens_in=a.tokens_in, tokens_out=a.tokens_out, cost_eur=float(a.cost_eur), latency_ms=a.latency_ms, ts=a.ts) for a in audit],
        )  # fmt: skip

    # ---- tasks ------------------------------------------------------------
    @app.get("/tasks", response_model=list[TaskOut], tags=["tasks"], dependencies=[Auth])
    def list_tasks(
        s: S, status: TaskStatus | None = None, priority: Priority | None = None, category: Category | None = None,
        assignee: str | None = None, escalated: bool | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 200, offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[TaskOut]:  # fmt: skip
        q = (
            select(Task, Message, Extraction.confidence)
            .join(Message, Message.id == Task.message_id)
            .outerjoin(Extraction, Extraction.run_id == Task.run_id)
        )
        if status:
            q = q.where(Task.status == status)
        if priority:
            q = q.where(Task.priority == priority)
        if category:
            q = q.where(Task.category == category)
        if assignee:
            q = q.where(Task.assignee_team == assignee)
        q = q.order_by(Task.priority, Task.sla_due_at).limit(limit).offset(offset)
        rows = s.execute(q).all()
        out = [_task_out(t, m, conf) for t, m, conf in rows]
        if escalated is not None:
            out = [t for t in out if bool(t.escalation_reasons) == escalated]
        return out

    @app.patch("/tasks/{task_id}", response_model=TaskOut, tags=["tasks"], dependencies=[Auth])
    def patch_task(task_id: uuid.UUID, patch: TaskPatch, s: S) -> TaskOut:
        t = s.get(Task, task_id)
        if t is None:
            raise HTTPException(404, "task not found")
        if t.status is TaskStatus.PENDING_REVIEW:
            raise HTTPException(409, "task is awaiting human review; use POST /reviews/{run_id}")
        changes = []
        if patch.status:
            changes.append(f"status {t.status.value} -> {patch.status}")
            t.status = TaskStatus(patch.status)
        if patch.assignee_team:
            changes.append(f"assignee {t.assignee_team} -> {patch.assignee_team}")
            t.assignee_team = patch.assignee_team
        if changes:
            s.add(
                AuditEvent(
                    run_id=t.run_id,
                    node="task_update",
                    input_hash="manual",
                    output_summary="; ".join(changes),
                    ts=datetime.now(UTC),
                )
            )
        s.commit()
        m = s.get(Message, t.message_id)
        assert m is not None
        return _task_out(t, m, None)

    # ---- reviews ----------------------------------------------------------
    @app.get(
        "/reviews/pending",
        response_model=list[PendingReview],
        tags=["reviews"],
        dependencies=[Auth],
    )
    def pending_reviews(s: S) -> list[PendingReview]:
        rows = s.execute(select(Task, Message, Extraction.confidence).join(Message, Message.id == Task.message_id).outerjoin(Extraction, Extraction.run_id == Task.run_id)
                         .where(Task.status == TaskStatus.PENDING_REVIEW).order_by(Task.priority, Task.sla_due_at)).all()  # fmt: skip
        out = []
        for t, m, conf in rows:
            d = s.get(Draft, t.draft_id) if t.draft_id else None
            out.append(PendingReview(task=_task_out(t, m, conf), draft=_draft_out(d)))
        return out

    @app.post("/reviews/{run_id}", response_model=IngestResponse, tags=["reviews"], dependencies=[Auth],
              summary="Approve, edit or reject an escalated run; resumes the paused graph")  # fmt: skip
    def review(run_id: uuid.UUID, body: ReviewRequest, c: C) -> IngestResponse:
        rid = str(run_id)
        if not c.pipeline.is_interrupted(rid):
            raise HTTPException(409, "run is not waiting for review")
        if body.action is ReviewAction.REJECT and not (body.reason and body.reason.strip()):
            raise HTTPException(422, "a reason is required to reject")
        if body.action is ReviewAction.EDIT and not (body.edited_body and body.edited_body.strip()):
            raise HTTPException(422, "edited_body is required to edit")
        return _ingest_response(c.pipeline.resume(rid, body.model_dump(mode="json")))

    # ---- insights ---------------------------------------------------------
    @app.get("/metrics", response_model=Metrics, tags=["insights"], dependencies=[Auth])
    def metrics(s: S) -> Metrics:
        return compute_metrics(s)

    @app.get(
        "/eval/latest",
        tags=["insights"],
        dependencies=[Auth],
        summary="Latest evaluation report (JSON + Markdown)",
    )
    def latest_eval(dataset: str = "ops") -> dict[str, Any]:
        found = [(f, json.loads(f.read_text())) for f in sorted(REPORTS_DIR.glob("eval*_*.json"))]
        found = [(f, r) for f, r in found if r.get("dataset", "ops") == dataset]
        if not found:
            raise HTTPException(404, f"no {dataset} evaluation report yet; run `make eval`")
        f, report = found[-1]
        md = f.with_suffix(".md")
        return {"name": f.stem, "report": report, "markdown": md.read_text() if md.exists() else ""}

    # ---- demo helpers -----------------------------------------------------
    @app.get("/samples", response_model=list[SampleOut], tags=["demo"], dependencies=[Auth])
    def samples(dataset: str = "ops") -> list[SampleOut]:
        base = SAMPLE_DIRS.get(dataset)
        if base is None:
            raise HTTPException(422, "dataset must be 'ops' or 'personal'")
        out = []
        for p in sorted((base / "emails").glob("*.json")):
            d = json.loads(p.read_text())
            out.append(SampleOut(id=d["id"], subject=d["subject"], from_email=d["from_email"]))
        return out

    @app.get("/samples/{sample_id}", response_model=RawEmail, tags=["demo"], dependencies=[Auth])
    def sample(sample_id: str, dataset: str = "ops") -> RawEmail:
        base = SAMPLE_DIRS.get(dataset)
        if base is None or not re.fullmatch(r"[A-Z]{2}-\d{3}", sample_id):
            raise HTTPException(404, "sample not found")
        p = base / "emails" / f"{sample_id}.json"
        if not p.exists():
            raise HTTPException(404, "sample not found")
        return raw_from_seed_json(p, base / "attachments")

    @app.post(
        "/simulate/stream",
        tags=["demo"],
        dependencies=[Auth],
        summary="Run an e-mail and stream one server-sent event per completed node",
    )
    def simulate(raw: RawEmail, c: C) -> StreamingResponse:
        def events() -> Iterator[str]:
            try:
                for ev in c.pipeline.stream(raw):
                    yield f"data: {json.dumps(ev)}\n\n"
            except LLMUnavailableError as exc:
                yield f"data: {json.dumps({'event': 'error', 'message': str(exc)})}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    _ = RunStatus  # imported for response typing in OpenAPI
    return app
