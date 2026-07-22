"""add pending_question to leads

Revision ID: 9f8e7d6c5b4a
Revises: f4a1b2c3d4e5
Create Date: 2026-07-13 12:00:00.000000
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "9f8e7d6c5b4a"
down_revision: Union[str, None] = "f4a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "leads" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("leads")}
        if "pending_question" not in columns:
            with op.batch_alter_table("leads", schema=None) as batch_op:
                batch_op.add_column(sa.Column("pending_question", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "leads" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("leads")}
        if "pending_question" in columns:
            with op.batch_alter_table("leads", schema=None) as batch_op:
                batch_op.drop_column("pending_question")
