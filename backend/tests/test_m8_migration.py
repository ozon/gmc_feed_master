import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


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


async def test_upgrade_adds_m8_columns(isolated_database_url):
    feed_cols = await _columns(isolated_database_url, "feed_sources")
    assert "feed_type" in feed_cols
    assert "export_token" in feed_cols
    assert "history_retention_count" in feed_cols

    version_cols = await _columns(isolated_database_url, "export_versions")
    assert "product_count" in version_cols
    assert "source" in version_cols
    assert "source_version_id" in version_cols


async def test_export_token_backfilled_unique(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)

    def _run(connection):
        inspector = inspect(connection)
        indexes = inspector.get_indexes("feed_sources")
        return indexes

    try:
        async with engine.connect() as connection:
            indexes = await connection.run_sync(_run)
    finally:
        await engine.dispose()

    assert any(
        idx["unique"] and idx["column_names"] == ["export_token"] for idx in indexes
    )
