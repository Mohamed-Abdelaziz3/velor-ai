"""add_workspace_suggested_replies

Revision ID: c4d2f8a7b1e6
Revises: b8a1f2c4d9e0
Create Date: 2026-07-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d2f8a7b1e6"
down_revision: Union[str, None] = "b8a1f2c4d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "workspace_suggested_replies" not in tables:
        op.create_table(
            "workspace_suggested_replies",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("lead_id", sa.Integer(), nullable=False),
            sa.Column("source_message_id", sa.Integer(), nullable=True),
            sa.Column("source_message_internal_id", sa.String(length=64), nullable=False),
            sa.Column("suggested_reply", sa.Text(), nullable=False),
            sa.Column("why_this_reply", sa.Text(), nullable=True),
            sa.Column("evidence_summary", sa.Text(), nullable=True),
            sa.Column("missing_data", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="suggested"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["companies.company_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "source_message_internal_id", name="uq_workspace_suggestion_source_message"),
        )
        op.create_index(op.f("ix_workspace_suggested_replies_company_id"), "workspace_suggested_replies", ["company_id"], unique=False)
        op.create_index(op.f("ix_workspace_suggested_replies_id"), "workspace_suggested_replies", ["id"], unique=False)
        op.create_index(op.f("ix_workspace_suggested_replies_lead_id"), "workspace_suggested_replies", ["lead_id"], unique=False)
        op.create_index(op.f("ix_workspace_suggested_replies_source_message_id"), "workspace_suggested_replies", ["source_message_id"], unique=False)
        op.create_index(
            op.f("ix_workspace_suggested_replies_source_message_internal_id"),
            "workspace_suggested_replies",
            ["source_message_internal_id"],
            unique=False,
        )
        op.create_index(op.f("ix_workspace_suggested_replies_status"), "workspace_suggested_replies", ["status"], unique=False)
        op.create_index(
            "ix_workspace_suggestions_lead_status_created",
            "workspace_suggested_replies",
            ["lead_id", "status", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "workspace_suggested_replies" in tables:
        op.drop_index("ix_workspace_suggestions_lead_status_created", table_name="workspace_suggested_replies")
        op.drop_index(op.f("ix_workspace_suggested_replies_status"), table_name="workspace_suggested_replies")
        op.drop_index(op.f("ix_workspace_suggested_replies_source_message_internal_id"), table_name="workspace_suggested_replies")
        op.drop_index(op.f("ix_workspace_suggested_replies_source_message_id"), table_name="workspace_suggested_replies")
        op.drop_index(op.f("ix_workspace_suggested_replies_lead_id"), table_name="workspace_suggested_replies")
        op.drop_index(op.f("ix_workspace_suggested_replies_id"), table_name="workspace_suggested_replies")
        op.drop_index(op.f("ix_workspace_suggested_replies_company_id"), table_name="workspace_suggested_replies")
        op.drop_table("workspace_suggested_replies")
