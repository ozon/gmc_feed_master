"""export_versions.source spec enum: {scheduled, manual, rollback} (m12, TODO 2.2)

Revision ID: 20260909_0001
Revises: 20260908_0001
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260909_0001'
down_revision: str | Sequence[str] | None = '20260908_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE export_versions SET source = 'manual' WHERE source = 'run'")
    op.alter_column(
        "export_versions",
        "source",
        existing_type=sa.String(length=20),
        server_default="manual",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "export_versions",
        "source",
        existing_type=sa.String(length=20),
        server_default="run",
        existing_nullable=False,
    )
    op.execute("UPDATE export_versions SET source = 'run' WHERE source IN ('manual', 'scheduled')")
