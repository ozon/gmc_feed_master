"""m16 ai cleanup

Revision ID: b1a2c3d4e5f6
Revises: 2e9e790582c3
Create Date: 2026-09-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b1a2c3d4e5f6"
down_revision: str | Sequence[str] | None = "2e9e790582c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("ai_result_cache")
    op.drop_column("ai_provider_configs", "is_default")
    op.drop_column("global_settings", "ai_cache_retention_days")


def downgrade() -> None:
    op.add_column(
        "global_settings",
        sa.Column(
            "ai_cache_retention_days", sa.Integer(), server_default="90", nullable=False
        ),
    )
    op.add_column(
        "ai_provider_configs",
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.create_table(
        "ai_result_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column(
            "provider_config_id",
            sa.Integer(),
            sa.ForeignKey("ai_provider_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column(
            "template_version",
            sa.String(length=100),
            server_default="builtin",
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "task_type",
            "provider_config_id",
            "model",
            "template_version",
            "input_hash",
            name="uq_ai_result_cache_key",
        ),
    )
    op.create_index("ix_ai_result_cache_input_hash", "ai_result_cache", ["input_hash"])
