"""persist versioned legal consent

Revision ID: e27a6c4d9b10
Revises: d15c8b4f2a60
Create Date: 2026-07-16 23:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e27a6c4d9b10"
down_revision: Union[str, None] = "d15c8b4f2a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("companies"):
        return set()
    return {column["name"] for column in inspector.get_columns("companies")}


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("companies"):
        return
    columns = _columns()
    with op.batch_alter_table("companies") as batch_op:
        if "terms_accepted_at" not in columns:
            batch_op.add_column(
                sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "terms_version" not in columns:
            batch_op.add_column(sa.Column("terms_version", sa.String(length=40), nullable=True))
        if "privacy_version" not in columns:
            batch_op.add_column(sa.Column("privacy_version", sa.String(length=40), nullable=True))


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("companies"):
        return
    columns = _columns()
    with op.batch_alter_table("companies") as batch_op:
        if "privacy_version" in columns:
            batch_op.drop_column("privacy_version")
        if "terms_version" in columns:
            batch_op.drop_column("terms_version")
        if "terms_accepted_at" in columns:
            batch_op.drop_column("terms_accepted_at")
