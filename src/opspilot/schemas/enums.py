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
    # personal-inbox profile
    JOB_APPLICATION_UPDATE = "job_application_update"
    JOB_ALERT = "job_alert"
    NEWSLETTER_OR_PROMO = "newsletter_or_promo"
    FINANCE_NOTICE = "finance_notice"
    ACCOUNT_OR_SECURITY = "account_or_security"
    PERSONAL_MESSAGE = "personal_message"


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


class Profile(StrEnum):
    """Which kind of mailbox an e-mail belongs to; selects categories, prompts and routing."""

    OPS = "ops"
    PERSONAL = "personal"


OPS_CATEGORIES = [
    Category.ORDER_REQUEST, Category.INVOICE_QUERY, Category.REFUND_OR_RETURN, Category.COMPLAINT,
    Category.SUPPLIER_DOCUMENT, Category.ACCESS_OR_IT_REQUEST, Category.GENERAL_INQUIRY, Category.SPAM_OR_IRRELEVANT,
]  # fmt: skip
PERSONAL_CATEGORIES = [
    Category.JOB_APPLICATION_UPDATE, Category.JOB_ALERT, Category.NEWSLETTER_OR_PROMO, Category.FINANCE_NOTICE,
    Category.ACCOUNT_OR_SECURITY, Category.PERSONAL_MESSAGE, Category.SPAM_OR_IRRELEVANT,
]  # fmt: skip
CATEGORIES_BY_PROFILE = {Profile.OPS: OPS_CATEGORIES, Profile.PERSONAL: PERSONAL_CATEGORIES}
# Categories that are filed away without a reply or a task for a person.
JUNK_CATEGORIES = {Category.SPAM_OR_IRRELEVANT, Category.JOB_ALERT, Category.NEWSLETTER_OR_PROMO}
