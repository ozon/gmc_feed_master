import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


def _alembic_config(url):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


async def _inspect_schema(url):
    engine = create_async_engine(url)

    def _run(connection):
        inspector = inspect(connection)
        return (
            {c["name"] for c in inspector.get_columns("staging_products")},
            {i["name"]: i for i in inspector.get_indexes("staging_products")},
            inspector.get_foreign_keys("staging_history"),
        )

    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_run)
    finally:
        await engine.dispose()


def _fk_ondelete(fk):
    if "ondelete" in fk:
        return fk["ondelete"]
    return (fk.get("options") or {}).get("ondelete")


async def test_upgrade_adds_removed_at_cascade_and_index(isolated_database_url):
    columns, indexes, fks = await _inspect_schema(isolated_database_url)

    assert "removed_at" in columns
    assert "ix_staging_products_removed_purge" in indexes
    history_fk = [fk for fk in fks if fk["constrained_columns"] == ["staging_product_id"]]
    assert history_fk and _fk_ondelete(history_fk[0]) == "CASCADE"


async def test_downgrade_reverses_all_three(isolated_database_url):
    await asyncio.to_thread(
        command.downgrade, _alembic_config(isolated_database_url), "20260825_0001"
    )

    columns, indexes, fks = await _inspect_schema(isolated_database_url)
    assert "removed_at" not in columns
    assert "ix_staging_products_removed_purge" not in indexes
    history_fk = [fk for fk in fks if fk["constrained_columns"] == ["staging_product_id"]]
    assert history_fk and _fk_ondelete(history_fk[0]) == "RESTRICT"

    await asyncio.to_thread(command.upgrade, _alembic_config(isolated_database_url), "head")


async def test_removal_deletes_history_via_cascade(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            client = (await session.execute(
                text(
                    "INSERT INTO clients (name, settings, contact_details) "
                    "VALUES ('C', '{}', '{}') RETURNING id"
                )
            )).scalar_one()
            fs = (await session.execute(
                text(
                    "INSERT INTO feed_sources "
                    "(client_id, name, source_format, field_mapping, configuration) "
                    "VALUES (:cid, 'F', 'tsv', '{}', '{}') RETURNING id"
                ),
                {"cid": client},
            )).scalar_one()
            run = (await session.execute(
                text(
                    "INSERT INTO ingestion_runs "
                    "(feed_source_id, status, processed_count, failed_count, statistics) "
                    "VALUES (:fid, 'running', 0, 0, '{}') RETURNING id"
                ),
                {"fid": fs},
            )).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO staging_products "
                    "(feed_source_id, ingestion_run_id, product_id, content_hash, "
                    "config_hash, status, raw_data) "
                    "VALUES (:fid, :rid, 'p1', 'h', 'c', 'active', '{}')"
                ),
                {"fid": fs, "rid": run},
            )
            await session.execute(text(
                "INSERT INTO staging_history (staging_product_id, snapshot) "
                "SELECT id, '{}' FROM staging_products"
            ))

    async with factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM staging_products"))

    async with factory() as session:
        remaining = (await session.execute(
            text("SELECT count(*) FROM staging_history")
        )).scalar_one()
    assert remaining == 0
    await engine.dispose()
