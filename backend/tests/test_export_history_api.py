import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.export.service import ExportService
from app.export.store import ExportFileStore
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.clock import TestClock
from datetime import datetime, timezone
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


async def _seed_versions(app_factory, product_sets, finding_counts=None):
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
                export_token="tok-history-test",
            )
            session.add(feed_source)
            await session.flush()
            feed_source_id = feed_source.id

    service = ExportService(factory, ExportFileStore(settings.export_dir), clock, "http://test.public")
    for index, products in enumerate(product_sets):
        counts = finding_counts[index] if finding_counts else (0, 0, 0)
        async with factory() as session:
            async with session.begin():
                run = IngestionRun(feed_source_id=feed_source_id, status="completed")
                session.add(run)
                await session.flush()
                session.add(ExportRun(
                    feed_source_id=feed_source_id, ingestion_run_id=run.id,
                    status="pending_export", product_count=len(products),
                    critical_finding_count=counts[0],
                    warning_finding_count=counts[1],
                    info_finding_count=counts[2],
                ))
                run_id = run.id
        await service.export_for_run(feed_source_id, run_id, products, REGISTRY)
    return feed_source_id


BASE = [{"id": "A", "title": "Shirt", "price": "10 USD"}]
CHANGED = [{"id": "A", "title": "Shirt v2", "price": "9 USD"}, {"id": "B", "title": "Hat", "price": "5 USD"}]


async def test_history_lists_versions_descending(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history")
    assert resp.status_code == 200
    body = resp.json()
    assert [v["version_number"] for v in body] == [2, 1]
    assert body[0]["source"] == "run"
    assert body[0]["product_count"] == 2
    assert len(body[0]["file_hash"]) == 64
    assert body[0]["source_version_id"] is None
    assert body[0]["findings"] == {"critical": 0, "warning": 0, "info": 0}
    assert body[0]["url"] == "http://test.public/export/tok-history-test.xml"
    assert body[1]["findings"] == {"critical": 0, "warning": 0, "info": 0}
    assert body[1]["url"] == "http://test.public/export/tok-history-test.xml"


async def test_history_reports_run_finding_counts_per_version(app_factory):
    feed_source_id = await _seed_versions(
        app_factory, [BASE, CHANGED], finding_counts=[(0, 0, 0), (1, 2, 3)]
    )
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["version_number"] == 2
    assert body[0]["findings"] == {"critical": 1, "warning": 2, "info": 3}
    assert body[1]["version_number"] == 1
    assert body[1]["findings"] == {"critical": 0, "warning": 0, "info": 0}


async def test_history_shows_rollback_version_as_not_qc_d(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)
    rollback_resp = await client.post(f"/feed-sources/{feed_source_id}/export-history/1/rollback")
    assert rollback_resp.status_code == 201

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["version_number"] == 3
    assert body[0]["source"] == "rollback"
    assert body[0]["findings"] is None
    assert body[0]["url"] == "http://test.public/export/tok-history-test.xml"
    assert body[1]["source"] == "run"
    assert body[1]["findings"] == {"critical": 0, "warning": 0, "info": 0}


async def test_history_requires_auth_and_known_feed_source(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    app, _, _ = app_factory
    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anonymous.get(f"/feed-sources/{feed_source_id}/export-history")).status_code == 401

    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/999999/export-history")).status_code == 404


async def test_diff_reports_added_removed_and_changed_fields(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/2/diff?against=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 2
    assert body["against"] == 1
    assert body["added"] == ["B"]
    assert body["removed"] == []
    changed = {entry["product_id"]: entry["fields"] for entry in body["changed"]}
    assert set(changed) == {"A"}
    fields = {f["field"]: (f["old"], f["new"]) for f in changed["A"]}
    assert fields["title"] == ("Shirt", "Shirt v2")
    assert fields["price"] == ("10 USD", "9 USD")


async def test_diff_defaults_to_preceding_version(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/2/diff")
    assert resp.status_code == 200
    assert resp.json()["against"] == 1


async def test_diff_404_cases(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    client = await logged_in_client(app_factory)

    assert (await client.get(f"/feed-sources/{feed_source_id}/export-history/9/diff")).status_code == 404
    assert (await client.get(f"/feed-sources/{feed_source_id}/export-history/1/diff")).status_code == 404
    assert (await client.get(f"/feed-sources/{feed_source_id}/export-history/1/diff?against=9")).status_code == 404
