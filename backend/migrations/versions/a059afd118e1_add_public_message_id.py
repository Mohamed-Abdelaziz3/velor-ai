"""add_public_message_id

Revision ID: a059afd118e1
Revises: 86680c4c6956
Create Date: 2026-07-07 03:52:26.567907
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import uuid


revision: str = 'a059afd118e1'
down_revision: Union[str, None] = '86680c4c6956'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if not inspector.has_table("messages"):
        return
        
    # Add column
    op.add_column("messages", sa.Column("public_message_id", sa.String(length=64), nullable=True))
    
    metadata = sa.MetaData()
    messages_table = sa.Table(
        'messages', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('public_message_id', sa.String)
    )
    
    connection = op.get_bind()
    results = connection.execute(sa.select(messages_table.c.id)).fetchall()
    
    generated_ids = set()
    for row in results:
        msg_db_id = row[0]
        while True:
            new_id = f"pub-{uuid.uuid4().hex}"
            if new_id in generated_ids:
                continue
            # Check DB for collision (just in case)
            exists = connection.execute(
                sa.select(messages_table.c.id).where(messages_table.c.public_message_id == new_id)
            ).fetchone()
            if not exists:
                generated_ids.add(new_id)
                break
            
        connection.execute(
            messages_table.update().where(messages_table.c.id == msg_db_id).values(public_message_id=new_id)
        )
        
    # Create the index
    op.create_index("ix_messages_public_message_id", "messages", ["public_message_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_messages_public_message_id", table_name="messages")
    op.drop_column("messages", "public_message_id")
