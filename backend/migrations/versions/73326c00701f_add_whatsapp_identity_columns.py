"""add_whatsapp_identity_columns

Revision ID: 73326c00701f
Revises: 581d7b7859b1
Create Date: 2026-06-24 21:48:03.896060
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "73326c00701f"
down_revision: Union[str, None] = "581d7b7859b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("whatsapp_number", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("whatsapp_jid", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("customer_provided_phone", sa.String(length=20), nullable=True))
        batch_op.create_index(batch_op.f("ix_leads_whatsapp_number"), ["whatsapp_number"], unique=False)
        batch_op.create_unique_constraint("_company_whatsapp_uc", ["company_id", "whatsapp_number"])
        batch_op.create_index("ix_lead_company_whatsapp_deleted", ["company_id", "whatsapp_number", "is_deleted"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_index("ix_lead_company_whatsapp_deleted")
        batch_op.drop_constraint("_company_whatsapp_uc", type_="unique")
        batch_op.drop_index(batch_op.f("ix_leads_whatsapp_number"))
        batch_op.drop_column("customer_provided_phone")
        batch_op.drop_column("whatsapp_jid")
        batch_op.drop_column("whatsapp_number")
