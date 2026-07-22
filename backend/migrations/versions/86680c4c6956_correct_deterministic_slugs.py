"""correct_deterministic_slugs

Revision ID: 86680c4c6956
Revises: f63c25949fbf
Create Date: 2026-07-07 03:23:25.900568
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import uuid


revision: str = '86680c4c6956'
down_revision: Union[str, None] = 'f63c25949fbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if not inspector.has_table("companies"):
        return
        
    metadata = sa.MetaData()
    companies_table = sa.Table(
        'companies', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('company_id', sa.String),
        sa.Column('public_chat_slug', sa.String)
    )
    
    connection = op.get_bind()
    results = connection.execute(sa.select(companies_table.c.id, companies_table.c.company_id, companies_table.c.public_chat_slug)).fetchall()
    
    generated_slugs = set()
    
    for row in results:
        comp_db_id = row[0]
        company_id = row[1]
        current_slug = row[2]
        
        needs_replacement = False
        if not current_slug:
            needs_replacement = True
        elif current_slug == f"{company_id}-chat":
            needs_replacement = True
            
        if needs_replacement:
            while True:
                new_slug = f"chat-{uuid.uuid4().hex[:16]}"
                if new_slug in generated_slugs:
                    continue
                # Check DB for collision
                exists = connection.execute(
                    sa.select(companies_table.c.id).where(companies_table.c.public_chat_slug == new_slug)
                ).fetchone()
                if not exists:
                    generated_slugs.add(new_slug)
                    break
            
            connection.execute(
                companies_table.update().where(companies_table.c.id == comp_db_id).values(public_chat_slug=new_slug)
            )


def downgrade() -> None:
    pass
