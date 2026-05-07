"""Initial schema — work_orders, audit_log, equipment_health, anomaly_scores.

Revision ID: 001
Revises:
Create Date: 2026-05-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── work_orders ──────────────────────────────────────────────────────────
    op.create_table(
        "work_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("device_class", sa.String(64), nullable=False),
        sa.Column("fault_description", sa.Text, nullable=False),
        sa.Column(
            "recommended_steps",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("parts_required", postgresql.JSONB, nullable=True),
        sa.Column("estimated_labour_hours", sa.Float, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="3"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("due_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_work_orders_entity_id", "work_orders", ["entity_id"])
    op.create_index("ix_work_orders_status", "work_orders", ["status"])

    # ── audit_log ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_id", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])

    # ── equipment_health (converted to TimescaleDB hypertable post-create) ───
    op.create_table(
        "equipment_health",
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("health_score", sa.Float, nullable=False),
        sa.Column("failure_probability", sa.Float, nullable=False),
        sa.Column("features", postgresql.JSONB, nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("entity_id", "scored_at"),
    )
    # Convert to hypertable
    op.execute(
        "SELECT create_hypertable('equipment_health', 'scored_at', if_not_exists => TRUE);"
    )

    # ── anomaly_scores (TimescaleDB hypertable) ───────────────────────────────
    op.create_table(
        "anomaly_scores",
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("sigma", sa.Float, nullable=False),
        sa.Column("triggered", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("telemetry_snapshot", postgresql.JSONB, nullable=True),
        sa.PrimaryKeyConstraint("entity_id", "scored_at"),
    )
    op.execute(
        "SELECT create_hypertable('anomaly_scores', 'scored_at', if_not_exists => TRUE);"
    )


def downgrade() -> None:
    op.drop_table("anomaly_scores")
    op.drop_table("equipment_health")
    op.drop_index("ix_audit_log_event_type", "audit_log")
    op.drop_index("ix_audit_log_entity_id", "audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_work_orders_status", "work_orders")
    op.drop_index("ix_work_orders_entity_id", "work_orders")
    op.drop_table("work_orders")
