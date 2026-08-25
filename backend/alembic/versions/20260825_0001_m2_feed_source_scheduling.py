"""M2 feed source scheduling

Revision ID: 20260825_0001
Revises: 20260824_0001
Create Date: 2026-08-25 09:10:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260825_0001'
down_revision: Union[str, Sequence[str], None] = '20260824_0001'
branch_labels: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'feed_sources',
        'source_type',
        new_column_name='source_format',
        existing_type=sa.String(length=100),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.add_column('feed_sources', sa.Column('cron_expression', sa.String(length=100), nullable=True))
    op.add_column('feed_sources', sa.Column('target_country', sa.String(length=10), nullable=True))
    op.add_column('feed_sources', sa.Column('target_language', sa.String(length=10), nullable=True))
    op.add_column('feed_sources', sa.Column('currency', sa.String(length=3), nullable=True))
    op.add_column('feed_sources', sa.Column('source_url', sa.String(length=2048), nullable=True))
    op.add_column(
        'clients',
        sa.Column(
            'contact_details',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='{}',
        ),
    )
    op.add_column(
        'clients',
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
    )


def downgrade() -> None:
    op.drop_column('clients', 'status')
    op.drop_column('clients', 'contact_details')
    op.drop_column('feed_sources', 'source_url')
    op.drop_column('feed_sources', 'currency')
    op.drop_column('feed_sources', 'target_language')
    op.drop_column('feed_sources', 'target_country')
    op.drop_column('feed_sources', 'cron_expression')
    op.alter_column(
        'feed_sources',
        'source_format',
        new_column_name='source_type',
        existing_type=sa.String(length=50),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
