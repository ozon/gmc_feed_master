"""M8 XML writer: export tokens, retention, version bookkeeping

Revision ID: 20260828_0001
Revises: 20260827_0002
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260828_0001'
down_revision: Union[str, Sequence[str], None] = '20260827_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('feed_sources', sa.Column('feed_type', sa.String(20), nullable=False, server_default='primary'))
    op.add_column('feed_sources', sa.Column('export_token', sa.String(64), nullable=True))
    op.add_column('feed_sources', sa.Column('history_retention_count', sa.Integer(), nullable=False, server_default='30'))
    op.execute(
        "UPDATE feed_sources SET export_token = "
        "md5(random()::text || clock_timestamp()::text) || md5(random()::text) "
        "WHERE export_token IS NULL"
    )
    op.alter_column('feed_sources', 'export_token', nullable=False)
    op.create_index('uq_feed_sources_export_token', 'feed_sources', ['export_token'], unique=True)

    op.add_column('export_versions', sa.Column('product_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('export_versions', sa.Column('source', sa.String(20), nullable=False, server_default='run'))
    op.add_column('export_versions', sa.Column('source_version_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_export_versions_source_version_id', 'export_versions', 'export_versions',
        ['source_version_id'], ['id'], ondelete='SET NULL',
    )

    op.drop_constraint('fk_export_runs_export_version_id', 'export_runs', type_='foreignkey')
    op.create_foreign_key(
        'fk_export_runs_export_version_id', 'export_runs', 'export_versions',
        ['export_version_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_export_runs_export_version_id', 'export_runs', type_='foreignkey')
    op.create_foreign_key(
        'fk_export_runs_export_version_id', 'export_runs', 'export_versions',
        ['export_version_id'], ['id'], ondelete='RESTRICT',
    )

    op.drop_constraint('fk_export_versions_source_version_id', 'export_versions', type_='foreignkey')
    op.drop_column('export_versions', 'source_version_id')
    op.drop_column('export_versions', 'source')
    op.drop_column('export_versions', 'product_count')

    op.drop_index('uq_feed_sources_export_token', table_name='feed_sources')
    op.drop_column('feed_sources', 'history_retention_count')
    op.drop_column('feed_sources', 'export_token')
    op.drop_column('feed_sources', 'feed_type')
