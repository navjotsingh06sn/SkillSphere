
"""add complete assessment and interview system

Revision ID: 5e7d713ce7f5
Revises: 56080f2cfb44
Create Date: 2026-11-12 22:54:21.476795
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5e7d713ce7f5"
down_revision: Union[str, Sequence[str], None] = "56080f2cfb44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # Assessment answers index
    op.create_index(
        "ix_assessment_answers_assessment",
        "assessment_answers",
        ["assessment_id"],
        unique=False,
    )

    # Assessment questions
    op.add_column(
        "assessment_questions",
        sa.Column(
            "marks",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )

    op.create_index(
        "ix_assessment_question_bank",
        "assessment_questions",
        ["question_bank_id"],
        unique=False,
    )

    # Assessments
    op.add_column(
        "assessments",
        sa.Column(
            "title",
            sa.String(length=255),
            nullable=False,
            server_default="Untitled Assessment",
        ),
    )

    op.add_column(
        "assessments",
        sa.Column(
            "total_marks",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
    )

    op.add_column(
        "assessments",
        sa.Column(
            "passing_marks",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
    )

    op.add_column(
        "assessments",
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.alter_column(
        "assessments",
        "candidate_id",
        existing_type=sa.UUID(),
        nullable=True,
    )

    op.create_index(
        "ix_assessment_candidate_status",
        "assessments",
        ["candidate_id", "status"],
        unique=False,
    )

    op.create_index(
        "ix_assessment_recruiter_status",
        "assessments",
        ["recruiter_id", "status"],
        unique=False,
    )

    op.create_index(
        op.f("ix_assessments_job_id"),
        "assessments",
        ["job_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_assessments_status"),
        "assessments",
        ["status"],
        unique=False,
    )

    op.create_unique_constraint(
        "uq_assessment_application",
        "assessments",
        ["application_id"],
    )

    # Interview email tracking
    op.add_column(
        "interviews",
        sa.Column(
            "email_status",
            sa.String(length=30),
            nullable=False,
            server_default="pending",
        ),
    )

    op.add_column(
        "interviews",
        sa.Column(
            "email_message_id",
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.add_column(
        "interviews",
        sa.Column(
            "email_error",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "interviews",
        sa.Column(
            "email_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "interviews",
        sa.Column(
            "email_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # Question bank
    op.add_column(
        "question_bank_questions",
        sa.Column("category", sa.String(length=150), nullable=True),
    )

    op.add_column(
        "question_bank_questions",
        sa.Column("topic", sa.String(length=150), nullable=True),
    )

    op.add_column(
        "question_bank_questions",
        sa.Column("subtopic", sa.String(length=150), nullable=True),
    )

    op.add_column(
        "question_bank_questions",
        sa.Column(
            "marks",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )

    op.alter_column(
        "question_bank_questions",
        "recruiter_id",
        existing_type=sa.UUID(),
        nullable=True,
    )

    op.create_index(
        "ix_question_bank_filters",
        "question_bank_questions",
        ["technology", "role", "difficulty", "is_active"],
        unique=False,
    )

    # Remove temporary migration defaults.
    op.alter_column("assessment_questions", "marks", server_default=None)
    op.alter_column("assessments", "title", server_default=None)
    op.alter_column("assessments", "total_marks", server_default=None)
    op.alter_column("assessments", "passing_marks", server_default=None)
    op.alter_column("interviews", "email_status", server_default=None)
    op.alter_column("interviews", "email_attempts", server_default=None)
    op.alter_column("question_bank_questions", "marks", server_default=None)


def downgrade() -> None:

    op.drop_index(
        "ix_question_bank_filters",
        table_name="question_bank_questions",
    )

    op.alter_column(
        "question_bank_questions",
        "recruiter_id",
        existing_type=sa.UUID(),
        nullable=False,
    )

    op.drop_column("question_bank_questions", "marks")
    op.drop_column("question_bank_questions", "subtopic")
    op.drop_column("question_bank_questions", "topic")
    op.drop_column("question_bank_questions", "category")

    op.drop_column("interviews", "email_attempts")
    op.drop_column("interviews", "email_sent_at")
    op.drop_column("interviews", "email_error")
    op.drop_column("interviews", "email_message_id")
    op.drop_column("interviews", "email_status")

    op.drop_constraint(
        "uq_assessment_application",
        "assessments",
        type_="unique",
    )

    op.drop_index(
        op.f("ix_assessments_status"),
        table_name="assessments",
    )

    op.drop_index(
        op.f("ix_assessments_job_id"),
        table_name="assessments",
    )

    op.drop_index(
        "ix_assessment_recruiter_status",
        table_name="assessments",
    )

    op.drop_index(
        "ix_assessment_candidate_status",
        table_name="assessments",
    )

    op.alter_column(
        "assessments",
        "candidate_id",
        existing_type=sa.UUID(),
        nullable=False,
    )

    op.drop_column("assessments", "published_at")
    op.drop_column("assessments", "passing_marks")
    op.drop_column("assessments", "total_marks")
    op.drop_column("assessments", "title")

    op.drop_index(
        "ix_assessment_question_bank",
        table_name="assessment_questions",
    )

    op.drop_column("assessment_questions", "marks")

    op.drop_index(
        "ix_assessment_answers_assessment",
        table_name="assessment_answers",
    )
