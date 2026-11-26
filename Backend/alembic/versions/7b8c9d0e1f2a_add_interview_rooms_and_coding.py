"""add in-platform interview rooms, live coding, and reports"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7b8c9d0e1f2a"
down_revision: Union[str, Sequence[str], None] = "6a7b8c9d0e1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interviews", sa.Column("room_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interviews", sa.Column("room_ended_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "interview_room_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("interview_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_interview_room_events_interview_time", "interview_room_events", ["interview_id", "occurred_at"])
    op.create_table(
        "interview_coding_problems",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("interview_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("allowed_languages", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=False, server_default="1800"),
        sa.Column("test_cases", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_interview_coding_problem_interview", "interview_coding_problems", ["interview_id"])
    op.create_table(
        "interview_code_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("interview_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("problem_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interview_coding_problems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_interview_code_submissions_interview_time", "interview_code_submissions", ["interview_id", "created_at"])
    op.create_table(
        "interview_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("interview_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recruiter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("strengths", sa.Text(), nullable=True),
        sa.Column("improvement_areas", sa.Text(), nullable=True),
        sa.Column("private_notes", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("interview_id", name="uq_interview_feedback_interview"),
    )


def downgrade() -> None:
    op.drop_table("interview_feedback")
    op.drop_index("ix_interview_code_submissions_interview_time", table_name="interview_code_submissions")
    op.drop_table("interview_code_submissions")
    op.drop_index("ix_interview_coding_problem_interview", table_name="interview_coding_problems")
    op.drop_table("interview_coding_problems")
    op.drop_index("ix_interview_room_events_interview_time", table_name="interview_room_events")
    op.drop_table("interview_room_events")
    op.drop_column("interviews", "room_ended_at")
    op.drop_column("interviews", "room_started_at")
