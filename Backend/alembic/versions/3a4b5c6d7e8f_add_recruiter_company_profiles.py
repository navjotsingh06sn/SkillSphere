"""allow recruiters to manage multiple company profiles"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "3a4b5c6d7e8f"
down_revision: Union[str, Sequence[str], None] = "f2179a03c4de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recruiter_companies",
        sa.Column("recruiter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recruiter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recruiter_id", "company_id"),
    )
    op.execute(sa.text("""
        INSERT INTO recruiter_companies (recruiter_id, company_id, created_at)
        SELECT user_id, company_id, now()
        FROM recruiter_profiles
        WHERE company_id IS NOT NULL
        ON CONFLICT (recruiter_id, company_id) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_table("recruiter_companies")
