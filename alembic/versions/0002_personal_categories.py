"""add personal-inbox categories to the category enum

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

NEW = (
    "job_application_update",
    "job_alert",
    "newsletter_or_promo",
    "finance_notice",
    "account_or_security",
    "personal_message",
)


def upgrade() -> None:
    # PostgreSQL 12+ allows ADD VALUE inside a transaction (the value just can't be used in the same one).
    for value in NEW:
        op.execute(f"ALTER TYPE category ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL cannot drop enum values; the extra values are harmless and 0001's downgrade drops the type.
    pass
