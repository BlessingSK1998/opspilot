"""Node 6: hybrid rules + LLM priority and escalation reasons.

Rules decide *whether* a case needs a human. The LLM only contributes a risk read
(urgency, severity, legal language) that the rules consume, and may raise priority, never lower it.
"""

import time
from typing import Any

from opspilot.nodes.common import Deps, finish
from opspilot.nodes.validate import CUSTOMER_CATEGORIES
from opspilot.schemas.enums import JUNK_CATEGORIES, Category, Priority
from opspilot.schemas.state import OpsState

AMOUNT_LIMIT = 5000.0
CONFIDENCE_FLOOR = 0.7
THREAD_LIMIT = 3

BASE_PRIORITY = {
    Category.COMPLAINT: Priority.P2, Category.INVOICE_QUERY: Priority.P2, Category.REFUND_OR_RETURN: Priority.P2,
    Category.ORDER_REQUEST: Priority.P3, Category.SUPPLIER_DOCUMENT: Priority.P3, Category.ACCESS_OR_IT_REQUEST: Priority.P3,
    Category.GENERAL_INQUIRY: Priority.P4, Category.SPAM_OR_IRRELEVANT: Priority.P4,
    Category.JOB_APPLICATION_UPDATE: Priority.P3, Category.FINANCE_NOTICE: Priority.P2, Category.ACCOUNT_OR_SECURITY: Priority.P3,
    Category.PERSONAL_MESSAGE: Priority.P3, Category.JOB_ALERT: Priority.P4, Category.NEWSLETTER_OR_PROMO: Priority.P4,
}  # fmt: skip
ORDER = [Priority.P1, Priority.P2, Priority.P3, Priority.P4]
URGENCY_TO_PRIORITY = {1: Priority.P1, 2: Priority.P2, 3: Priority.P3, 4: Priority.P4}


def _most_urgent(*ps: Priority) -> Priority:
    return min(ps, key=ORDER.index)


def assess_priority(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    assert state.classification is not None
    cat = state.classification.category
    reasons: list[str] = []
    usage = None
    risk = None

    if cat not in JUNK_CATEGORIES:
        res = deps.provider.assess_risk(state.safe_text)
        risk, usage = res.parsed, res.usage

    customer = state.records.get("customer")
    if state.risk_amount is not None and state.risk_amount > AMOUNT_LIMIT:
        reasons.append("amount_over_5000")
    if risk and risk.legal_language:
        reasons.append("legal_language")
    if cat is Category.COMPLAINT and risk and risk.severity_signal == "high":
        reasons.append("high_severity_complaint")
    if customer and customer.get("vip") and cat in CUSTOMER_CATEGORIES | {Category.GENERAL_INQUIRY}:
        reasons.append("vip_customer")
    flat = state.flat_fields()
    if cat is Category.JOB_APPLICATION_UPDATE and flat.get("status") in ("interview", "offer"):
        reasons.append("interview_or_offer")
    if cat is Category.FINANCE_NOTICE and flat.get("action_required") is True:
        reasons.append("finance_action_required")
    if state.classification.confidence < CONFIDENCE_FLOOR:
        reasons.append("low_confidence")
    if state.injection_flags:
        reasons.append("prompt_injection")
    if state.message and state.message.thread_message_count >= THREAD_LIMIT:
        reasons.append("unresolved_thread")

    rule = BASE_PRIORITY[cat]
    if {"high_severity_complaint", "legal_language", "interview_or_offer"} & set(reasons) or {
        "vip_customer",
        "amount_over_5000",
    } <= set(reasons):
        rule = Priority.P1
    elif reasons:
        rule = _most_urgent(rule, Priority.P2)
    priority = _most_urgent(rule, URGENCY_TO_PRIORITY[risk.urgency]) if risk else rule

    summary = f"{priority.value}; escalation={reasons or 'none'}"
    return finish(
        "assess_priority",
        state,
        t0,
        summary,
        {"risk": risk, "priority": priority, "escalation_reasons": reasons},
        usage,
    )
