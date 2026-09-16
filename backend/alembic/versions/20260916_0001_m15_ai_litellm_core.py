"""m15 ai litellm core

Revision ID: 2e9e790582c3
Revises: 642b864e0593
Create Date: 2026-09-16 11:56:26.461642
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2e9e790582c3"
down_revision: str | Sequence[str] | None = "642b864e0593"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('ai_provider_configs', sa.Column('tier', sa.String(length=20), server_default='bulk', nullable=False))
    op.add_column('ai_usage_logs', sa.Column('provider', sa.String(length=255), nullable=True))
    op.add_column('ai_usage_logs', sa.Column('tier', sa.String(length=20), nullable=True))
    op.add_column('ai_usage_logs', sa.Column('fallback_used', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('global_settings', sa.Column('ai_cache_type', sa.String(length=20), server_default='local', nullable=False))
    op.add_column('global_settings', sa.Column('ai_cache_namespace', sa.String(length=100), server_default='gmc-ai', nullable=False))
    op.add_column('global_settings', sa.Column('ai_cache_ttl_taxonomy_s', sa.Integer(), server_default='2592000', nullable=False))
    op.add_column('global_settings', sa.Column('ai_cache_ttl_content_s', sa.Integer(), server_default='604800', nullable=False))
    op.add_column('global_settings', sa.Column('ai_router_timeout_s', sa.Integer(), server_default='30', nullable=False))
    op.add_column('global_settings', sa.Column('ai_router_num_retries', sa.Integer(), server_default='2', nullable=False))
    op.add_column('global_settings', sa.Column('ai_router_allowed_fails', sa.Integer(), server_default='3', nullable=False))
    op.add_column('global_settings', sa.Column('ai_router_cooldown_s', sa.Integer(), server_default='30', nullable=False))
    op.add_column('global_settings', sa.Column('ai_instructor_max_retries', sa.Integer(), server_default='2', nullable=False))


def downgrade() -> None:
    op.drop_column('global_settings', 'ai_instructor_max_retries')
    op.drop_column('global_settings', 'ai_router_cooldown_s')
    op.drop_column('global_settings', 'ai_router_allowed_fails')
    op.drop_column('global_settings', 'ai_router_num_retries')
    op.drop_column('global_settings', 'ai_router_timeout_s')
    op.drop_column('global_settings', 'ai_cache_ttl_content_s')
    op.drop_column('global_settings', 'ai_cache_ttl_taxonomy_s')
    op.drop_column('global_settings', 'ai_cache_namespace')
    op.drop_column('global_settings', 'ai_cache_type')
    op.drop_column('ai_usage_logs', 'fallback_used')
    op.drop_column('ai_usage_logs', 'tier')
    op.drop_column('ai_usage_logs', 'provider')
    op.drop_column('ai_provider_configs', 'tier')
