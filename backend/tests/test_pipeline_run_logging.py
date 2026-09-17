import pytest
import pytest_asyncio
import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Client, FeedSource
from app.pipeline import LockRegistry, StepResult
from app.pipeline.runner import PipelineRunner

pytestmark = pytest.mark.asyncio


class ContextCapturingStep:
    name = "capture"

    def __init__(self):
        self.contexts = []

    async def execute(self, ctx):
        self.contexts.append(dict(structlog.contextvars.get_contextvars()))
        return StepResult(0, 0, {})


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def feed_source_id(session_factory):
    async with session_factory() as session, session.begin():
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


async def test_pipeline_run_binds_contextvars(session_factory, feed_source_id):
    step = ContextCapturingStep()
    runner = PipelineRunner(LockRegistry(), session_factory, [step])
    run_id = await runner.execute(feed_source_id)

    assert step.contexts, "step did not execute"
    context = step.contexts[0]
    assert context["feed_source_id"] == feed_source_id
    assert context["run_id"] == run_id
    assert context["client_id"] > 0

    assert "run_id" not in structlog.contextvars.get_contextvars()
