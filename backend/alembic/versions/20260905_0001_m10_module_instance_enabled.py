"""module_instances.enabled column for M10 pipeline page master-detail

Revision ID: 20260905_0001
Revises: 20260828_0001
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260905_0001'
down_revision: str | Sequence[str] | None = '20260828_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('module_instances', sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('module_instances', 'enabled')
