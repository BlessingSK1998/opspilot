import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from opspilot.llm import MockProvider
from opspilot.nodes import Deps, assess_priority, classify, extract, ingest, sanitize, validate
from opspilot.schemas.state import AttachmentIn, OpsState, RawEmail
from opspilot.tools.reference import MemoryReference
from opspilot.tools.sink import Backend, MemorySink

SEED = Path("data/seed")
PIPE = (ingest, sanitize, classify, extract, validate, assess_priority)


@pytest.fixture(scope="session")
def reference() -> MemoryReference:
    return MemoryReference(SEED)


@pytest.fixture
def deps(reference: MemoryReference) -> Deps:
    return Deps(MockProvider(), Backend(reference, MemorySink()))


def apply(state: OpsState, update: dict[str, Any]) -> OpsState:
    update = dict(update)
    audit = update.pop("audit", [])
    return state.model_copy(update={**update, "audit": state.audit + audit})


@pytest.fixture
def run_pipeline(deps: Deps) -> Callable[..., OpsState]:
    def _run(raw: RawEmail, upto: int = 6) -> OpsState:
        state = OpsState(run_id="r1", raw=raw)
        for node in PIPE[:upto]:
            state = apply(state, node(state, deps))
        return state

    return _run


@pytest.fixture
def customer(reference: MemoryReference) -> dict[str, Any]:
    c = reference.find_customer(
        name=json.loads((SEED / "reference" / "customers.json").read_text())[0]["name"]
    )
    assert c
    return c


def make_raw(customer: dict[str, Any], subject: str, body: str, **kw: Any) -> RawEmail:
    return RawEmail(from_email=customer["contact_email"], from_name=customer["contact_name"], subject=subject,
                    body=f"{body}\n\nBest regards\n--\n{customer['contact_name']}\n{customer['name']}\nTel.: +49 40 123 4567", **kw)  # fmt: skip


def attach(name: str, ctype: str, data: bytes) -> AttachmentIn:
    return AttachmentIn(
        filename=name, content_type=ctype, content_b64=base64.b64encode(data).decode()
    )


def ref_rows(name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((SEED / "reference" / f"{name}.json").read_text())
    return data
