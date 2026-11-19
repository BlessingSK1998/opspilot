"""SQLAlchemy 2.0 ORM models for OpsPilot."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from opspilot.schemas.enums import (
    Category,
    DraftKind,
    InvoiceStatus,
    OrderStatus,
    Priority,
    ReviewAction,
    RunStatus,
    TaskStatus,
)

# JSONB on Postgres, plain JSON elsewhere (unit tests may use SQLite).
JsonType = JSON().with_variant(JSONB(), "postgresql")


def _enum[E: StrEnum](cls: type[E]) -> Enum:
    return Enum(cls, name=cls.__name__.lower(), values_callable=lambda e: [m.value for m in e])


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JsonType, list[Any]: JsonType}


# --------------------------------------------------------------------------
# Reference data (stand-in for Northwind's ERP)
# --------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # C-1001
    name: Mapped[str] = mapped_column(String(200), unique=True)
    contact_name: Mapped[str] = mapped_column(String(120))
    contact_email: Mapped[str] = mapped_column(String(200), index=True)
    email_domain: Mapped[str] = mapped_column(String(120), index=True)
    delivery_address: Mapped[str] = mapped_column(String(300))
    vip: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)


class Product(Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(16), primary_key=True)  # NW-1001
    name: Mapped[str] = mapped_column(String(200))
    family: Mapped[str] = mapped_column(String(60), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    stock: Mapped[int] = mapped_column(Integer)


class Order(Base):
    __tablename__ = "orders"

    order_number: Mapped[str] = mapped_column(String(20), primary_key=True)  # SO-2026-00001
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    order_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus))
    delivery_address: Mapped[str] = mapped_column(String(300))
    # [{"sku": "NW-1001", "qty": 10, "unit_price": 0.42}] — see DECISIONS.md #6
    lines: Mapped[list[Any]]
    total_net: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Invoice(Base):
    __tablename__ = "invoices"

    invoice_number: Mapped[str] = mapped_column(String(20), primary_key=True)  # INV-2026-00001
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    order_number: Mapped[str] = mapped_column(ForeignKey("orders.order_number"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # gross incl. 19% VAT
    issued_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[InvoiceStatus] = mapped_column(_enum(InvoiceStatus))


class SlaPolicy(Base):
    __tablename__ = "sla_policies"

    priority: Mapped[Priority] = mapped_column(_enum(Priority), primary_key=True)
    first_response_hours: Mapped[int] = mapped_column(Integer)
    resolution_hours: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))


# --------------------------------------------------------------------------
# Pipeline data
# --------------------------------------------------------------------------
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    external_id: Mapped[str | None] = mapped_column(String(120))
    thread_id: Mapped[str] = mapped_column(String(120), index=True)
    sender: Mapped[str] = mapped_column(String(200), index=True)
    sender_name: Mapped[str | None] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    thread_message_count: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)  # idempotency key
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    attachments: Mapped[list["Attachment"]] = relationship(back_populates="message")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)

    message: Mapped[Message] = relationship(back_populates="attachments")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), index=True)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_state: Mapped[dict[str, Any] | None]


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), unique=True)
    category: Mapped[Category] = mapped_column(_enum(Category), index=True)
    confidence: Mapped[float]
    rationale: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict[str, Any]]  # {name: {value, confidence, source_span}}
    missing_fields: Mapped[list[Any]]
    validation_issues: Mapped[list[Any]]


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[DraftKind] = mapped_column(_enum(DraftKind))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    sent: Mapped[bool] = mapped_column(Boolean, default=False)  # never set by the system
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_status_priority", "status", "priority"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), unique=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), index=True)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drafts.id"))
    category: Mapped[Category] = mapped_column(_enum(Category), index=True)
    priority: Mapped[Priority] = mapped_column(_enum(Priority))
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus))
    assignee_team: Mapped[str] = mapped_column(String(60), index=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    escalation_reasons: Mapped[list[Any]]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(120))
    action: Mapped[ReviewAction] = mapped_column(_enum(ReviewAction))
    edits_diff: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_run_ts", "run_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"))
    node: Mapped[str] = mapped_column(String(60), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    output_summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"), index=True)
    channel: Mapped[str] = mapped_column(String(40))  # db | slack
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
