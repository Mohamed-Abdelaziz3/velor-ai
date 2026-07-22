"""add durable webhook inbox

Revision ID: d15c8b4f2a60
Revises: c42f9a7e1d30
Create Date: 2026-07-16 21:25:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d15c8b4f2a60"
down_revision: Union[str, None] = "c42f9a7e1d30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("webhook_inbox"):
        return

    op.create_table(
        "webhook_inbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=True),
        sa.Column("company_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_category", sa.String(length=120), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.company_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_inbox_provider", "webhook_inbox", ["provider"])
    op.create_index("ix_webhook_inbox_payload_hash", "webhook_inbox", ["payload_hash"], unique=True)
    op.create_index("ix_webhook_inbox_provider_event_id", "webhook_inbox", ["provider_event_id"])
    op.create_index("ix_webhook_inbox_company_id", "webhook_inbox", ["company_id"])
    op.create_index("ix_webhook_inbox_status", "webhook_inbox", ["status"])
    op.create_index("ix_webhook_inbox_status_created", "webhook_inbox", ["status", "created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("webhook_inbox"):
        op.drop_table("webhook_inbox")
