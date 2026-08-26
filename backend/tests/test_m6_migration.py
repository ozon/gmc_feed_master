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


async def _columns(url):
    engine = create_async_engine(url, pool_size=2, max_overflow=0)

    def _run(connection):
        inspector = inspect(connection)
        return {c["name"] for c in inspector.get_columns("staging_products")}

    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_run)
    finally:
        await engine.dispose()


async def test_upgrade_adds_processed_data_and_excluded(isolated_database_url):
    columns = await _columns(isolated_database_url)

    assert "processed_data" in columns
    assert "excluded" in columns


async def test_downgrade_drops_processed_data_and_excluded(isolated_database_url):
    await asyncio.to_thread(
        command.downgrade, _alembic_config(isolated_database_url), "20260826_0002"
    )

    columns = await _columns(isolated_database_url)
    assert "processed_data" not in columns
    assert "excluded" not in columns

    await asyncio.to_thread(command.upgrade, _alembic_config(isolated_database_url), "head")
