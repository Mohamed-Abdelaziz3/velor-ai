"""add commercial execution lineage and deterministic events

Revision ID: d4f6a8b0c2e4
Revises: b7a9d3e4c2f1
Create Date: 2026-07-10 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4f6a8b0c2e4"
down_revision: Union[str, None] = "b7a9d3e4c2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "commercial_decision_lineage" not in tables:
        op.create_table(
            "commercial_decision_lineage",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("lead_id", sa.Integer(), nullable=False),
            sa.Column("source_message_id", sa.Integer(), nullable=True),
            sa.Column("source_message_internal_id", sa.String(length=64), nullable=False),
            sa.Column("objective", sa.String(length=80), nullable=False),
            sa.Column("strategy", sa.String(length=80), nullable=False),
            sa.Column("next_move", sa.String(length=80), nullable=False),
            sa.Column("decision_json", sa.Text(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("escalation_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("escalation_json", sa.Text(), nullable=True),
            sa.Column("observed_outcome", sa.String(length=80), nullable=True),
            sa.Column("outcome_evidence_json", sa.Text(), nullable=True),
            sa.Column("outcome_observed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["companies.company_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "source_message_internal_id", name="uq_commercial_decision_source_message"),
        )
        op.create_index("ix_commercial_decision_company_created", "commercial_decision_lineage", ["company_id", "created_at"])
        op.create_index("ix_commercial_decision_lead_created", "commercial_decision_lineage", ["lead_id", "created_at"])
        for name, columns in (
            ("ix_commercial_decision_lineage_company_id", ["company_id"]),
            ("ix_commercial_decision_lineage_lead_id", ["lead_id"]),
            ("ix_commercial_decision_lineage_source_message_id", ["source_message_id"]),
            ("ix_commercial_decision_lineage_source_message_internal_id", ["source_message_internal_id"]),
            ("ix_commercial_decision_lineage_objective", ["objective"]),
            ("ix_commercial_decision_lineage_strategy", ["strategy"]),
            ("ix_commercial_decision_lineage_escalation_required", ["escalation_required"]),
            ("ix_commercial_decision_lineage_observed_outcome", ["observed_outcome"]),
            ("ix_commercial_decision_lineage_created_at", ["created_at"]),
        ):
            op.create_index(name, "commercial_decision_lineage", columns)

    if "commercial_events" not in tables:
        op.create_table(
            "commercial_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("lead_id", sa.Integer(), nullable=False),
            sa.Column("message_id", sa.Integer(), nullable=True),
            sa.Column("source_message_internal_id", sa.String(length=64), nullable=False),
            sa.Column("channel", sa.String(length=50), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("product_ref", sa.String(length=240), nullable=True),
            sa.Column("stage", sa.String(length=80), nullable=True),
            sa.Column("objection_type", sa.String(length=80), nullable=True),
            sa.Column("source_text", sa.Text(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("provenance", sa.String(length=80), nullable=False, server_default="deterministic_v1"),
            sa.Column("event_hash", sa.String(length=64), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["companies.company_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "event_hash", name="uq_commercial_event_hash"),
        )
        op.create_index("ix_commercial_event_company_type_observed", "commercial_events", ["company_id", "event_type", "observed_at"])
        op.create_index("ix_commercial_event_company_product_observed", "commercial_events", ["company_id", "product_ref", "observed_at"])
        op.create_index("ix_commercial_event_lead_observed", "commercial_events", ["lead_id", "observed_at"])
        for name, columns in (
            ("ix_commercial_events_company_id", ["company_id"]),
            ("ix_commercial_events_lead_id", ["lead_id"]),
            ("ix_commercial_events_message_id", ["message_id"]),
            ("ix_commercial_events_source_message_internal_id", ["source_message_internal_id"]),
            ("ix_commercial_events_event_type", ["event_type"]),
            ("ix_commercial_events_product_ref", ["product_ref"]),
            ("ix_commercial_events_stage", ["stage"]),
            ("ix_commercial_events_objection_type", ["objection_type"]),
            ("ix_commercial_events_observed_at", ["observed_at"]),
        ):
            op.create_index(name, "commercial_events", columns)


def downgrade() -> None:
    tables = _tables()
    if "commercial_events" in tables:
        op.drop_table("commercial_events")
    if "commercial_decision_lineage" in tables:
        op.drop_table("commercial_decision_lineage")
