from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.export import ExportRun
from app.models.feed_source import FeedSource
from app.models.ingestion import IngestionRun
from app.models.quality import QualityFinding
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.qc.engine import Finding
from app.qc.persistence import persist_findings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(QualityFinding))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def feed_source_id(session_factory):
    async with session_factory() as session, session.begin():
            client = Client(name="delta-client")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="delta-feed",
                source_format="tsv",
                source_url="http://test.local/feed.tsv",
                configuration={},
            )
            session.add(feed_source)
            await session.flush()
            for run_id in (100, 101):
                session.add(IngestionRun(id=run_id, feed_source_id=feed_source.id, status="completed"))
            return feed_source.id


async def _export_rows(session_factory, feed_source_id):
    async with session_factory() as session:
        return list((await session.execute(
            select(ExportRun)
            .where(ExportRun.feed_source_id == feed_source_id)
            .order_by(ExportRun.id)
        )).scalars())


async def test_persist_findings_counts_fixed_new_remaining(session_factory, feed_source_id):
    run_one = [
        Finding(rule_id="r", severity="critical", field="title", message="m", product_id="p1"),
        Finding(rule_id="r", severity="critical", field="brand", message="m", product_id="p2"),
    ]
    await persist_findings(session_factory, feed_source_id, 100, run_one, 2)
    run_two = [
        Finding(rule_id="r", severity="critical", field="title", message="changed msg", product_id="p1"),  # remaining (same key)
        Finding(rule_id="r", severity="critical", field="gtin", message="m", product_id="p3"),             # new
    ]
    await persist_findings(session_factory, feed_source_id, 101, run_two, 2)

    rows = await _export_rows(session_factory, feed_source_id)
    assert len(rows) == 2
    first, second = rows
    assert (first.fixed_finding_count, first.new_finding_count, first.remaining_finding_count) == (0, 2, 0)
    assert (second.fixed_finding_count, second.new_finding_count, second.remaining_finding_count) == (1, 1, 1)
