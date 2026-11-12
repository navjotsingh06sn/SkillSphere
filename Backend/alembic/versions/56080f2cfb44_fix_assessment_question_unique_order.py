"""fix assessment question unique order

Revision ID: 56080f2cfb44
Revises: b0c25c5f2488
"""

from alembic import op


revision = "56080f2cfb44"
down_revision = "b0c25c5f2488"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_assessment_question_order",
        table_name="assessment_questions",
    )

    op.create_unique_constraint(
        "uq_assessment_question_order",
        "assessment_questions",
        ["assessment_id", "order_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_assessment_question_order",
        "assessment_questions",
        type_="unique",
    )

    op.create_index(
        "ix_assessment_question_order",
        "assessment_questions",
        ["assessment_id", "order_number"],
        unique=False,
    )