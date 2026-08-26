import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
def alembic_config(isolated_database_url):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", isolated_database_url)
    return config


async def _columns(database_url, table):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
                    "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :table"
                ),
                {"table": table},
            )
            return {row[0]: row for row in result}
    finally:
        await engine.dispose()


def test_m2_migration_upgrade_downgrade_reupgrade(alembic_config, isolated_database_url):
    command.upgrade(alembic_config, "head")

    feed_source_columns = asyncio.run(_columns(isolated_database_url, "feed_sources"))
    assert "source_format" in feed_source_columns
    assert "source_type" not in feed_source_columns
    assert feed_source_columns["source_format"][2] == 50
    assert feed_source_columns["cron_expression"][2] == 100
    assert feed_source_columns["cron_expression"][3] == "YES"
    assert feed_source_columns["target_country"][2] == 10
    assert feed_source_columns["target_language"][2] == 10
    assert feed_source_columns["currency"][2] == 3
    assert feed_source_columns["source_url"][2] == 2048

    client_columns = asyncio.run(_columns(isolated_database_url, "clients"))
    assert client_columns["contact_details"][1] == "jsonb"
    assert client_columns["contact_details"][3] == "NO"
    assert client_columns["contact_details"][4] == "'{}'::jsonb"
    assert client_columns["status"][2] == 50
    assert client_columns["status"][3] == "NO"
    assert client_columns["status"][4] == "'active'::character varying"

    command.downgrade(alembic_config, "20260824_0001")

    feed_source_columns = asyncio.run(_columns(isolated_database_url, "feed_sources"))
    assert "source_type" in feed_source_columns
    assert "source_format" not in feed_source_columns
    assert feed_source_columns["source_type"][2] == 100
    for dropped in ("cron_expression", "target_country", "target_language", "currency", "source_url"):
        assert dropped not in feed_source_columns

    client_columns = asyncio.run(_columns(isolated_database_url, "clients"))
    assert "contact_details" not in client_columns
    assert "status" not in client_columns

    command.upgrade(alembic_config, "head")

    feed_source_columns = asyncio.run(_columns(isolated_database_url, "feed_sources"))
    assert "source_format" in feed_source_columns
    assert "source_type" not in feed_source_columns
