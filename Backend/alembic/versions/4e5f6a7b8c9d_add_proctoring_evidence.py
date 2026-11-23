"""add private assessment proctoring evidence metadata"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "4e5f6a7b8c9d"
down_revision: Union[str, Sequence[str], None] = "3a4b5c6d7e8f"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "proctoring_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recruiter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("capture_type", sa.String(20), nullable=False),
        sa.Column("storage_path", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(100), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["proctoring_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recruiter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["proctoring_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_proctoring_evidence_session_time", "proctoring_evidence", ["session_id", "captured_at"])
    op.create_index("ix_proctoring_evidence_assessment_id", "proctoring_evidence", ["assessment_id"])
    op.create_index("ix_proctoring_evidence_candidate_id", "proctoring_evidence", ["candidate_id"])
    op.create_index("ix_proctoring_evidence_recruiter_id", "proctoring_evidence", ["recruiter_id"])

def downgrade() -> None:
    op.drop_index("ix_proctoring_evidence_recruiter_id", table_name="proctoring_evidence")
    op.drop_index("ix_proctoring_evidence_candidate_id", table_name="proctoring_evidence")
    op.drop_index("ix_proctoring_evidence_assessment_id", table_name="proctoring_evidence")
    op.drop_index("ix_proctoring_evidence_session_time", table_name="proctoring_evidence")
    op.drop_table("proctoring_evidence")
