"""Enumerations shared by the DB layer, graph state and API."""

from enum import StrEnum


class Category(StrEnum):
    ORDER_REQUEST = "order_request"
    INVOICE_QUERY = "invoice_query"
    REFUND_OR_RETURN = "refund_or_return"
    COMPLAINT = "complaint"
    SUPPLIER_DOCUMENT = "supplier_document"
    ACCESS_OR_IT_REQUEST = "access_or_it_request"
    GENERAL_INQUIRY = "general_inquiry"
    SPAM_OR_IRRELEVANT = "spam_or_irrelevant"


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class TaskStatus(StrEnum):
    READY_TO_SEND = "ready_to_send"
    AWAITING_CUSTOMER = "awaiting_customer"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    CLOSED = "closed"


class RunStatus(StrEnum):
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"


class DraftKind(StrEnum):
    RESPONSE = "response"
    INFO_REQUEST = "info_request"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class IssueType(StrEnum):
    OVERCHARGE = "overcharge"
    MISSING = "missing"
    DUPLICATE = "duplicate"
    OTHER = "other"


class OrderStatus(StrEnum):
    OPEN = "open"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class InvoiceStatus(StrEnum):
    OPEN = "open"
    PAID = "paid"
    OVERDUE = "overdue"
