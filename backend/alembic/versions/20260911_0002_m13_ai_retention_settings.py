"""m13 ai retention settings: global_settings.ai_usage_retention_days / ai_cache_retention_days

Revision ID: 20260911_0002
Revises: 20260911_0001
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260911_0002'
down_revision: str | Sequence[str] | None = '20260911_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'global_settings',
        sa.Column('ai_usage_retention_days', sa.Integer(), nullable=False, server_default='90'),
    )
    op.add_column(
        'global_settings',
        sa.Column('ai_cache_retention_days', sa.Integer(), nullable=False, server_default='90'),
    )


def downgrade() -> None:
    op.drop_column('global_settings', 'ai_cache_retention_days')
    op.drop_column('global_settings', 'ai_usage_retention_days')
