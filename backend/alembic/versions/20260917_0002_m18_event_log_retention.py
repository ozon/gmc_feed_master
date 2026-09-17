"""m18 event log retention setting

Revision ID: 20260917_0002
Revises: 20260917_0001
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260917_0002"
down_revision: str | Sequence[str] | None = "20260917_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_settings",
        sa.Column(
            "event_log_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="180",
        ),
    )


def downgrade() -> None:
    op.drop_column("global_settings", "event_log_retention_days")
