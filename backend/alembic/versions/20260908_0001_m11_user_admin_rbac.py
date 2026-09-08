"""users role/is_active, user_clients join table, global_settings for m11 user admin rbac

Revision ID: 20260908_0001
Revises: 20260905_0001
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20260908_0001'
down_revision: Union[str, Sequence[str], None] = '20260905_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(length=20), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))
    # Promote every pre-existing user to admin (single-operator installs).
    op.execute("UPDATE users SET role = 'admin'")
    op.create_table(
        "user_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "client_id", name="uq_user_clients_user_client"),
    )
    op.create_index("ix_user_clients_user_id", "user_clients", ["user_id"])
    op.create_index("ix_user_clients_client_id", "user_clients", ["client_id"])
    op.create_table(
        "global_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staging_removal_retention_days", sa.Integer(), nullable=False),
        sa.Column("staging_history_retention_days", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_retention_days", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("global_settings")
    op.drop_index("ix_user_clients_client_id", table_name="user_clients")
    op.drop_index("ix_user_clients_user_id", table_name="user_clients")
    op.drop_table("user_clients")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
