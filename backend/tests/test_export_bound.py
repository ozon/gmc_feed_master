import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Client, FeedSource, IngestionRun
from app.models.staging import StagingProduct
from app.staging.persistence import load_export_bound

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(session_factory):
    async with session_factory() as session:
        async with session.begin():
            client = Client(name="C")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="F",
                source_format="tsv",
                export_token="tok-bound-test",
            )
            session.add(feed_source)
            await session.flush()
            run = IngestionRun(feed_source_id=feed_source.id, status="completed")
            session.add(run)
            await session.flush()

            def row(product_id, status, raw, processed=None, excluded=False):
                return StagingProduct(
                    feed_source_id=feed_source.id,
                    ingestion_run_id=run.id,
                    product_id=product_id,
                    content_hash="c" + product_id,
                    config_hash="g" + product_id,
                    status=status,
                    raw_data=raw,
                    processed_data=processed,
                    excluded=excluded,
                )

            session.add(row("b", "active", {"id": "b", "title": "raw-b"}, {"id": "b", "title": "proc-b"}))
            session.add(row("a", "active", {"id": "a", "title": "raw-a"}, None))
            session.add(row("x", "active", {"id": "x"}, {"id": "x"}, excluded=True))
            session.add(row("r", "removed", {"id": "r"}, None))
            return feed_source.id


async def test_load_export_bound_filters_and_falls_back(session_factory):
    feed_source_id = await _seed(session_factory)
    bound = await load_export_bound(session_factory, feed_source_id)
    assert [(pid, product["title"] if "title" in product else None) for pid, product in bound] == [
        ("a", "raw-a"),
        ("b", "proc-b"),
    ]
