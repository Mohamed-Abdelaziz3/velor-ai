"""add_company_auto_reply_control

Revision ID: b8a1f2c4d9e0
Revises: 9c3b6a1e4f20
Create Date: 2026-07-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8a1f2c4d9e0"
down_revision: Union[str, None] = "9c3b6a1e4f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    company_columns = {col["name"] for col in inspector.get_columns("companies")}

    if "bot_auto_reply_enabled" not in company_columns:
        with op.batch_alter_table("companies") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "bot_auto_reply_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    company_columns = {col["name"] for col in inspector.get_columns("companies")}

    if "bot_auto_reply_enabled" in company_columns:
        with op.batch_alter_table("companies") as batch_op:
            batch_op.drop_column("bot_auto_reply_enabled")
