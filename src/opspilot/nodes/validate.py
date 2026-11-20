"""Node 5: deterministic validation. No LLM here: formats, completeness and DB cross-checks."""

import re
import time
from datetime import date
from typing import Any

from opspilot.nodes.common import Deps, finish
from opspilot.schemas.enums import Category, IssueType
from opspilot.schemas.extraction import SCHEMAS
from opspilot.schemas.state import OpsState
from opspilot.tools.agent_tools import (
    CheckInventoryArgs,
    LookupCustomerArgs,
    LookupInvoiceArgs,
    LookupOrderArgs,
    check_inventory,
    lookup_customer,
    lookup_invoice,
    lookup_order,
)

INVOICE_RE = re.compile(r"^INV-\d{4}-\d{5}$")
ORDER_RE = re.compile(r"^SO-\d{4}-\d{5}$")
PO_RE = re.compile(r"^PO-\d{5,8}$")
SKU_RE = re.compile(r"^NW-\d{4}$")
CUSTOMER_CATEGORIES = {
    Category.ORDER_REQUEST,
    Category.INVOICE_QUERY,
    Category.REFUND_OR_RETURN,
    Category.COMPLAINT,
}
AMOUNT_TOLERANCE = 0.01

ISSUE_MESSAGES = {
    "invoice_not_found": "We could not find the invoice number you quoted. Could you please check it?",
    "amount_mismatch": "The amount you mention differs from our records. Could you confirm the amount?",
    "manager_approval_missing": "Manager approval is required before we can grant access.",
    "order_not_found": "We could not find the order number you quoted. Could you please check it?",
    "customer_not_found": "We could not match your message to a customer account. Please send your customer number.",
}


def _resolve_customer(state: OpsState, deps: Deps) -> dict[str, Any] | None:
    ref = deps.backend.reference
    company = state.flat_fields().get("company")
    if company and (c := lookup_customer(ref, LookupCustomerArgs(name=company))):
        return c
    emails = [state.message.sender] if state.message else []
    emails += re.findall(r"From: .*?<([^>]+)>", state.email_text)  # forwarded chains
    for e in emails:
        if e.endswith("@northwind-supply.de"):
            continue
        if c := lookup_customer(ref, LookupCustomerArgs(email=e)):
            return c
    return None


def _valid_iso(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def validate(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    assert state.classification is not None
    cat = state.classification.category
    ref = deps.backend.reference
    f = state.flat_fields()
    issues: list[str] = []
    warnings: list[str] = []
    records: dict[str, Any] = {}
    amount: float | None = None

    schema = SCHEMAS[cat].model_validate(state.fields)
    missing = schema.missing_required()

    customer = (
        _resolve_customer(state, deps)
        if cat in CUSTOMER_CATEGORIES or cat is Category.GENERAL_INQUIRY
        else None
    )
    if customer:
        records["customer"] = customer
    elif cat in CUSTOMER_CATEGORIES:
        issues.append("customer_not_found")

    if cat is Category.ORDER_REQUEST:
        skus: list[str] = f.get("product_skus", [])
        qtys: list[int] = f.get("quantities", [])
        for s in skus:
            if not SKU_RE.match(s) or ref.get_product(s) is None:
                issues.append(f"unknown_sku:{s}")
        if skus and qtys:
            if len(skus) != len(qtys) or any(q <= 0 for q in qtys):
                issues.append("quantity_mismatch")
            else:
                known = [(s, q) for s, q in zip(skus, qtys, strict=True) if ref.get_product(s)]
                amount = round(sum(q * ref.get_product(s)["unit_price"] for s, q in known), 2)
                for s, q in known:
                    inv = check_inventory(ref, CheckInventoryArgs(sku=s, quantity=q))
                    if not inv["sufficient"]:
                        warnings.append(f"insufficient_stock:{s}")
        if "requested_date" in f:
            d = _valid_iso(f["requested_date"])
            if d is None:
                issues.append("invalid_requested_date")
            elif state.message and d < state.message.received_at.date():
                issues.append("requested_date_in_past")
        if "po_number" in f and not PO_RE.match(f["po_number"]):
            issues.append("invalid_po_number_format")

    elif cat is Category.INVOICE_QUERY:
        amount = f.get("amount")
        if "issue_type" in f and f["issue_type"] not in {i.value for i in IssueType}:
            issues.append("invalid_issue_type")
        if num := f.get("invoice_number"):
            if not INVOICE_RE.match(num):
                issues.append("invalid_invoice_number_format")
            elif (inv_rec := lookup_invoice(ref, LookupInvoiceArgs(invoice_number=num))) is None:
                issues.append("invoice_not_found")
            else:
                records["invoice"] = inv_rec
                if customer and inv_rec["customer_id"] != customer["id"]:
                    issues.append("invoice_customer_mismatch")
                if amount is not None and abs(inv_rec["amount"] - amount) > AMOUNT_TOLERANCE:
                    issues.append("amount_mismatch")

    elif cat is Category.REFUND_OR_RETURN:
        amount = f.get("amount")
        if num := f.get("order_number"):
            if not ORDER_RE.match(num):
                issues.append("invalid_order_number_format")
            elif (order := lookup_order(ref, LookupOrderArgs(order_number=num))) is None:
                issues.append("order_not_found")
            else:
                records["order"] = order
                if customer and order["customer_id"] != customer["id"]:
                    issues.append("order_customer_mismatch")
                in_order = {ln["sku"] for ln in order["lines"]}
                for s in f.get("items", []):
                    if s not in in_order:
                        issues.append(f"item_not_in_order:{s}")

    elif cat is Category.COMPLAINT:
        if num := f.get("order_number"):
            order = (
                lookup_order(ref, LookupOrderArgs(order_number=num))
                if ORDER_RE.match(num)
                else None
            )
            if order is None:
                issues.append("order_not_found")
            else:
                records["order"] = order

    elif cat is Category.SUPPLIER_DOCUMENT:
        amount = f.get("amount")
        if f.get("document_type") not in (None, "invoice", "delivery_note", "certificate"):
            issues.append("invalid_document_type")
        if "due_date" in f and _valid_iso(f["due_date"]) is None:
            issues.append("invalid_due_date")

    elif cat is Category.ACCESS_OR_IT_REQUEST:
        if f.get("manager_approval") is False:
            issues.append("manager_approval_missing")
        if "access_level" in f and f["access_level"] not in ("read", "write", "admin"):
            issues.append("invalid_access_level")

    elif cat is Category.JOB_APPLICATION_UPDATE:
        if "status" in f and f["status"] not in (
            "received",
            "rejected",
            "interview",
            "offer",
            "other",
        ):
            issues.append("invalid_application_status")

    elif cat is Category.FINANCE_NOTICE:
        amount = f.get("amount")
        if "due_date" in f and _valid_iso(f["due_date"]) is None:
            issues.append("invalid_due_date")

    if amount is not None and amount <= 0:
        issues.append("invalid_amount")

    summary = (
        f"missing={missing or 'none'}; issues={issues or 'none'}; warnings={warnings or 'none'}"
    )
    return finish("validate", state, t0, summary, {
        "missing_fields": missing, "validation_issues": issues, "warnings": warnings,
        "records": records, "risk_amount": amount,
    })  # fmt: skip
