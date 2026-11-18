"""add round 1 cloudinary recordings

Revision ID: c84e1d6a9012
Revises: a6c53d127941
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c84e1d6a9012"
down_revision: Union[str, Sequence[str], None] = "a6c53d127941"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("proctoring_sessions", sa.Column("recording_consented_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "assessment_recordings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recruiter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recording_type", sa.String(length=30), nullable=False),
        sa.Column("cloudinary_public_id", sa.String(length=500), nullable=False),
        sa.Column("cloudinary_asset_id", sa.String(length=100), nullable=True),
        sa.Column("resource_type", sa.String(length=20), nullable=False),
        sa.Column("delivery_type", sa.String(length=30), nullable=False),
        sa.Column("format", sa.String(length=30), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("upload_status", sa.String(length=30), nullable=False),
        sa.Column("upload_error", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recruiter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "recording_type", name="uq_assessment_recording_type"),
        sa.UniqueConstraint("cloudinary_public_id", name="uq_assessment_recording_cloudinary_public_id"),
        sa.UniqueConstraint("cloudinary_asset_id", name="uq_assessment_recording_cloudinary_asset_id"),
    )
    op.create_index("ix_assessment_recordings_assessment_id", "assessment_recordings", ["assessment_id"])
    op.create_index("ix_assessment_recordings_candidate_id", "assessment_recordings", ["candidate_id"])
    op.create_index("ix_assessment_recordings_recruiter_id", "assessment_recordings", ["recruiter_id"])
    op.create_index("ix_assessment_recording_recruiter_status", "assessment_recordings", ["recruiter_id", "upload_status"])

def downgrade() -> None:
    op.drop_index("ix_assessment_recording_recruiter_status", table_name="assessment_recordings")
    op.drop_index("ix_assessment_recordings_recruiter_id", table_name="assessment_recordings")
    op.drop_index("ix_assessment_recordings_candidate_id", table_name="assessment_recordings")
    op.drop_index("ix_assessment_recordings_assessment_id", table_name="assessment_recordings")
    op.drop_table("assessment_recordings")
    op.drop_column("proctoring_sessions", "recording_consented_at")
