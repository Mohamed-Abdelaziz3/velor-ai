"""repair_web_chat_runtime_schema

Revision ID: b7a9d3e4c2f1
Revises: a059afd118e1
Create Date: 2026-07-09 03:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7a9d3e4c2f1"
down_revision: Union[str, None] = "a059afd118e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    lead_columns = _columns("leads")
    if lead_columns and "sales_state_snapshot" not in lead_columns:
        with op.batch_alter_table("leads") as batch_op:
            batch_op.add_column(sa.Column("sales_state_snapshot", sa.Text(), nullable=True))

    message_columns = _columns("messages")
    if message_columns:
        with op.batch_alter_table("messages") as batch_op:
            if "processing_status" not in message_columns:
                batch_op.add_column(
                    sa.Column(
                        "processing_status",
                        sa.String(length=30),
                        nullable=False,
                        server_default="completed",
                    )
                )
            if "processing_started_at" not in message_columns:
                batch_op.add_column(sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
            if "processing_completed_at" not in message_columns:
                batch_op.add_column(sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True))
            if "processing_attempts" not in message_columns:
                batch_op.add_column(
                    sa.Column(
                        "processing_attempts",
                        sa.Integer(),
                        nullable=False,
                        server_default="0",
                    )
                )

        if "ix_messages_processing_status" not in _indexes("messages"):
            op.create_index("ix_messages_processing_status", "messages", ["processing_status"])


def downgrade() -> None:
    if "ix_messages_processing_status" in _indexes("messages"):
        op.drop_index("ix_messages_processing_status", table_name="messages")

    message_columns = _columns("messages")
    if message_columns:
        with op.batch_alter_table("messages") as batch_op:
            if "processing_attempts" in message_columns:
                batch_op.drop_column("processing_attempts")
            if "processing_completed_at" in message_columns:
                batch_op.drop_column("processing_completed_at")
            if "processing_started_at" in message_columns:
                batch_op.drop_column("processing_started_at")
            if "processing_status" in message_columns:
                batch_op.drop_column("processing_status")

    lead_columns = _columns("leads")
    if "sales_state_snapshot" in lead_columns:
        with op.batch_alter_table("leads") as batch_op:
            batch_op.drop_column("sales_state_snapshot")
