"""add lead evidence

Revision ID: 9c3b6a1e4f20
Revises: dd6a7529ebfc
Create Date: 2026-07-02 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9c3b6a1e4f20"
down_revision: Union[str, None] = "dd6a7529ebfc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str], unique: bool = False) -> None:
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if index_name not in existing_indexes:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "lead_evidence" not in existing_tables:
        op.create_table(
            "lead_evidence",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("lead_id", sa.Integer(), nullable=True),
            sa.Column("message_id", sa.Integer(), nullable=True),
            sa.Column("message_internal_id", sa.String(length=64), nullable=False),
            sa.Column("evidence_type", sa.String(length=100), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=False, server_default="message"),
            sa.Column("source_text", sa.Text(), nullable=False),
            sa.Column("normalized_value", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("evidence_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["companies.company_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "message_internal_id", "evidence_type", "evidence_hash", name="uq_lead_evidence_message_type_hash"),
        )

    _create_index_if_missing("lead_evidence", "ix_lead_evidence_id", ["id"])
    _create_index_if_missing("lead_evidence", "ix_lead_evidence_company_id", ["company_id"])
    _create_index_if_missing("lead_evidence", "ix_lead_evidence_lead_id", ["lead_id"])
    _create_index_if_missing("lead_evidence", "ix_lead_evidence_message_id", ["message_id"])
    _create_index_if_missing("lead_evidence", "ix_lead_evidence_message_internal_id", ["message_internal_id"])
    _create_index_if_missing("lead_evidence", "ix_lead_evidence_evidence_type", ["evidence_type"])
    _create_index_if_missing("lead_evidence", "ix_lead_evidence_created_at", ["created_at"])
    _create_index_if_missing("lead_evidence", "ix_lead_evidence_company_type_created", ["company_id", "evidence_type", "created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "lead_evidence" in set(inspector.get_table_names()):
        op.drop_table("lead_evidence")
