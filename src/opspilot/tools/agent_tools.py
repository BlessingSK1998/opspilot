"""The agent's tools: typed functions with Pydantic argument schemas.

`TOOL_SPECS` exports them in OpenAI function-calling format, so the same definitions can be
handed to a tool-calling model; the pipeline also invokes them directly from deterministic nodes.
"""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from opspilot.tools.reference import Reference


class LookupCustomerArgs(BaseModel):
    name: str | None = Field(None, description="Company name")
    email: str | None = Field(None, description="Sender e-mail; the domain is used as a fallback")


class LookupOrderArgs(BaseModel):
    order_number: str = Field(description="Format SO-YYYY-NNNNN")


class LookupInvoiceArgs(BaseModel):
    invoice_number: str = Field(description="Format INV-YYYY-NNNNN")


class CheckInventoryArgs(BaseModel):
    sku: str
    quantity: int = Field(gt=0)


class GetSlaPolicyArgs(BaseModel):
    priority: str = Field(pattern="^P[1-4]$")


class NotifyHumanArgs(BaseModel):
    severity: str = Field(pattern="^(info|warning|critical)$")
    message: str


class CreateTaskArgs(BaseModel):
    run_id: str


def lookup_customer(ref: Reference, args: LookupCustomerArgs) -> dict[str, Any] | None:
    return ref.find_customer(name=args.name, email=args.email)


def lookup_order(ref: Reference, args: LookupOrderArgs) -> dict[str, Any] | None:
    return ref.get_order(args.order_number)


def lookup_invoice(ref: Reference, args: LookupInvoiceArgs) -> dict[str, Any] | None:
    return ref.get_invoice(args.invoice_number)


def check_inventory(ref: Reference, args: CheckInventoryArgs) -> dict[str, Any]:
    p = ref.get_product(args.sku)
    if p is None:
        return {"sku": args.sku, "known": False, "available": 0, "sufficient": False}
    return {
        "sku": args.sku,
        "known": True,
        "available": p["stock"],
        "sufficient": p["stock"] >= args.quantity,
    }


def get_sla_policy(ref: Reference, args: GetSlaPolicyArgs) -> dict[str, Any]:
    return ref.get_sla(args.priority)


TOOLS: dict[str, tuple[str, type[BaseModel], Callable[..., Any]]] = {
    "lookup_customer": (
        "Find a customer by company name or sender e-mail.",
        LookupCustomerArgs,
        lookup_customer,
    ),
    "lookup_order": ("Fetch an order by order number.", LookupOrderArgs, lookup_order),
    "lookup_invoice": ("Fetch an invoice by invoice number.", LookupInvoiceArgs, lookup_invoice),
    "check_inventory": ("Check stock for a SKU and quantity.", CheckInventoryArgs, check_inventory),
    "get_sla_policy": (
        "Return response/resolution hours for a priority.",
        GetSlaPolicyArgs,
        get_sla_policy,
    ),
    "notify_human": (
        "Notify the operations team (notifications table, optional Slack).",
        NotifyHumanArgs,
        lambda *_: None,
    ),
    "create_task": (
        "Create the work item for a processed message.",
        CreateTaskArgs,
        lambda *_: None,
    ),
}


def tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": n, "description": d, "parameters": a.model_json_schema()},
        }
        for n, (d, a, _) in TOOLS.items()
    ]


def call_tool(ref: Reference, name: str, arguments: dict[str, Any]) -> Any:
    """Validate arguments against the schema, then dispatch (for model-issued tool calls)."""
    _, args_model, fn = TOOLS[name]
    return fn(ref, args_model.model_validate(arguments))
