from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.config import Settings
from app.export.service import ExportService
from app.export.store import ExportFileStore
from app.ingest.xml_reader import parse_xml
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from registry.loader import load_registry

pytestmark = pytest.mark.asyncio

REGISTRY = load_registry()


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
        export_dir=str(tmp_path / "exports"),
        public_base_url="http://test.public",
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_versions(app_factory, product_sets):
    """Run export_for_run once per product set; returns feed_source_id."""
    _, factory, settings = app_factory
    clock = TestClock(datetime(2026, 8, 27, tzinfo=timezone.utc))
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id, name="Main", source_format="tsv",
                export_token="tok-rollback-test",
            )
            session.add(feed_source)
            await session.flush()
            feed_source_id = feed_source.id

    service = ExportService(factory, ExportFileStore(settings.export_dir), clock, "http://test.public")
    for products in product_sets:
        async with factory() as session:
            async with session.begin():
                run = IngestionRun(feed_source_id=feed_source_id, status="completed")
                session.add(run)
                await session.flush()
                session.add(ExportRun(
                    feed_source_id=feed_source_id, ingestion_run_id=run.id,
                    status="pending_export", product_count=len(products),
                ))
                run_id = run.id
        await service.export_for_run(feed_source_id, run_id, products, REGISTRY)
    return feed_source_id


BASE = [{"id": "A", "title": "Shirt", "price": "10 USD"}]
CHANGED = [{"id": "A", "title": "Shirt v2", "price": "9 USD"}]


async def test_rollback_creates_new_version_and_republishes_old_content(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.post(f"/feed-sources/{feed_source_id}/export-history/1/rollback")
    assert resp.status_code == 201
    body = resp.json()
    assert body["version_number"] == 3
    assert body["source"] == "rollback"
    assert body["source_version_id"] is not None

    _, factory, settings = app_factory
    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source_id)
            .order_by(ExportVersion.version_number)
        )).scalars().all())
        runs = list((await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source_id)
            .order_by(ExportRun.id)
        )).scalars().all())

    assert [v.version_number for v in versions] == [1, 2, 3]
    assert versions[2].source_version_id == versions[0].id
    assert versions[2].file_hash == versions[0].file_hash

    rollback_run = runs[-1]
    assert rollback_run.status == "rollback"
    assert rollback_run.ingestion_run_id is None
    assert rollback_run.product_count == 1
    assert rollback_run.critical_finding_count == 0
    assert rollback_run.warning_finding_count == 0
    assert rollback_run.info_finding_count == 0
    assert rollback_run.id == versions[2].export_run_id

    published = ExportFileStore(settings.export_dir).published_path(feed_source_id).read_bytes()
    report = parse_xml(published, REGISTRY)
    assert report.products == [BASE[0]]


async def test_rollback_after_deduplicated_run_still_creates_version(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, BASE])
    client = await logged_in_client(app_factory)

    resp = await client.post(f"/feed-sources/{feed_source_id}/export-history/1/rollback")
    assert resp.status_code == 201
    assert resp.json()["version_number"] == 2
    assert resp.json()["source"] == "rollback"


async def test_rollback_404_for_unknown_version_or_feed_source(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    client = await logged_in_client(app_factory)
    assert (await client.post(f"/feed-sources/{feed_source_id}/export-history/9/rollback")).status_code == 404
    assert (await client.post("/feed-sources/999999/export-history/1/rollback")).status_code == 404


async def test_rollback_respects_retention(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    _, factory, settings = app_factory
    async with factory() as session:
        async with session.begin():
            fs = await session.get(FeedSource, feed_source_id)
            fs.history_retention_count = 2

    client = await logged_in_client(app_factory)
    resp = await client.post(f"/feed-sources/{feed_source_id}/export-history/1/rollback")
    assert resp.status_code == 201

    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source_id)
            .order_by(ExportVersion.version_number)
        )).scalars().all())
    assert [v.version_number for v in versions] == [2, 3]
    store = ExportFileStore(settings.export_dir)
    assert store.read_version(feed_source_id, 1) is None
