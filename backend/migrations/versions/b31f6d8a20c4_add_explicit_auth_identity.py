"""add explicit authentication identity fields

Revision ID: b31f6d8a20c4
Revises: a7c4e2f91b30
Create Date: 2026-07-15 12:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b31f6d8a20c4"
down_revision: Union[str, None] = "a7c4e2f91b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "companies" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("companies")}
    with op.batch_alter_table("companies", schema=None) as batch_op:
        if "auth_provider" not in columns:
            batch_op.add_column(
                sa.Column("auth_provider", sa.String(length=20), server_default="password", nullable=False)
            )
        if "google_subject" not in columns:
            batch_op.add_column(sa.Column("google_subject", sa.String(length=255), nullable=True))

    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("companies")}
    if "ix_companies_google_subject" not in indexes:
        op.create_index("ix_companies_google_subject", "companies", ["google_subject"], unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "companies" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("companies")}
    indexes = {index["name"] for index in inspector.get_indexes("companies")}
    if "ix_companies_google_subject" in indexes:
        op.drop_index("ix_companies_google_subject", table_name="companies")
    with op.batch_alter_table("companies", schema=None) as batch_op:
        if "google_subject" in columns:
            batch_op.drop_column("google_subject")
        if "auth_provider" in columns:
            batch_op.drop_column("auth_provider")
