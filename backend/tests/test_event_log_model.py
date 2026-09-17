import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.event_log import EventLog

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    f = async_sessionmaker(engine, expire_on_commit=False)
    yield f
    await engine.dispose()


async def test_event_log_roundtrip_defaults(factory):
    async with factory() as session, session.begin():
        session.add(EventLog(category="audit", level="info", source="backend", message="hello"))
    async with factory() as session:
        row = (await session.execute(select(EventLog))).scalar_one()
        assert row.id > 0
        assert row.context == {}
        assert row.created_at is not None
        assert row.actor is None
