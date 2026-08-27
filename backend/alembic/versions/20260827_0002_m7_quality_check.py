"""M7 quality check engine

Revision ID: 20260827_0002
Revises: 20260827_0001
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260827_0002'
down_revision: Union[str, Sequence[str], None] = '20260827_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename export_runs.error_finding_count → critical_finding_count
    op.alter_column('export_runs', 'error_finding_count', new_column_name='critical_finding_count')

    # 2. Add export_runs.ingestion_run_id (nullable FK)
    op.add_column('export_runs', sa.Column('ingestion_run_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_export_runs_ingestion_run_id', 'export_runs', 'ingestion_runs', ['ingestion_run_id'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_export_runs_ingestion_run_id', 'export_runs', ['ingestion_run_id'])

    # 3. Create image_dimensions table
    op.create_table(
        'image_dimensions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('url', sa.String(2048), nullable=False, unique=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('fetch_error', sa.String(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 4. Add feed_sources.volume_drop_threshold_pct
    op.add_column('feed_sources', sa.Column('volume_drop_threshold_pct', sa.Integer(), nullable=False, server_default='20'))

    # 5. Modify quality_findings: add feed_source_id, product_id, field; drop staging_product_id
    op.add_column('quality_findings', sa.Column('feed_source_id', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('quality_findings', sa.Column('product_id', sa.String(255), nullable=False, server_default=''))
    op.add_column('quality_findings', sa.Column('field', sa.String(255), nullable=True))
    op.create_foreign_key('fk_quality_findings_feed_source_id', 'quality_findings', 'feed_sources', ['feed_source_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_quality_findings_feed_source_id', 'quality_findings', ['feed_source_id'])
    op.drop_index('ix_quality_findings_staging_product_id', table_name='quality_findings')
    op.drop_constraint('quality_findings_staging_product_id_fkey', 'quality_findings', type_='foreignkey')
    op.drop_column('quality_findings', 'staging_product_id')


def downgrade() -> None:
    # Reverse quality_findings changes
    op.add_column('quality_findings', sa.Column('staging_product_id', sa.Integer(), nullable=False))
    op.create_foreign_key('quality_findings_staging_product_id_fkey', 'quality_findings', 'staging_products', ['staging_product_id'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_quality_findings_staging_product_id', 'quality_findings', ['staging_product_id'])
    op.drop_index('ix_quality_findings_feed_source_id', table_name='quality_findings')
    op.drop_constraint('fk_quality_findings_feed_source_id', 'quality_findings', type_='foreignkey')
    op.drop_column('quality_findings', 'field')
    op.drop_column('quality_findings', 'product_id')
    op.drop_column('quality_findings', 'feed_source_id')

    # Reverse feed_sources change
    op.drop_column('feed_sources', 'volume_drop_threshold_pct')

    # Drop image_dimensions
    op.drop_table('image_dimensions')

    # Reverse export_runs changes
    op.drop_index('ix_export_runs_ingestion_run_id', table_name='export_runs')
    op.drop_constraint('fk_export_runs_ingestion_run_id', 'export_runs', type_='foreignkey')
    op.drop_column('export_runs', 'ingestion_run_id')
    op.alter_column('export_runs', 'critical_finding_count', new_column_name='error_finding_count')
