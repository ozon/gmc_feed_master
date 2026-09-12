"""export_runs finding delta counters

Revision ID: 642b864e0593
Revises: 20260911_0003
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '642b864e0593'
down_revision: str | Sequence[str] | None = '20260911_0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('export_runs', sa.Column('fixed_finding_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('export_runs', sa.Column('new_finding_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('export_runs', sa.Column('remaining_finding_count', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('export_runs', 'remaining_finding_count')
    op.drop_column('export_runs', 'new_finding_count')
    op.drop_column('export_runs', 'fixed_finding_count')
