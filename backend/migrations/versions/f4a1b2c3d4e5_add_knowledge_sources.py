"""add reviewable tenant-scoped knowledge sources

Revision ID: f4a1b2c3d4e5
Revises: e5b7c9d1f2a3
Create Date: 2026-07-13 02:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4a1b2c3d4e5"
down_revision: Union[str, None] = "e5b7c9d1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "knowledge_sources" not in inspector.get_table_names():
        op.create_table(
            "knowledge_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.String(length=64), sa.ForeignKey("companies.company_id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_name", sa.String(length=160), nullable=False),
            sa.Column("source_type", sa.String(length=30), nullable=False),
            sa.Column("mime_type", sa.String(length=120), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="processed"),
            sa.Column("extracted_text", sa.Text(), nullable=False),
            sa.Column("extracted_char_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("error_category", sa.String(length=80), nullable=True),
            sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("uuid", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_knowledge_sources_company_id", "knowledge_sources", ["company_id"])
        op.create_index("ix_knowledge_sources_status", "knowledge_sources", ["status"])
        op.create_index("ix_knowledge_sources_active", "knowledge_sources", ["active"])
        op.create_index("ix_knowledge_sources_uuid", "knowledge_sources", ["uuid"], unique=True)
        op.create_index("ix_knowledge_sources_created_at", "knowledge_sources", ["created_at"])
        op.create_index("ix_knowledge_sources_is_deleted", "knowledge_sources", ["is_deleted"])
        op.create_index(
            "ix_knowledge_source_company_active_updated",
            "knowledge_sources",
            ["company_id", "active", "updated_at"],
        )

    inspector = sa.inspect(op.get_bind())
    if "workspace_suggested_replies" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("workspace_suggested_replies")}
        additions = (
            ("style", sa.Column("style", sa.String(length=40), nullable=False, server_default="natural")),
            ("context_version", sa.Column("context_version", sa.String(length=40), nullable=False, server_default="v2")),
            ("fact_ids_used", sa.Column("fact_ids_used", sa.Text(), nullable=False, server_default="[]")),
            ("variants_json", sa.Column("variants_json", sa.Text(), nullable=False, server_default="[]")),
            ("stale_reason", sa.Column("stale_reason", sa.String(length=80), nullable=True)),
        )
        with op.batch_alter_table("workspace_suggested_replies") as batch_op:
            for name, column in additions:
                if name not in columns:
                    batch_op.add_column(column)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "workspace_suggested_replies" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("workspace_suggested_replies")}
        with op.batch_alter_table("workspace_suggested_replies") as batch_op:
            for name in ("stale_reason", "variants_json", "fact_ids_used", "context_version", "style"):
                if name in columns:
                    batch_op.drop_column(name)
    inspector = sa.inspect(op.get_bind())
    if "knowledge_sources" in inspector.get_table_names():
        op.drop_table("knowledge_sources")
