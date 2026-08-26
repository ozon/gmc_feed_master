"""processed output store for M6 plugin host

Revision ID: 20260827_0001
Revises: 20260826_0002
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260827_0001'
down_revision: Union[str, Sequence[str], None] = '20260826_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('staging_products', sa.Column('processed_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('staging_products', sa.Column('excluded', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('staging_products', 'excluded')
    op.drop_column('staging_products', 'processed_data')
