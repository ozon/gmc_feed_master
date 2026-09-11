"""m14 prompt templates

Revision ID: 20260911_0003
Revises: 20260911_0002
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260911_0003'
down_revision: str | Sequence[str] | None = '20260911_0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('prompt_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_type', sa.String(length=100), nullable=False),
    sa.Column('client_id', sa.Integer(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('system_prompt', sa.Text(), nullable=False),
    sa.Column('user_prompt', sa.Text(), nullable=False),
    sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_prompt_templates_client_active', 'prompt_templates', ['task_type', 'client_id'], unique=True, postgresql_where=sa.text('is_active AND client_id IS NOT NULL'))
    op.create_index('uq_prompt_templates_client_version', 'prompt_templates', ['task_type', 'client_id', 'version'], unique=True, postgresql_where=sa.text('client_id IS NOT NULL'))
    op.create_index('uq_prompt_templates_global_active', 'prompt_templates', ['task_type'], unique=True, postgresql_where=sa.text('is_active AND client_id IS NULL'))
    op.create_index('uq_prompt_templates_global_version', 'prompt_templates', ['task_type', 'version'], unique=True, postgresql_where=sa.text('client_id IS NULL'))


def downgrade() -> None:
    op.drop_index('uq_prompt_templates_global_version', table_name='prompt_templates', postgresql_where=sa.text('client_id IS NULL'))
    op.drop_index('uq_prompt_templates_global_active', table_name='prompt_templates', postgresql_where=sa.text('is_active AND client_id IS NULL'))
    op.drop_index('uq_prompt_templates_client_version', table_name='prompt_templates', postgresql_where=sa.text('client_id IS NOT NULL'))
    op.drop_index('uq_prompt_templates_client_active', table_name='prompt_templates', postgresql_where=sa.text('is_active AND client_id IS NOT NULL'))
    op.drop_table('prompt_templates')
