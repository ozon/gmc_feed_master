"""add ai_model_catalog table (GFM-12)

Revision ID: a1b2c3d4e5f6
Revises: TODO_SET_TO_CURRENT_HEAD
Create Date: 2026-09-17

NOTE: `down_revision` is a placeholder. This branch was created without a
local checkout, so the true current Alembic head could not be resolved from
the API. Before merging, run:

    alembic heads

and set `down_revision` below to that value (or rebase this migration with
`alembic merge` if a new head was added concurrently).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "TODO_SET_TO_CURRENT_HEAD"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_model_catalog",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("input_price_per_mtok", sa.Float(), nullable=True),
        sa.Column("output_price_per_mtok", sa.Float(), nullable=True),
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_function_calling", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_ai_model_catalog_model_id", "ai_model_catalog", ["model_id"])
    op.create_index("ix_ai_model_catalog_vendor", "ai_model_catalog", ["vendor"])


def downgrade() -> None:
    op.drop_index("ix_ai_model_catalog_vendor", table_name="ai_model_catalog")
    op.drop_constraint("uq_ai_model_catalog_model_id", "ai_model_catalog", type_="unique")
    op.drop_table("ai_model_catalog")
