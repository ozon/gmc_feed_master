"""M5 staging delta support

Revision ID: 20260826_0001
Revises: 20260825_0001
Create Date: 2026-08-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260826_0001'
down_revision: Union[str, Sequence[str], None] = '20260825_0001'
branch_labels: Union[str, Sequence[str], None] = None

_PURGE_INDEX = 'ix_staging_products_removed_purge'
_HISTORY_FK = 'staging_history_staging_product_id_fkey'


def upgrade() -> None:
    op.add_column(
        'staging_products',
        sa.Column('removed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        _PURGE_INDEX,
        'staging_products',
        ['removed_at'],
        unique=False,
        postgresql_where=sa.text("status = 'removed'"),
    )
    op.drop_constraint(_HISTORY_FK, 'staging_history', type_='foreignkey')
    op.create_foreign_key(
        _HISTORY_FK,
        'staging_history',
        'staging_products',
        ['staging_product_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(_HISTORY_FK, 'staging_history', type_='foreignkey')
    op.create_foreign_key(
        _HISTORY_FK,
        'staging_history',
        'staging_products',
        ['staging_product_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.drop_index(_PURGE_INDEX, table_name='staging_products')
    op.drop_column('staging_products', 'removed_at')
