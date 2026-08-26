"""plugins.enabled column for M6 plugin host registration

Revision ID: 20260826_0002
Revises: 20260826_0001
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20260826_0002'
down_revision: Union[str, Sequence[str], None] = '20260826_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('plugins', sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('plugins', 'enabled')
