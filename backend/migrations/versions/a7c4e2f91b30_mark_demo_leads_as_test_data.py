"""mark demo-tenant leads as test data

Revision ID: a7c4e2f91b30
Revises: 9f8e7d6c5b4a
Create Date: 2026-07-15 12:00:00.000000

Demo rows must never contribute to merchant-facing metrics. This migration
classifies historical fixtures that predate the explicit ``is_test`` write
boundary. The downgrade is intentionally a no-op: reverting code must not
silently turn synthetic evidence back into production evidence.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7c4e2f91b30"
down_revision: Union[str, None] = "9f8e7d6c5b4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "leads" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("leads")}
    if not {"company_id", "is_test"}.issubset(columns):
        return

    leads = sa.table(
        "leads",
        sa.column("company_id", sa.String()),
        sa.column("is_test", sa.Boolean()),
    )
    op.execute(
        leads.update()
        .where(
            sa.or_(
                leads.c.company_id.like("velor_demo_%"),
                leads.c.company_id == "velor_commercial_intelligence_demo",
            )
        )
        .values(is_test=True)
    )


def downgrade() -> None:
    pass
