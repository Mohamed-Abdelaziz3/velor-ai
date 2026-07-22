"""make_phone_nullable_and_add_web_chat_enabled

Revision ID: f63c25949fbf
Revises: e8a2b5c6d7e9
Create Date: 2026-07-07 02:09:08.141553
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f63c25949fbf'
down_revision: Union[str, None] = 'e8a2b5c6d7e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # 1. Update companies table
    company_columns = {col["name"] for col in inspector.get_columns("companies")}
    with op.batch_alter_table("companies") as batch_op:
        if "is_web_chat_enabled" not in company_columns:
            batch_op.add_column(
                sa.Column("is_web_chat_enabled", sa.Boolean(), nullable=False, server_default="0")
            )
        if "public_chat_slug" not in company_columns:
            batch_op.add_column(
                sa.Column("public_chat_slug", sa.String(length=100), nullable=True)
            )
            
    # Generate unique slugs for existing companies before creating index/unique constraint
    metadata = sa.MetaData()
    companies_table = sa.Table(
        'companies', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('company_id', sa.String),
        sa.Column('public_chat_slug', sa.String)
    )
    
    import uuid
    connection = op.get_bind()
    results = connection.execute(sa.select(companies_table.c.id, companies_table.c.company_id)).fetchall()
    generated_slugs = set()
    for row in results:
        while True:
            slug = f"chat-{uuid.uuid4().hex[:16]}"
            if slug in generated_slugs:
                continue
            exists = connection.execute(
                sa.select(companies_table.c.id).where(companies_table.c.public_chat_slug == slug)
            ).fetchone()
            if not exists:
                generated_slugs.add(slug)
                break
        connection.execute(
            companies_table.update().where(companies_table.c.id == row[0]).values(public_chat_slug=slug)
        )

    # Now create the index
    with op.batch_alter_table("companies") as batch_op:
        if "public_chat_slug" not in company_columns:
            batch_op.create_index("ix_companies_public_chat_slug", ["public_chat_slug"], unique=True)
            
    # 2. Update leads table
    lead_columns = {col["name"] for col in inspector.get_columns("leads")}
    with op.batch_alter_table("leads") as batch_op:
        if "phone" in lead_columns:
            batch_op.alter_column("phone", existing_type=sa.String(length=20), nullable=True)
        if "channel_type" not in lead_columns:
            batch_op.add_column(
                sa.Column("channel_type", sa.String(length=50), nullable=False, server_default="WHATSAPP_QR")
            )
        if "external_customer_id" not in lead_columns:
            batch_op.add_column(
                sa.Column("external_customer_id", sa.String(length=100), nullable=True)
            )
        
        # Add the unique constraint on (company_id, channel_type, external_customer_id)
        batch_op.create_unique_constraint("_company_channel_customer_uc", ["company_id", "channel_type", "external_customer_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # 1. Downgrade companies table
    company_columns = {col["name"] for col in inspector.get_columns("companies")}
    with op.batch_alter_table("companies") as batch_op:
        if "is_web_chat_enabled" in company_columns:
            batch_op.drop_column("is_web_chat_enabled")
        if "public_chat_slug" in company_columns:
            batch_op.drop_index("ix_companies_public_chat_slug")
            batch_op.drop_column("public_chat_slug")
            
    # 2. Downgrade leads table
    lead_columns = {col["name"] for col in inspector.get_columns("leads")}
    with op.batch_alter_table("leads") as batch_op:
        if "channel_type" in lead_columns:
            batch_op.drop_constraint("_company_channel_customer_uc", type_="unique")
            batch_op.drop_column("channel_type")
        if "external_customer_id" in lead_columns:
            batch_op.drop_column("external_customer_id")
        if "phone" in lead_columns:
            batch_op.alter_column("phone", existing_type=sa.String(length=20), nullable=False, server_default="")
