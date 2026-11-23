"""prevent duplicate recruiter application notifications"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "6a7b8c9d0e1f"
down_revision: Union[str, Sequence[str], None] = "5f6a7b8c9d0e"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_index(
        "uq_notifications_new_application", "notifications", ["user_id", "related_id"],
        unique=True, postgresql_where=sa.text("type = 'new_application' AND related_id IS NOT NULL"),
    )

def downgrade() -> None:
    op.drop_index("uq_notifications_new_application", table_name="notifications")
