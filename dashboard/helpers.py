"""Pure helpers (unit-tested): highlighting, formatting, colour system."""

import html
from datetime import UTC, datetime
from typing import Any

ALL_CATEGORIES = [
    "order_request", "invoice_query", "refund_or_return", "complaint", "supplier_document", "access_or_it_request",
    "general_inquiry", "spam_or_irrelevant", "job_application_update", "job_alert", "newsletter_or_promo",
    "finance_notice", "account_or_security", "personal_message",
]  # fmt: skip
TEAMS = ["Sales Operations", "Finance", "Customer Service", "Accounts Payable", "IT Service Desk",
         "Job search", "Finances", "Accounts", "Personal", "Archive"]  # fmt: skip
PRIORITY_COLOURS = {"P1": "#C0392B", "P2": "#E08A1E", "P3": "#2F6FB0", "P4": "#8A94A3"}
STATUS_COLOURS = {
    "pending_review": "#C0392B", "awaiting_customer": "#E08A1E", "ready_to_send": "#0F766E",
    "rejected": "#8A94A3", "archived": "#B8C0CC", "closed": "#5B6B7F", "approved": "#0F766E",
}  # fmt: skip
CATEGORY_COLOURS = [
    "#0F766E",
    "#2F6FB0",
    "#E08A1E",
    "#C0392B",
    "#6B5CA5",
    "#3D9970",
    "#8A94A3",
    "#B8860B",
]
REASON_LABELS = {
    "amount_over_5000": "Amount over €5,000", "legal_language": "Legal language", "high_severity_complaint": "High-severity complaint",
    "vip_customer": "VIP customer", "low_confidence": "Low classification confidence", "prompt_injection": "Possible prompt injection",
    "unresolved_thread": "3+ messages, unresolved",
    "interview_or_offer": "Interview or offer: needs your reply",
    "finance_action_required": "Money matter: action expected",
}  # fmt: skip


def highlight(body: str, spans: list[str]) -> str:
    """HTML-escape `body` and wrap each non-empty source span in <mark>."""
    out = html.escape(body)
    for span in sorted({s for s in spans if s and len(s) > 1}, key=len, reverse=True):
        esc = html.escape(span)
        if esc in out:
            out = out.replace(esc, f"<mark>{esc}</mark>", 1)
    return out.replace("\n", "<br>")


def chip(text: str, colour: str) -> str:
    return f'<span class="chip" style="background:{colour}1A;color:{colour};border:1px solid {colour}55">{html.escape(text)}</span>'


def priority_chip(p: str) -> str:
    return chip(p, PRIORITY_COLOURS.get(p, "#8A94A3"))


def reason_chips(reasons: list[str]) -> str:
    return (
        " ".join(chip(REASON_LABELS.get(r, r), "#C0392B") for r in reasons)
        or '<span class="muted">none</span>'
    )


def fmt_dt(value: str | datetime | None) -> str:
    if not value:
        return "-"
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt.strftime("%d %b %H:%M")


def sla_label(due: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    delta = datetime.fromisoformat(due) - now
    mins = int(delta.total_seconds() // 60)
    if mins < 0:
        h = -mins // 60
        return f"overdue {h}h" if h < 48 else f"overdue {h // 24}d"
    return f"in {mins // 60}h {mins % 60}m" if mins >= 60 else f"in {mins}m"


def fields_table(fields: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"Field": k, "Value": ", ".join(map(str, v["value"])) if isinstance(v["value"], list) else str(v["value"]),
         "Confidence": round(float(v.get("confidence", 0)), 2), "Source": v.get("source_span") or ""}
        for k, v in fields.items()
    ]  # fmt: skip


def pct(x: float) -> str:
    return f"{x:.0f}%" if x == int(x) else f"{x:.1f}%"
