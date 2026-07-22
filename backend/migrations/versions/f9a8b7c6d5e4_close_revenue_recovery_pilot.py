"""close the evidence-bound revenue recovery pilot loop

Revision ID: f9a8b7c6d5e4
Revises: e27a6c4d9b10
Create Date: 2026-07-19 04:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f9a8b7c6d5e4"
down_revision: Union[str, None] = "e27a6c4d9b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_current_system_events() -> None:
    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=True),
        sa.Column("uuid", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid", name="uq_system_events_uuid"),
        sa.UniqueConstraint("company_id", "event_type", "idempotency_key", name="uq_system_event_company_type_idempotency"),
    )
    op.create_index("ix_system_events_id", "system_events", ["id"])
    op.create_index("ix_system_events_company_id", "system_events", ["company_id"])
    op.create_index("ix_system_events_event_type", "system_events", ["event_type"])
    op.create_index("ix_system_events_entity_id", "system_events", ["entity_id"])
    op.create_index("ix_system_events_processed", "system_events", ["processed"])
    op.create_index("ix_system_events_created_at", "system_events", ["created_at"])
    op.create_index("ix_system_events_is_deleted", "system_events", ["is_deleted"])
    op.create_index("ix_system_event_company_type_created", "system_events", ["company_id", "event_type", "created_at"])


def _create_current_follow_up_tasks() -> None:
    op.create_table(
        "follow_up_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.String(length=64), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("task_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_identifier", sa.String(length=160), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=True),
        sa.Column("source_message_internal_id", sa.String(length=64), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="FOLLOW_UP_DUE"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suggested_message", sa.Text(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_reference", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "idempotency_key", name="uq_follow_up_company_idempotency"),
    )
    op.create_index("ix_follow_up_tasks_id", "follow_up_tasks", ["id"])
    op.create_index("ix_follow_up_tasks_company_id", "follow_up_tasks", ["company_id"])
    op.create_index("ix_follow_up_tasks_lead_id", "follow_up_tasks", ["lead_id"])
    op.create_index("ix_follow_up_tasks_source_event_id", "follow_up_tasks", ["source_event_id"])
    op.create_index("ix_follow_up_tasks_source_message_internal_id", "follow_up_tasks", ["source_message_internal_id"])
    op.create_index("ix_follow_up_tasks_status", "follow_up_tasks", ["status"])
    op.create_index("ix_follow_up_company_status_due", "follow_up_tasks", ["company_id", "status", "due_at"])
    op.create_index("ix_follow_up_company_lead_status", "follow_up_tasks", ["company_id", "lead_id", "status"])


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    system_existed = "system_events" in existing_tables
    follow_up_existed = "follow_up_tasks" in existing_tables

    if system_existed:
        with op.batch_alter_table("system_events") as batch_op:
            batch_op.add_column(sa.Column("idempotency_key", sa.String(length=160), nullable=True))
            batch_op.create_unique_constraint(
                "uq_system_event_company_type_idempotency",
                ["company_id", "event_type", "idempotency_key"],
            )
            batch_op.create_index(
                "ix_system_event_company_type_created",
                ["company_id", "event_type", "created_at"],
                unique=False,
            )
    else:
        _create_current_system_events()

    if not follow_up_existed:
        _create_current_follow_up_tasks()
        return

    with op.batch_alter_table("follow_up_tasks") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("source_type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("source_identifier", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("source_event_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_message_internal_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("reason_code", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("category", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("priority", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("completion_reference", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_follow_up_tasks_company_id_companies",
            "companies",
            ["company_id"],
            ["company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_follow_up_tasks_source_event_id_commercial_events",
            "commercial_events",
            ["source_event_id"],
            ["id"],
            ondelete="SET NULL",
        )

    rows = bind.execute(
        sa.text(
            "SELECT follow_up_tasks.id, follow_up_tasks.lead_id, leads.company_id, "
            "follow_up_tasks.task_type, follow_up_tasks.task_level, follow_up_tasks.created_at "
            "FROM follow_up_tasks LEFT JOIN leads ON leads.id = follow_up_tasks.lead_id"
        )
    ).mappings().all()
    for row in rows:
        if not row["company_id"]:
            # An orphan legacy task has no safe tenant authority and cannot be
            # surfaced. Removing it is safer than assigning fabricated ownership.
            bind.execute(sa.text("DELETE FROM follow_up_tasks WHERE id = :task_id"), {"task_id": row["id"]})
            continue
        bind.execute(
            sa.text(
                "UPDATE follow_up_tasks SET company_id = :company_id, "
                "source_type = :source_type, source_identifier = :source_identifier, "
                "reason_code = :reason_code, idempotency_key = :idempotency_key, "
                "category = :category, priority = :priority, "
                "updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE id = :task_id"
            ),
            {
                "company_id": row["company_id"],
                "source_type": "legacy_stage_sweeper",
                "source_identifier": f"legacy-follow-up:{row['id']}",
                "reason_code": str(row["task_type"] or "LEGACY_FOLLOW_UP")[:100],
                "idempotency_key": f"legacy-follow-up:{row['id']}",
                "category": "FOLLOW_UP_DUE",
                "priority": max(1, min(100, int(row["task_level"] or 1) * 25)),
                "task_id": row["id"],
            },
        )

    with op.batch_alter_table("follow_up_tasks") as batch_op:
        batch_op.alter_column("company_id", existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column("lead_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("source_type", existing_type=sa.String(length=50), nullable=False)
        batch_op.alter_column("source_identifier", existing_type=sa.String(length=160), nullable=False)
        batch_op.alter_column("reason_code", existing_type=sa.String(length=100), nullable=False)
        batch_op.alter_column("idempotency_key", existing_type=sa.String(length=160), nullable=False)
        batch_op.alter_column("category", existing_type=sa.String(length=50), nullable=False)
        batch_op.alter_column("priority", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            existing_server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        batch_op.create_unique_constraint(
            "uq_follow_up_company_idempotency",
            ["company_id", "idempotency_key"],
        )
        batch_op.create_index(
            "ix_follow_up_company_status_due",
            ["company_id", "status", "due_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_follow_up_company_lead_status",
            ["company_id", "lead_id", "status"],
            unique=False,
        )
        batch_op.create_index(
            "ix_follow_up_tasks_source_event_id",
            ["source_event_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_follow_up_tasks_source_message_internal_id",
            ["source_message_internal_id"],
            unique=False,
        )
        batch_op.create_index("ix_follow_up_tasks_status", ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("follow_up_tasks") as batch_op:
        batch_op.drop_index("ix_follow_up_tasks_status")
        batch_op.drop_index("ix_follow_up_tasks_source_message_internal_id")
        batch_op.drop_index("ix_follow_up_tasks_source_event_id")
        batch_op.drop_index("ix_follow_up_company_lead_status")
        batch_op.drop_index("ix_follow_up_company_status_due")
        batch_op.drop_constraint("uq_follow_up_company_idempotency", type_="unique")
        batch_op.drop_constraint("fk_follow_up_tasks_source_event_id_commercial_events", type_="foreignkey")
        batch_op.drop_constraint("fk_follow_up_tasks_company_id_companies", type_="foreignkey")
        batch_op.alter_column("lead_id", existing_type=sa.Integer(), nullable=True)
        for column in (
            "updated_at",
            "completion_reference",
            "snoozed_until",
            "dismissed_at",
            "completed_at",
            "priority",
            "category",
            "idempotency_key",
            "reason_code",
            "source_message_internal_id",
            "source_event_id",
            "source_identifier",
            "source_type",
            "company_id",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("system_events") as batch_op:
        batch_op.drop_index("ix_system_event_company_type_created")
        batch_op.drop_constraint("uq_system_event_company_type_idempotency", type_="unique")
        batch_op.drop_column("idempotency_key")
