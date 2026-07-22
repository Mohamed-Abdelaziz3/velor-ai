"""Initial schema — all tables

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("uuid", sa.String(36), unique=True),
        sa.Column("company_id", sa.String(64), unique=True, nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(254), unique=True, nullable=False),
        sa.Column("password", sa.String(256), nullable=False),
        sa.Column("api_key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("role", sa.String(20), server_default="tenant"),
        sa.Column("plan", sa.String(20), server_default="FREE"),
        sa.Column("is_deleted", sa.Boolean, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_company_api_deleted", "companies", ["api_key_hash", "is_deleted"])
    op.create_index("ix_company_email_deleted", "companies", ["email", "is_deleted"])

    op.create_table(
        "company_knowledge",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("uuid", sa.String(36), unique=True),
        sa.Column("company_id", sa.String(64), sa.ForeignKey("companies.company_id", ondelete="CASCADE"), unique=True),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("products_data", sa.Text, nullable=False),
        sa.Column("is_deleted", sa.Boolean, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("uuid", sa.String(36), unique=True),
        sa.Column("company_id", sa.String(64), sa.ForeignKey("companies.company_id", ondelete="CASCADE")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("interest", sa.Text, nullable=True),
        sa.Column("is_deleted", sa.Boolean, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "phone", name="_company_phone_uc"),
    )
    op.create_index("ix_lead_company_phone_deleted", "leads", ["company_id", "phone", "is_deleted"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("uuid", sa.String(36), unique=True),
        sa.Column("company_id", sa.String(64), sa.ForeignKey("companies.company_id", ondelete="CASCADE")),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("sender", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("is_deleted", sa.Boolean, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conv_company_user_ts", "conversations", ["company_id", "user_id", "created_at"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.String(64), sa.ForeignKey("companies.company_id", ondelete="CASCADE")),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rt_active_lookup", "refresh_tokens", ["token_hash", "revoked", "expires_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.String(64), sa.ForeignKey("companies.company_id", ondelete="CASCADE"), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_created", "audit_logs", ["created_at"])

    op.create_table(
        "usage_stats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.String(64), sa.ForeignKey("companies.company_id", ondelete="CASCADE"), unique=True),
        sa.Column("messages_count", sa.Integer, server_default="0"),
        sa.Column("leads_count", sa.Integer, server_default="0"),
        sa.Column("requests_count", sa.Integer, server_default="0"),
        sa.Column("current_month", sa.String(7), nullable=False),
        sa.Column("monthly_messages", sa.Integer, server_default="0"),
        sa.Column("monthly_leads", sa.Integer, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in ["usage_stats", "audit_logs", "refresh_tokens", "conversations", "leads", "company_knowledge", "companies"]:
        op.drop_table(table)
