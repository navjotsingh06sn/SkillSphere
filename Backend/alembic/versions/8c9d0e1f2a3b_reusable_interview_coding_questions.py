"""allow interview coding questions to be saved in a recruiter bank"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8c9d0e1f2a3b"
down_revision: Union[str, Sequence[str], None] = "7b8c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "interview_coding_problems",
        "interview_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "interview_coding_problems",
        "interview_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
