import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.export.store import ExportFileStore
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio


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


async def _create_feed_source(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Main", "source_format": "tsv"},
    )
    assert resp.status_code == 201
    return client, resp.json()


async def test_create_feed_source_generates_token_and_export_url(app_factory):
    _, payload = await _create_feed_source(app_factory)
    assert payload["feed_type"] == "primary"
    assert payload["history_retention_count"] == 30
    assert payload["export_url"].startswith("http://test.public/export/")
    assert payload["export_url"].endswith(".xml")

    _, factory, _ = app_factory
    async with factory() as session:
        row = (await session.execute(select(FeedSource))).scalar_one()
        assert row.feed_type == "primary"
        assert row.export_token
        assert payload["export_url"] == f"http://test.public/export/{row.export_token}.xml"


async def test_public_endpoint_404_for_unknown_token_and_before_export(app_factory):
    client, payload = await _create_feed_source(app_factory)
    token = payload["export_url"].rsplit("/", 1)[1].removesuffix(".xml")

    resp = await client.get("/export/does-not-exist.xml")
    assert resp.status_code == 404

    resp = await client.get(f"/export/{token}.xml")
    assert resp.status_code == 404


async def test_public_endpoint_serves_published_file_without_auth(app_factory):
    app, factory, settings = app_factory
    client, payload = await _create_feed_source(app_factory)
    token = payload["export_url"].rsplit("/", 1)[1].removesuffix(".xml")

    async with factory() as session:
        feed_source_id = (await session.execute(select(FeedSource))).scalar_one().id

    store = ExportFileStore(settings.export_dir)
    store.publish(feed_source_id, b"<rss>published</rss>")

    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await anonymous.get(f"/export/{token}.xml")
    assert resp.status_code == 200
    assert resp.content == b"<rss>published</rss>"
    assert resp.headers["content-type"].startswith("application/xml")


async def test_rotate_token_invalidates_old_url_immediately(app_factory):
    app, factory, settings = app_factory
    client, payload = await _create_feed_source(app_factory)
    old_url = payload["export_url"]
    old_token = old_url.rsplit("/", 1)[1].removesuffix(".xml")
    feed_source_id = payload["id"]

    ExportFileStore(settings.export_dir).publish(feed_source_id, b"<rss/>")

    resp = await client.post(f"/feed-sources/{feed_source_id}/export-token/rotate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["export_url"] != old_url
    assert body["export_token"] != old_token

    assert (await client.get(f"/export/{old_token}.xml")).status_code == 404
    resp = await client.get(f"/export/{body['export_token']}.xml")
    assert resp.status_code == 200


async def test_delete_feed_source_removes_export_files(app_factory):
    client, payload = await _create_feed_source(app_factory)
    _, _, settings = app_factory
    feed_source_id = payload["id"]
    store = ExportFileStore(settings.export_dir)
    store.publish(feed_source_id, b"<rss/>")
    store.write_version(feed_source_id, 1, b"<rss/>")

    resp = await client.delete(f"/feed-sources/{feed_source_id}")
    assert resp.status_code == 204
    assert not store.published_exists(feed_source_id)
    assert store.read_version(feed_source_id, 1) is None
