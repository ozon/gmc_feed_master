"""m18 event log and retention

Revision ID: 20260917_0001
Revises: 1a5ebca06d61
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260917_0001"
down_revision: str | Sequence[str] | None = "1a5ebca06d61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("logger", sa.String(length=120), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("actor_role", sa.String(length=20), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("feed_source_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("ix_event_log_created_at", "event_log", ["created_at"])
    op.create_index(
        "ix_event_log_category_created_at", "event_log", ["category", "created_at"]
    )
    op.create_index("ix_event_log_request_id", "event_log", ["request_id"])
    op.create_index("ix_event_log_feed_source_id", "event_log", ["feed_source_id"])


def downgrade() -> None:
    op.drop_index("ix_event_log_feed_source_id", table_name="event_log")
    op.drop_index("ix_event_log_request_id", table_name="event_log")
    op.drop_index("ix_event_log_category_created_at", table_name="event_log")
    op.drop_index("ix_event_log_created_at", table_name="event_log")
    op.drop_table("event_log")
