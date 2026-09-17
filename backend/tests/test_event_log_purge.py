from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.event_log import purge_expired_events, record_event
from app.models.event_log import EventLog
from app.models.global_setting import GlobalSetting

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


async def test_purge_uses_default_days_when_no_setting_row(factory):
    now = datetime.now(timezone.utc)
    async with factory() as session, session.begin():
        await session.execute(delete(GlobalSetting))
        await record_event(session, category="audit", level="info", source="backend", message="old")
        await record_event(session, category="audit", level="info", source="backend", message="kept")
    async with factory() as session, session.begin():
        rows = (await session.execute(select(EventLog).order_by(EventLog.id))).scalars().all()
        rows[0].created_at = now - timedelta(days=100)
        rows[1].created_at = now - timedelta(days=10)

    counts = await purge_expired_events(factory, now, default_days=30)
    assert counts.rows == 1

    async with factory() as session:
        remaining = (await session.execute(select(EventLog))).scalars().all()
        assert [r.message for r in remaining] == ["kept"]


async def test_purge_setting_row_overrides_default_days(factory):
    now = datetime.now(timezone.utc)
    async with factory() as session, session.begin():
        await session.execute(delete(GlobalSetting))
        session.add(GlobalSetting(id=1, event_log_retention_days=200))
        await record_event(session, category="audit", level="info", source="backend", message="kept")
    async with factory() as session, session.begin():
        row = (await session.execute(select(EventLog))).scalars().one()
        row.created_at = now - timedelta(days=100)

    counts = await purge_expired_events(factory, now, default_days=30)
    assert counts.rows == 0

    async with factory() as session:
        remaining = (await session.execute(select(EventLog))).scalars().all()
        assert [r.message for r in remaining] == ["kept"]
