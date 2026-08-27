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
