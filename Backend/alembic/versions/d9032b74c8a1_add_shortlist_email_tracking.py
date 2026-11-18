"""add shortlist email tracking

Revision ID: d9032b74c8a1
Revises: 5e7d713ce7f5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9032b74c8a1"
down_revision: Union[str, Sequence[str], None] = "5e7d713ce7f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column(
            "shortlist_email_status",
            sa.String(length=30),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "applications",
        sa.Column("shortlist_email_message_id", sa.String(length=255)),
    )
    op.add_column(
        "applications",
        sa.Column("shortlist_email_error", sa.Text()),
    )
    op.add_column(
        "applications",
        sa.Column(
            "shortlist_email_sent_at",
            sa.DateTime(timezone=True),
        ),
    )
    op.add_column(
        "applications",
        sa.Column(
            "shortlist_email_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.alter_column(
        "applications",
        "shortlist_email_status",
        server_default=None,
    )
    op.alter_column(
        "applications",
        "shortlist_email_attempts",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("applications", "shortlist_email_attempts")
    op.drop_column("applications", "shortlist_email_sent_at")
    op.drop_column("applications", "shortlist_email_error")
    op.drop_column("applications", "shortlist_email_message_id")
    op.drop_column("applications", "shortlist_email_status")
