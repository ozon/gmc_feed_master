"""m13 ai provider abstraction: ai_provider_configs, ai_result_cache, ai_usage_logs

Revision ID: 20260911_0001
Revises: 20260909_0001
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260911_0001'
down_revision: str | Sequence[str] | None = '20260909_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_provider_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('provider_type', sa.String(length=50), nullable=False),
    sa.Column('base_url', sa.String(length=1024), nullable=False),
    sa.Column('api_key', sa.String(length=1024), nullable=False),
    sa.Column('model', sa.String(length=255), nullable=False),
    sa.Column('input_price_per_mtok', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('output_price_per_mtok', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('max_concurrency', sa.Integer(), nullable=False),
    sa.Column('timeout_s', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', name='uq_ai_provider_configs_name')
    )
    op.create_table('ai_usage_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_id', sa.Integer(), nullable=True),
    sa.Column('feed_source_id', sa.Integer(), nullable=True),
    sa.Column('task_type', sa.String(length=100), nullable=False),
    sa.Column('provider_config_id', sa.Integer(), nullable=True),
    sa.Column('model', sa.String(length=255), nullable=False),
    sa.Column('cache_hit', sa.Boolean(), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ai_usage_logs_client_id', 'ai_usage_logs', ['client_id'], unique=False)
    op.create_index('ix_ai_usage_logs_created_at', 'ai_usage_logs', ['created_at'], unique=False)
    op.create_index('ix_ai_usage_logs_feed_source_id', 'ai_usage_logs', ['feed_source_id'], unique=False)
    op.create_table('ai_result_cache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_type', sa.String(length=100), nullable=False),
    sa.Column('provider_config_id', sa.Integer(), nullable=False),
    sa.Column('model', sa.String(length=255), nullable=False),
    sa.Column('template_version', sa.String(length=100), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['provider_config_id'], ['ai_provider_configs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_type', 'provider_config_id', 'model', 'template_version', 'input_hash', name='uq_ai_result_cache_key')
    )
    op.create_index('ix_ai_result_cache_input_hash', 'ai_result_cache', ['input_hash'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ai_result_cache_input_hash', table_name='ai_result_cache')
    op.drop_table('ai_result_cache')
    op.drop_index('ix_ai_usage_logs_feed_source_id', table_name='ai_usage_logs')
    op.drop_index('ix_ai_usage_logs_created_at', table_name='ai_usage_logs')
    op.drop_index('ix_ai_usage_logs_client_id', table_name='ai_usage_logs')
    op.drop_table('ai_usage_logs')
    op.drop_table('ai_provider_configs')
