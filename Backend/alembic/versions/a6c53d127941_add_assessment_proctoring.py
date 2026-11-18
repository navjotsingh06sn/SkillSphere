"""add assessment proctoring

Revision ID: a6c53d127941
Revises: d9032b74c8a1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a6c53d127941"
down_revision: Union[str, Sequence[str], None] = "d9032b74c8a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proctoring_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "camera_permission_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("is_flagged", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", name="uq_proctoring_assessment"),
    )
    op.create_index(
        "ix_proctoring_candidate_status",
        "proctoring_sessions",
        ["candidate_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_proctoring_sessions_candidate_id",
        "proctoring_sessions",
        ["candidate_id"],
        unique=False,
    )

    op.create_table(
        "proctoring_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["proctoring_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_proctoring_event_session_time",
        "proctoring_events",
        ["session_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_proctoring_event_session_time", table_name="proctoring_events")
    op.drop_table("proctoring_events")
    op.drop_index(
        "ix_proctoring_sessions_candidate_id", table_name="proctoring_sessions"
    )
    op.drop_index(
        "ix_proctoring_candidate_status", table_name="proctoring_sessions"
    )
    op.drop_table("proctoring_sessions")
