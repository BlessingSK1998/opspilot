"""Nodes 8: draft_response and draft_info_request. Drafts are never sent automatically."""

import json
import re
import time
from typing import Any

from opspilot.llm.mock_provider import is_german, parse_amount
from opspilot.nodes.common import Deps, finish
from opspilot.nodes.validate import ISSUE_MESSAGES
from opspilot.schemas.enums import DraftKind
from opspilot.schemas.llm import DraftResult
from opspilot.schemas.state import OpsState

FIELD_LABELS = {
    "customer_name": "Your name", "company": "Company name", "product_skus": "Product numbers (SKUs)",
    "quantities": "Quantities", "delivery_address": "Delivery address", "requested_date": "Requested delivery date",
    "invoice_number": "Invoice number", "amount": "Amount", "issue_type": "Nature of the problem",
    "order_number": "Order number", "reason": "Reason for the return", "items": "Items concerned",
    "severity_signal": "How urgent this is for you", "description": "Description of the problem",
    "supplier_name": "Supplier name", "document_type": "Document type", "document_number": "Document number",
    "due_date": "Payment due date", "employee_name": "Employee name", "system": "System", "access_level": "Access level (read/write/admin)",
    "manager_approval": "Confirmation of manager approval", "topic": "Topic", "question": "Your question",
}  # fmt: skip
TOKEN_RE = re.compile(
    r"\b(?:NW-\d{4}|SO-\d{4}-\d{5}|INV-\d{4}-\d{5}|PO-\d{5,8}|RE-\d{7}|LS-\d{5}|CERT-\d{4}-[A-D])\b|€\s?\d[\d.,]*|EUR\s?\d[\d.,]*"
)


def build_facts(state: OpsState, kind: DraftKind, owner_name: str | None = None) -> dict[str, Any]:
    cust = state.records.get("customer") or {}
    name = (
        state.flat_fields().get("customer_name")
        or (state.message.sender_name if state.message else None)
        or cust.get("contact_name")
    )
    slim = {k: v for k, v in state.records.items() if k != "customer"}
    facts: dict[str, Any] = {
        "profile": state.profile.value,
        "owner_name": owner_name,
        "subject": state.message.subject if state.message else None,
        "language": "de" if is_german(state.safe_text) else "en",
        "customer_name": name,
        "category": state.category.value if state.category else None,
        "fields": state.flat_fields(),
        "records": slim,
        "missing_fields": state.missing_fields,
        "field_labels": {f: FIELD_LABELS.get(f, f) for f in state.missing_fields},
        "issue_messages": [ISSUE_MESSAGES.get(i.split(":")[0], i) for i in state.validation_issues],
    }
    if kind is DraftKind.INFO_REQUEST:
        facts["records"] = {}  # an info request needs no record data
    return facts


def _numbers(obj: Any) -> set[float]:
    """Every numeric value present in the facts (including numbers inside strings)."""
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        out.add(round(float(obj), 2))
    elif isinstance(obj, str):
        for m in re.findall(r"\d[\d.,]*", obj):
            v = parse_amount(m)
            if v is not None:
                out.add(round(v, 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _numbers(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            out |= _numbers(v)
    return out


def ungrounded_tokens(body: str, facts: dict[str, Any]) -> list[str]:
    """Identifiers or amounts in the draft that appear nowhere in the supplied facts."""
    haystack = json.dumps(facts, ensure_ascii=False, default=str)
    known = _numbers(facts)
    out = []
    for tok in TOKEN_RE.findall(body):
        if tok[0] in "€E":  # an amount: compare numerically
            v = parse_amount(tok)
            if v is None or round(v, 2) not in known:
                out.append(tok)
        elif tok not in haystack:
            out.append(tok)
    return out


def _safe_fallback(facts: dict[str, Any]) -> DraftResult:
    de = facts["language"] == "de"
    hi = (
        f"Guten Tag {facts['customer_name']},"
        if de and facts.get("customer_name")
        else "Guten Tag,"
        if de
        else "Hello,"
    )
    body = (
        f"{hi}\n\nvielen Dank für Ihre Nachricht. Ein Kollege prüft Ihr Anliegen und meldet sich bei Ihnen.\n\nMit freundlichen Grüßen\nNorthwind Supply GmbH, Operations Team"
        if de
        else f"{hi}\n\nthank you for your message. A colleague is reviewing your request and will get back to you.\n\nKind regards\nNorthwind Supply GmbH, Operations Team"
    )
    return DraftResult(
        subject="Ihre Anfrage bei Northwind" if de else "Your request to Northwind", body=body
    )


def _draft(node: str, kind: DraftKind, state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    facts = build_facts(state, kind, deps.owner_name)
    res = deps.provider.draft(kind, facts)
    draft, warnings = res.parsed, list(state.warnings)
    bad = ungrounded_tokens(draft.body, facts)
    if bad:  # guardrail: never ship invented identifiers or amounts
        warnings.append(f"draft_ungrounded:{','.join(bad)}")
        draft = _safe_fallback(facts)
    return finish(node, state, t0, f"{kind.value} draft ({len(draft.body)} chars){' [grounding fallback]' if bad else ''}",
                  {"draft": draft, "draft_kind": kind, "warnings": warnings}, res.usage)  # fmt: skip


def draft_response(state: OpsState, deps: Deps) -> dict[str, Any]:
    return _draft("draft_response", DraftKind.RESPONSE, state, deps)


def draft_info_request(state: OpsState, deps: Deps) -> dict[str, Any]:
    return _draft("draft_info_request", DraftKind.INFO_REQUEST, state, deps)
