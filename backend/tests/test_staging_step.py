import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.ingestion import IngestionRun
from app.models.staging import StagingHistory, StagingProduct
from app.pipeline import RunState, StepContext
from app.pipeline.steps import StagingStep
from app.staging.delta import StoredRow
from app.staging.hashing import content_hash
from app.staging.persistence import load_stored_rows

pytestmark = pytest.mark.asyncio


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
    session.add_all([
        IngestionRun(id=run_id, feed_source_id=feed_source.id, status="completed")
        for run_id in (1, 2, 3)
    ])
    await session.flush()
    return feed_source


def _ctx(factory, feed_source_id, products, run_id=1):
    state = RunState(products=list(products))
    return StepContext(
        feed_source_id=feed_source_id,
        session_factory=FactoryAdapter(factory),
        logger=logging.getLogger(__name__),
        run_state=state,
        ingestion_run_id=run_id,
    )


async def _staged_rows(factory):
    async with factory() as session:
        result = await session.execute(select(StagingProduct))
        return {row.product_id: row for row in result.scalars()}


async def test_first_run_stages_all_products(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products))

    assert result.statistics["staging"]["new"] == 2
    assert result.processed_count == 2
    rows = await _staged_rows(factory)
    assert set(rows) == {"1", "2"}
    assert all(r.status == "active" for r in rows.values())
    assert rows["1"].raw_data == products[0]
    await engine.dispose()


async def test_identical_rerun_touches_only(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=2))

    assert result.statistics["staging"]["unchanged"] == 1
    assert result.processed_count == 0
    async with factory() as session:
        row = (await session.execute(select(StagingProduct))).scalar_one()
        assert row.ingestion_run_id == 1
    await engine.dispose()


async def test_run_state_replaced_with_enqueue_set(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    first = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, first, run_id=1))

    second = [{"id": "1", "title": "CHANGED"}, {"id": "2", "title": "B"}]
    ctx = _ctx(factory, feed_source.id, second, run_id=2)
    await StagingStep().execute(ctx)

    assert [p["id"] for p in ctx.run_state.products] == ["1"]
    async with factory() as session:
        histories = (await session.execute(select(StagingHistory))).scalars().all()
    assert len(histories) == 3
    await engine.dispose()


async def test_config_only_change_no_new_history(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    async with factory() as session:
        async with session.begin():
            row = (await session.execute(select(StagingProduct))).scalar_one()
            row.config_hash = "different"

    ctx = _ctx(factory, feed_source.id, products, run_id=2)
    result = await StagingStep().execute(ctx)

    assert result.statistics["staging"]["changed"] == 1
    async with factory() as session:
        histories = (await session.execute(select(StagingHistory))).scalars().all()
    assert len(histories) == 1
    await engine.dispose()


async def test_removal_then_reactivation_round_trip(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    await StagingStep().execute(_ctx(factory, feed_source.id, products[:1], run_id=2))
    rows = await _staged_rows(factory)
    assert rows["2"].status == "removed"
    assert rows["2"].removed_at is not None

    ctx = _ctx(factory, feed_source.id, products, run_id=3)
    result = await StagingStep().execute(ctx)

    assert result.statistics["staging"]["reactivated"] == 1
    assert [p["id"] for p in ctx.run_state.products] == ["2"]
    rows = await _staged_rows(factory)
    assert rows["2"].status == "active"
    assert rows["2"].removed_at is None
    await engine.dispose()


async def test_invalid_and_duplicate_ids_counted_failed(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [
        {"title": "no id"},
        {"id": "1", "title": "first"},
        {"id": "1", "title": "dup"},
    ]

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products))

    assert result.failed_count == 2
    assert result.statistics["staging"]["failed"] == 2
    rows = await _staged_rows(factory)
    assert set(rows) == {"1"}
    assert rows["1"].raw_data["title"] == "first"
    await engine.dispose()


async def test_load_stored_rows_maps_snapshots(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    await StagingStep().execute(
        _ctx(factory, feed_source.id, [{"id": "1", "title": "A"}], run_id=1)
    )

    stored = await load_stored_rows(FactoryAdapter(factory), feed_source.id)

    assert set(stored) == {"1"}
    row = stored["1"]
    assert isinstance(row, StoredRow)
    assert row.snapshot == {"id": "1", "title": "A"}
    assert row.content_hash == content_hash({"id": "1", "title": "A"})
    await engine.dispose()
