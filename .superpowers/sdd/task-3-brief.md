### Task 3: Migration — Schema Changes

**Goal:** Create Alembic migration for all M7 schema changes.

**Files:**
- Create: `backend/alembic/versions/20260827_0002_m7_quality_check.py`
- Create: `backend/tests/test_m7_migration.py`

#### Steps

- [ ] **Step 1: Write the migration**

```python
# backend/alembic/versions/20260827_0002_m7_quality_check.py
"""M7 quality check engine

Revision ID: 20260827_0002
Revises: 20260827_0001
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_0002"
down_revision = "20260827_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename export_runs.error_finding_count → critical_finding_count
    op.alter_column("export_runs", "error_finding_count", new_column_name="critical_finding_count")

    # 2. Add export_runs.ingestion_run_id (nullable FK)
    op.add_column("export_runs", sa.Column("ingestion_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_export_runs_ingestion_run_id", "export_runs", "ingestion_runs", ["ingestion_run_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_export_runs_ingestion_run_id", "export_runs", ["ingestion_run_id"])

    # 3. Create image_dimensions table
    op.create_table(
        "image_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(2048), nullable=False, unique=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fetch_error", sa.String(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 4. Add feed_sources.volume_drop_threshold_pct
    op.add_column("feed_sources", sa.Column("volume_drop_threshold_pct", sa.Integer(), nullable=False, server_default="20"))

    # 5. Modify quality_findings: add feed_source_id, product_id, field; drop staging_product_id
    op.add_column("quality_findings", sa.Column("feed_source_id", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("quality_findings", sa.Column("product_id", sa.String(255), nullable=False, server_default=""))
    op.add_column("quality_findings", sa.Column("field", sa.String(255), nullable=True))
    op.create_foreign_key("fk_quality_findings_feed_source_id", "quality_findings", "feed_sources", ["feed_source_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_quality_findings_feed_source_id", "quality_findings", ["feed_source_id"])
    op.drop_index("ix_quality_findings_staging_product_id", table_name="quality_findings")
    op.drop_constraint("quality_findings_staging_product_id_fkey", "quality_findings", type_="foreignkey")
    op.drop_column("quality_findings", "staging_product_id")


def downgrade() -> None:
    # Reverse quality_findings changes
    op.add_column("quality_findings", sa.Column("staging_product_id", sa.Integer(), nullable=False))
    op.create_foreign_key("quality_findings_staging_product_id_fkey", "quality_findings", "staging_products", ["staging_product_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_quality_findings_staging_product_id", "quality_findings", ["staging_product_id"])
    op.drop_index("ix_quality_findings_feed_source_id", table_name="quality_findings")
    op.drop_constraint("fk_quality_findings_feed_source_id", "quality_findings", type_="foreignkey")
    op.drop_column("quality_findings", "field")
    op.drop_column("quality_findings", "product_id")
    op.drop_column("quality_findings", "feed_source_id")

    # Reverse feed_sources change
    op.drop_column("feed_sources", "volume_drop_threshold_pct")

    # Drop image_dimensions
    op.drop_table("image_dimensions")

    # Reverse export_runs changes
    op.drop_index("ix_export_runs_ingestion_run_id", table_name="export_runs")
    op.drop_constraint("fk_export_runs_ingestion_run_id", "export_runs", type_="foreignkey")
    op.drop_column("export_runs", "ingestion_run_id")
    op.alter_column("export_runs", "critical_finding_count", new_column_name="error_finding_count")
```

- [ ] **Step 2: Write migration tests**

```python
# backend/tests/test_m7_migration.py
import asyncio
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


def _alembic_config(url):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


async def _columns(url, table):
    engine = create_async_engine(url, pool_size=2, max_overflow=0)

    def _run(connection):
        inspector = inspect(connection)
        return {c["name"] for c in inspector.get_columns(table)}

    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_run)
    finally:
        await engine.dispose()


async def test_upgrade_adds_qc_columns(isolated_database_url):
    export_cols = await _columns(isolated_database_url, "export_runs")
    assert "critical_finding_count" in export_cols
    assert "ingestion_run_id" in export_cols
    assert "error_finding_count" not in export_cols

    quality_cols = await _columns(isolated_database_url, "quality_findings")
    assert "feed_source_id" in quality_cols
    assert "product_id" in quality_cols
    assert "field" in quality_cols
    assert "staging_product_id" not in quality_cols

    feed_cols = await _columns(isolated_database_url, "feed_sources")
    assert "volume_drop_threshold_pct" in feed_cols

    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)

    def _has_table(connection):
        inspector = inspect(connection)
        return "image_dimensions" in inspector.get_table_names()

    try:
        async with engine.connect() as connection:
            assert await connection.run_sync(_has_table)
    finally:
        await engine.dispose()


async def test_downgrade_reverses_qc_changes(isolated_database_url):
    await asyncio.to_thread(
        command.downgrade, _alembic_config(isolated_database_url), "20260827_0001"
    )

    export_cols = await _columns(isolated_database_url, "export_runs")
    assert "error_finding_count" in export_cols
    assert "critical_finding_count" not in export_cols
    assert "ingestion_run_id" not in export_cols

    quality_cols = await _columns(isolated_database_url, "quality_findings")
    assert "staging_product_id" in quality_cols
    assert "feed_source_id" not in quality_cols

    await asyncio.to_thread(command.upgrade, _alembic_config(isolated_database_url), "head")
```

- [ ] **Step 3: Run migration tests**

Run: `cd backend && python -m pytest tests/test_m7_migration.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/20260827_0002_m7_quality_check.py backend/tests/test_m7_migration.py
git commit -m "feat(migration): M7 schema changes for QC engine"
```

---

