import asyncio
import logging

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Client, FeedSource, IngestionRun
from app.pipeline import LockRegistry, StepContext, StepResult
from app.pipeline.runner import PipelineRunner


pytestmark = pytest.mark.asyncio


class RecordingStep:
    name = "recording"

    def __init__(self, processed=0, failed=0, statistics=None, calls=None):
        self._processed = processed
        self._failed = failed
        self._statistics = statistics or {}
        self._calls = calls if calls is not None else []

    async def execute(self, ctx: StepContext) -> StepResult:
        self._calls.append((self.name, ctx.feed_source_id))
        return StepResult(self._processed, self._failed, dict(self._statistics))


class FailingStep:
    name = "failing"

    async def execute(self, ctx: StepContext) -> StepResult:
        raise RuntimeError("step exploded")


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


async def _get_run(factory, run_id):
    async with factory() as session:
        return await session.get(IngestionRun, run_id)


async def _run_count(factory):
    async with factory() as session:
        return len((await session.execute(select(IngestionRun))).scalars().all())


async def test_success_path_with_default_steps(session_factory, feed_source_id):
    from app.pipeline import default_steps
    from registry.model import RegistryDocument

    class StubFetcher:
        async def fetch(self, url, basic_auth=None, _client=None):
            return b"<rss><channel></channel></rss>"

    steps = default_steps(StubFetcher(), RegistryDocument(attributes={}))
    runner = PipelineRunner(LockRegistry(), session_factory, list(steps))
    run_id = await runner.execute(feed_source_id)
    run = await _get_run(session_factory, run_id)
    assert run.status == "success"
    assert run.processed_count == 0
    assert run.failed_count == 0
    assert run.completed_at is not None
    assert run.error_message is None


async def test_success_path_sums_counts_and_merges_statistics(session_factory, feed_source_id):
    steps = [
        RecordingStep(processed=3, failed=1, statistics={"ingested": 3}),
        RecordingStep(processed=2, failed=0, statistics={"exported": 2}),
    ]
    runner = PipelineRunner(LockRegistry(), session_factory, steps)
    run_id = await runner.execute(feed_source_id)
    run = await _get_run(session_factory, run_id)
    assert run.status == "success"
    assert run.processed_count == 5
    assert run.failed_count == 1
    assert run.statistics == {"ingested": 3, "exported": 2}


async def test_failing_step_records_error_and_swallows_exception(session_factory, feed_source_id):
    runner = PipelineRunner(LockRegistry(), session_factory, [FailingStep()])
    run_id = await runner.execute(feed_source_id)
    run = await _get_run(session_factory, run_id)
    assert run.status == "error"
    assert run.error_message == "step exploded"
    assert "RuntimeError" in run.error_stack_trace
    assert run.completed_at is not None


async def test_lock_held_marks_run_skipped_without_executing_steps(session_factory, feed_source_id):
    registry = LockRegistry()
    calls = []
    steps = [RecordingStep(calls=calls)]
    runner = PipelineRunner(registry, session_factory, steps)
    lock = registry.get(feed_source_id)
    await lock.acquire()
    try:
        run_id = await runner.execute(feed_source_id)
    finally:
        lock.release()
    run = await _get_run(session_factory, run_id)
    assert run.status == "skipped"
    assert run.completed_at is not None
    assert calls == []


async def test_missing_feed_source_returns_none_without_run(session_factory):
    runner = PipelineRunner(LockRegistry(), session_factory, [RecordingStep()])
    result = await runner.execute(999999)
    assert result is None
    assert await _run_count(session_factory) == 0


async def test_precreated_run_id_is_updated_through_lifecycle(session_factory, feed_source_id):
    async with session_factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed_source_id, status="pending")
            session.add(run)
            await session.flush()
            run_id = run.id

    runner = PipelineRunner(LockRegistry(), session_factory, [RecordingStep(processed=1)])
    returned_id = await runner.execute(feed_source_id, run_id=run_id)
    assert returned_id == run_id
    run = await _get_run(session_factory, run_id)
    assert run.status == "success"
    assert run.processed_count == 1
    assert await _run_count(session_factory) == 1


async def test_precreated_run_id_skipped_when_lock_held(session_factory, feed_source_id):
    registry = LockRegistry()
    async with session_factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed_source_id, status="pending")
            session.add(run)
            await session.flush()
            run_id = run.id

    runner = PipelineRunner(registry, session_factory, [RecordingStep()])
    lock = registry.get(feed_source_id)
    await lock.acquire()
    try:
        returned_id = await runner.execute(feed_source_id, run_id=run_id)
    finally:
        lock.release()
    assert returned_id == run_id
    run = await _get_run(session_factory, run_id)
    assert run.status == "skipped"
    assert run.completed_at is not None
    assert await _run_count(session_factory) == 1


async def test_execute_returns_run_id_in_all_paths(session_factory, feed_source_id):
    runner = PipelineRunner(LockRegistry(), session_factory, [RecordingStep()])
    run_id = await runner.execute(feed_source_id)
    assert isinstance(run_id, int)
    assert await _get_run(session_factory, run_id) is not None
