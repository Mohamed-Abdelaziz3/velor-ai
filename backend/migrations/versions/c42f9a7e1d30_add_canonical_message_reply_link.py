"""add canonical message reply link

Revision ID: c42f9a7e1d30
Revises: b31f6d8a20c4
Create Date: 2026-07-16 21:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c42f9a7e1d30"
down_revision: Union[str, None] = "b31f6d8a20c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if "in_reply_to_message_id" not in _columns("messages"):
        with op.batch_alter_table("messages") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "in_reply_to_message_id",
                    sa.Integer(),
                    nullable=True,
                )
            )
            batch_op.create_foreign_key(
                "fk_messages_in_reply_to_message_id_messages",
                "messages",
                ["in_reply_to_message_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if "ix_messages_in_reply_to_message_id" not in _indexes("messages"):
        op.create_index(
            "ix_messages_in_reply_to_message_id",
            "messages",
            ["in_reply_to_message_id"],
            unique=True,
        )


def downgrade() -> None:
    if "ix_messages_in_reply_to_message_id" in _indexes("messages"):
        op.drop_index(
            "ix_messages_in_reply_to_message_id",
            table_name="messages",
        )
    if "in_reply_to_message_id" in _columns("messages"):
        with op.batch_alter_table("messages") as batch_op:
            batch_op.drop_constraint(
                "fk_messages_in_reply_to_message_id_messages",
                type_="foreignkey",
            )
            batch_op.drop_column("in_reply_to_message_id")
