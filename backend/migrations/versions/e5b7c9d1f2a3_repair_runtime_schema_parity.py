"""repair runtime schema parity

Revision ID: e5b7c9d1f2a3
Revises: d4f6a8b0c2e4
Create Date: 2026-07-11 21:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5b7c9d1f2a3"
down_revision: Union[str, None] = "d4f6a8b0c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if _column_names("company_knowledge") and "google_sheet_webhook_url" not in _column_names("company_knowledge"):
        with op.batch_alter_table("company_knowledge") as batch_op:
            batch_op.add_column(sa.Column("google_sheet_webhook_url", sa.String(length=500), nullable=True))

    if _column_names("refresh_tokens") and "updated_at" not in _column_names("refresh_tokens"):
        with op.batch_alter_table("refresh_tokens") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                )
            )


def downgrade() -> None:
    if _column_names("refresh_tokens") and "updated_at" in _column_names("refresh_tokens"):
        with op.batch_alter_table("refresh_tokens") as batch_op:
            batch_op.drop_column("updated_at")

    if _column_names("company_knowledge") and "google_sheet_webhook_url" in _column_names("company_knowledge"):
        with op.batch_alter_table("company_knowledge") as batch_op:
            batch_op.drop_column("google_sheet_webhook_url")
