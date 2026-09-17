from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.event_log import purge_expired_events, record_event
from app.models.event_log import EventLog

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    f = async_sessionmaker(engine, expire_on_commit=False)
    yield f
    await engine.dispose()


async def test_purge_removes_rows_older_than_retention(factory):
    now = datetime.now(timezone.utc)
    async with factory() as session, session.begin():
        await record_event(session, category="audit", level="info", source="backend", message="old")
        await record_event(session, category="audit", level="info", source="backend", message="new")
    async with factory() as session, session.begin():
        rows = (await session.execute(select(EventLog).order_by(EventLog.id))).scalars().all()
        rows[0].created_at = now - timedelta(days=400)
        rows[1].created_at = now - timedelta(days=1)

    counts = await purge_expired_events(factory, now)
    assert counts.rows == 1

    async with factory() as session:
        remaining = (await session.execute(select(EventLog))).scalars().all()
        assert [r.message for r in remaining] == ["new"]
