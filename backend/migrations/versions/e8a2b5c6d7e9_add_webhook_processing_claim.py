"""add_webhook_processing_claim

Revision ID: e8a2b5c6d7e9
Revises: c4d2f8a7b1e6
Create Date: 2026-07-05 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e8a2b5c6d7e9"
down_revision: Union[str, None] = "c4d2f8a7b1e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    message_columns = {col["name"] for col in inspector.get_columns("messages")}

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
            batch_op.add_column(
                sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "processing_completed_at" not in message_columns:
            batch_op.add_column(
                sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "processing_attempts" not in message_columns:
            batch_op.add_column(
                sa.Column(
                    "processing_attempts",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )

    # Re-inspect to see if index needs creation
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("messages")}
    if "ix_messages_processing_status" not in existing_indexes:
        op.create_index("ix_messages_processing_status", "messages", ["processing_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    message_columns = {col["name"] for col in inspector.get_columns("messages")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("messages")}

    if "ix_messages_processing_status" in existing_indexes:
        op.drop_index("ix_messages_processing_status", table_name="messages")

    with op.batch_alter_table("messages") as batch_op:
        if "processing_attempts" in message_columns:
            batch_op.drop_column("processing_attempts")
        if "processing_completed_at" in message_columns:
            batch_op.drop_column("processing_completed_at")
        if "processing_started_at" in message_columns:
            batch_op.drop_column("processing_started_at")
        if "processing_status" in message_columns:
            batch_op.drop_column("processing_status")
