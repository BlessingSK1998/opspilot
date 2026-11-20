"""Per-category extraction schemas. Every field carries value + confidence + source span."""

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from opspilot.schemas.enums import Category, IssueType


class StrField(BaseModel):
    value: str | None = None
    confidence: float = Field(0.0, ge=0, le=1)
    source_span: str | None = Field(None, description="Exact quoted text the value came from")


class StrListField(BaseModel):
    value: list[str] | None = None
    confidence: float = Field(0.0, ge=0, le=1)
    source_span: str | None = None


class IntListField(BaseModel):
    value: list[int] | None = None
    confidence: float = Field(0.0, ge=0, le=1)
    source_span: str | None = None


class FloatField(BaseModel):
    value: float | None = None
    confidence: float = Field(0.0, ge=0, le=1)
    source_span: str | None = None


class BoolField(BaseModel):
    value: bool | None = None
    confidence: float = Field(0.0, ge=0, le=1)
    source_span: str | None = None


class CategoryExtraction(BaseModel):
    """Base class. A field left None (or with value None) means 'not stated in the text'."""

    REQUIRED: ClassVar[tuple[str, ...]] = ()
    CATEGORY: ClassVar[Category]

    def flat(self) -> dict[str, Any]:
        """{field: value} for fields that have a value."""
        out: dict[str, Any] = {}
        for name in type(self).model_fields:
            f = getattr(self, name)
            if f is not None and f.value is not None:
                out[name] = f.value
        return out

    def missing_required(self) -> list[str]:
        flat = self.flat()
        return [n for n in self.REQUIRED if n not in flat]


class OrderRequest(CategoryExtraction):
    REQUIRED = (
        "customer_name",
        "company",
        "product_skus",
        "quantities",
        "delivery_address",
        "requested_date",
    )
    CATEGORY = Category.ORDER_REQUEST
    customer_name: StrField | None = None
    company: StrField | None = None
    product_skus: StrListField | None = None
    quantities: IntListField | None = None
    delivery_address: StrField | None = None
    requested_date: StrField | None = Field(None, description="ISO date YYYY-MM-DD")
    po_number: StrField | None = None


class InvoiceQuery(CategoryExtraction):
    REQUIRED = ("invoice_number", "company", "amount", "issue_type")
    CATEGORY = Category.INVOICE_QUERY
    invoice_number: StrField | None = None
    company: StrField | None = None
    amount: FloatField | None = None
    issue_type: StrField | None = Field(None, description="|".join(i.value for i in IssueType))


class RefundOrReturn(CategoryExtraction):
    REQUIRED = ("order_number", "company", "reason", "items")
    CATEGORY = Category.REFUND_OR_RETURN
    order_number: StrField | None = None
    company: StrField | None = None
    reason: StrField | None = None
    items: StrListField | None = Field(None, description="SKUs being returned")
    amount: FloatField | None = None


class Complaint(CategoryExtraction):
    REQUIRED = ("company", "severity_signal", "description")
    CATEGORY = Category.COMPLAINT
    company: StrField | None = None
    order_number: StrField | None = None
    severity_signal: StrField | None = Field(None, description="low|medium|high")
    description: StrField | None = None


class SupplierDocument(CategoryExtraction):
    REQUIRED = ("supplier_name", "document_type", "document_number")
    CATEGORY = Category.SUPPLIER_DOCUMENT
    supplier_name: StrField | None = None
    document_type: StrField | None = Field(None, description="invoice|delivery_note|certificate")
    document_number: StrField | None = None
    amount: FloatField | None = None
    due_date: StrField | None = Field(None, description="ISO date YYYY-MM-DD")

    def missing_required(self) -> list[str]:
        missing = super().missing_required()
        doc = self.document_type.value if self.document_type else None
        if doc == "invoice":  # only invoices need an amount and a due date
            flat = self.flat()
            missing += [n for n in ("amount", "due_date") if n not in flat]
        return missing


class AccessOrItRequest(CategoryExtraction):
    REQUIRED = ("employee_name", "system", "access_level", "manager_approval")
    CATEGORY = Category.ACCESS_OR_IT_REQUEST
    employee_name: StrField | None = None
    system: StrField | None = None
    access_level: StrField | None = Field(None, description="read|write|admin")
    manager_approval: BoolField | None = None


class GeneralInquiry(CategoryExtraction):
    REQUIRED = ("topic", "question")
    CATEGORY = Category.GENERAL_INQUIRY
    topic: StrField | None = None
    question: StrField | None = None


class SpamOrIrrelevant(CategoryExtraction):
    CATEGORY = Category.SPAM_OR_IRRELEVANT


class JobApplicationUpdate(CategoryExtraction):
    REQUIRED = ("company", "status")
    CATEGORY = Category.JOB_APPLICATION_UPDATE
    company: StrField | None = None
    position: StrField | None = None
    status: StrField | None = Field(None, description="received|rejected|interview|offer|other")
    reference: StrField | None = None
    next_step: StrField | None = Field(
        None, description="What the sender asks the candidate to do next, if anything"
    )


class JobAlert(CategoryExtraction):
    CATEGORY = Category.JOB_ALERT


class NewsletterOrPromo(CategoryExtraction):
    CATEGORY = Category.NEWSLETTER_OR_PROMO


class FinanceNotice(CategoryExtraction):
    REQUIRED = ("organization", "notice_type")
    CATEGORY = Category.FINANCE_NOTICE
    organization: StrField | None = None
    notice_type: StrField | None = Field(
        None, description="payment_reminder|statement|invoice|loan|other"
    )
    amount: FloatField | None = None
    due_date: StrField | None = Field(None, description="ISO date YYYY-MM-DD")
    action_required: BoolField | None = Field(
        None, description="true if the sender expects the recipient to do something"
    )


class AccountOrSecurity(CategoryExtraction):
    REQUIRED = ("service", "notice")
    CATEGORY = Category.ACCOUNT_OR_SECURITY
    service: StrField | None = None
    notice: StrField | None = Field(
        None, description="trial_ended|password|login_alert|verification|other"
    )
    action_required: BoolField | None = None


class PersonalMessage(CategoryExtraction):
    REQUIRED = ("topic",)
    CATEGORY = Category.PERSONAL_MESSAGE
    sender_name: StrField | None = None
    topic: StrField | None = None
    request: StrField | None = Field(None, description="What the sender asks for, if anything")


SCHEMAS: dict[Category, type[CategoryExtraction]] = {
    cls.CATEGORY: cls
    for cls in (
        OrderRequest,
        InvoiceQuery,
        RefundOrReturn,
        Complaint,
        SupplierDocument,
        AccessOrItRequest,
        GeneralInquiry,
        SpamOrIrrelevant,
        JobApplicationUpdate,
        JobAlert,
        NewsletterOrPromo,
        FinanceNotice,
        AccountOrSecurity,
        PersonalMessage,
    )
}
