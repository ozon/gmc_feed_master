from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.ingestion import IngestionRun
from app.models.staging import StagingHistory, StagingProduct
from app.staging.purge import purge_expired

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


class FactoryAdapter:
    def __init__(self, factory):
        self._factory = factory

    def __call__(self):
        return self._factory()


async def _seed(session):
    client = Client(name="Acme")
    session.add(client)
    await session.flush()
    feed_source = FeedSource(client_id=client.id, name="US", source_format="tsv")
    session.add(feed_source)
    await session.flush()
    session.add(IngestionRun(id=1, feed_source_id=feed_source.id, status="completed"))
    await session.flush()
    return feed_source


async def _product(factory, feed_source, pid, status, removed_at, recorded_at=NOW):
    async with factory() as session:
        async with session.begin():
            row = StagingProduct(
                feed_source_id=feed_source.id,
                ingestion_run_id=1,
                product_id=pid,
                content_hash="h",
                config_hash="c",
                status=status,
                raw_data={},
            )
            session.add(row)
            await session.flush()
            history = StagingHistory(staging_product_id=row.id, snapshot={})
            session.add(history)
            await session.flush()
            pk, history_pk = row.id, history.id
        async with session.begin():
            if status == "removed":
                await session.execute(
                    text(
                        "UPDATE staging_products SET removed_at = :ra WHERE id = :pk"
                    ),
                    {"ra": removed_at, "pk": pk},
                )
            await session.execute(
                text("UPDATE staging_history SET recorded_at = :t WHERE id = :pk"),
                {"t": recorded_at, "pk": history_pk},
            )
    return pk, history_pk


async def test_purge_removes_expired_rows_only(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)

    expired_pk, expired_hist = await _product(
        factory, feed_source, "old", "removed", NOW - timedelta(days=91)
    )
    fresh_pk, fresh_hist = await _product(
        factory, feed_source, "recent", "removed", NOW - timedelta(days=10)
    )
    active_pk, aged_hist = await _product(
        factory, feed_source, "active", "active", None,
        recorded_at=NOW - timedelta(days=91),
    )

    counts = await purge_expired(FactoryAdapter(factory), NOW)

    assert counts.removed_products == 1
    assert counts.history_rows == 2
    async with factory() as session:
        remaining_products = {
            row.product_id
            for row in (await session.execute(select(StagingProduct))).scalars()
        }
        remaining_history = {
            row.id for row in (await session.execute(select(StagingHistory))).scalars()
        }
    assert remaining_products == {"recent", "active"}
    assert remaining_history == {fresh_hist}
    await engine.dispose()


async def test_purge_on_empty_tables_is_zero(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    counts = await purge_expired(FactoryAdapter(factory), NOW)

    assert counts.removed_products == 0
    assert counts.history_rows == 0
    await engine.dispose()
