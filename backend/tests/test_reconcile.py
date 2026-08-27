from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.models import Client, FeedSource, IngestionRun
from app.pipeline.reconcile import INTERRUPTED_MESSAGE, reconcile_interrupted_runs


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def feed_source_id(session_factory):
    async with session_factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="xml",
                source_url="https://example.com/feed.xml",
            )
            session.add(feed_source)
            await session.flush()
            return feed_source.id


async def _seed_run(factory, feed_source_id, status):
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed_source_id, status=status)
            session.add(run)
            await session.flush()
            return run.id


async def _get_run(factory, run_id):
    async with factory() as session:
        return await session.get(IngestionRun, run_id)


async def test_reconcile_flips_only_nonterminal_runs(session_factory, feed_source_id):
    running_id = await _seed_run(session_factory, feed_source_id, "running")
    pending_id = await _seed_run(session_factory, feed_source_id, "pending")
    success_id = await _seed_run(session_factory, feed_source_id, "success")
    error_id = await _seed_run(session_factory, feed_source_id, "error")
    skipped_id = await _seed_run(session_factory, feed_source_id, "skipped")
    clock = TestClock(datetime(2026, 2, 3, 4, 5, tzinfo=timezone.utc))

    count = await reconcile_interrupted_runs(session_factory, clock)

    assert count == 2
    for run_id in (running_id, pending_id):
        run = await _get_run(session_factory, run_id)
        assert run.status == "error"
        assert run.error_message == INTERRUPTED_MESSAGE
        assert run.completed_at == clock.now()
    assert (await _get_run(session_factory, success_id)).status == "success"
    assert (await _get_run(session_factory, error_id)).status == "error"
    assert (await _get_run(session_factory, skipped_id)).status == "skipped"
    for run_id in (success_id, error_id, skipped_id):
        assert (await _get_run(session_factory, run_id)).error_message != INTERRUPTED_MESSAGE


async def test_reconcile_empty_table_returns_zero(session_factory):
    clock = TestClock(datetime(2026, 2, 3, tzinfo=timezone.utc))
    assert await reconcile_interrupted_runs(session_factory, clock) == 0
