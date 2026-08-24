import os
import uuid
import asyncio
from urllib.parse import urlsplit, urlunsplit

import pytest
import asyncpg
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


EXPECTED_TABLES = {
    "users",
    "sessions",
    "clients",
    "feed_sources",
    "ingestion_runs",
    "staging_products",
    "staging_history",
    "quality_findings",
    "plugins",
    "plugin_configs",
    "plugin_data",
    "module_pipelines",
    "module_instances",
    "export_runs",
    "export_versions",
}


@pytest.fixture
def database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL; SQLite fallback is not supported")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg:// dialect")
    return value


@pytest.fixture
def alembic_config(database_url):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def isolated_schema(database_url):
    parts = urlsplit(database_url)
    database_name = f"m1_test_{uuid.uuid4().hex}"
    admin_url = urlunsplit((parts.scheme.replace("+asyncpg", ""), parts.netloc, "/postgres", parts.query, parts.fragment))
    asyncio.run(_database_command(admin_url, f'CREATE DATABASE "{database_name}"'))
    isolated_url = urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, parts.fragment))
    try:
        yield isolated_url
    finally:
        asyncio.run(_database_command(admin_url, f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))


async def _database_command(database_url, statement):
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


async def _execute(database_url, statement):
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for command_text in statement.split(";"):
                if command_text.strip():
                    await connection.execute(text(command_text))
    finally:
        await engine.dispose()


def _schema_url(database_url: str, schema: str) -> str:
    return database_url


async def _table_names(database_url, schema):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"),
                {"schema": schema},
            )
            return {row[0] for row in result} - {"alembic_version"}
    finally:
        await engine.dispose()


async def _indexes_and_constraints(database_url, schema):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync: {
                    table: {
                        "indexes": inspect(sync).get_indexes(table, schema=schema),
                        "constraints": inspect(sync).get_check_constraints(table, schema=schema)
                        + inspect(sync).get_unique_constraints(table, schema=schema),
                        "foreign_keys": inspect(sync).get_foreign_keys(table, schema=schema),
                    }
                    for table in EXPECTED_TABLES
                }
            )
    finally:
        await engine.dispose()


def test_baseline_upgrade_downgrade_reupgrade(alembic_config, database_url, isolated_schema):
    alembic_config.set_main_option("sqlalchemy.url", isolated_schema)

    try:
        command.upgrade(alembic_config, "head")
        assert asyncio.run(_table_names(isolated_schema, "public")) == EXPECTED_TABLES

        objects = asyncio.run(_indexes_and_constraints(isolated_schema, "public"))
        assert any(index["name"] == "ix_sessions_token_hash" and index["unique"] for index in objects["sessions"]["indexes"])
        assert any(constraint["name"] == "uq_module_instances_pipeline_position" for constraint in objects["module_instances"]["constraints"])
        assert any(fk["referred_table"] == "module_pipelines" for fk in objects["feed_sources"]["foreign_keys"])
        assert any(fk["referred_table"] == "feed_sources" for fk in objects["module_pipelines"]["foreign_keys"])
        assert any(constraint["name"] == "ck_plugin_configs_scope_owner" for constraint in objects["plugin_configs"]["constraints"])
        assert any(index["name"] == "uq_plugin_data_feed_source_plugin_key" and index["unique"] for index in objects["plugin_data"]["indexes"])

        command.downgrade(alembic_config, "base")
        assert asyncio.run(_table_names(isolated_schema, "public")) == set()

        command.upgrade(alembic_config, "head")
        assert asyncio.run(_table_names(isolated_schema, "public")) == EXPECTED_TABLES
    finally:
        os.environ.pop("MIGRATION_SCHEMA", None)
