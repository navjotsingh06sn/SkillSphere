"""replace job experience and salary ranges with flexible text fields"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "5f6a7b8c9d0e"
down_revision: Union[str, Sequence[str], None] = "4e5f6a7b8c9d"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("jobs", sa.Column("experience_requirement", sa.String(length=120), nullable=True))
    op.add_column("jobs", sa.Column("expected_salary", sa.String(length=160), nullable=True))
    op.execute(sa.text("""
        UPDATE jobs SET experience_requirement = CASE
            WHEN experience_min IS NULL AND experience_max IS NULL THEN NULL
            WHEN COALESCE(experience_min, 0) = 0 AND COALESCE(experience_max, 0) = 0 THEN 'Any experience'
            WHEN experience_min IS NULL THEN 'Up to ' || experience_max::text || ' years'
            WHEN experience_max IS NULL OR experience_max = 0 THEN experience_min::text || '+ years'
            WHEN experience_min = experience_max THEN experience_min::text || ' years'
            ELSE experience_min::text || '–' || experience_max::text || ' years'
        END,
        expected_salary = CASE
            WHEN salary_min IS NULL AND salary_max IS NULL THEN NULL
            WHEN salary_min IS NULL THEN 'Up to ' || salary_max::text
            WHEN salary_max IS NULL OR (salary_max = 0 AND salary_min > 0) THEN salary_min::text
            WHEN salary_min = salary_max THEN salary_min::text
            ELSE salary_min::text || ' – ' || salary_max::text
        END
    """))
    op.drop_column("jobs", "experience_min")
    op.drop_column("jobs", "experience_max")
    op.drop_column("jobs", "salary_min")
    op.drop_column("jobs", "salary_max")

def downgrade() -> None:
    # Retain the flexible text fields so values entered after upgrade are not lost.
    op.add_column("jobs", sa.Column("experience_min", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("experience_max", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_min", sa.Float(), nullable=True))
    op.add_column("jobs", sa.Column("salary_max", sa.Float(), nullable=True))
    op.execute(sa.text("""
        UPDATE jobs SET
            experience_min = NULLIF((regexp_match(experience_requirement, '([0-9]+)'))[1], '')::integer,
            experience_max = NULLIF((regexp_match(experience_requirement, '^[^0-9]*[0-9]+[^0-9]+([0-9]+)'))[1], '')::integer,
            salary_min = NULLIF(replace((regexp_match(expected_salary, '([0-9][0-9,]*(?:[.][0-9]+)?)'))[1], ',', ''), '')::double precision,
            salary_max = NULLIF(replace((regexp_match(expected_salary, '^[^0-9]*[0-9][0-9,]*(?:[.][0-9]+)?[^0-9]+([0-9][0-9,]*(?:[.][0-9]+)?)'))[1], ',', ''), '')::double precision
    """))
