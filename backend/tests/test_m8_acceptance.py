import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.ingest.xml_reader import parse_xml
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from registry.loader import load_registry

pytestmark = pytest.mark.asyncio

REGISTRY = load_registry()

WIDE_TSV = (
    "id\ttitle\tdescription\tlink\timage_link\tavailability\tprice\tcondition\tbrand\tgtin\tshipping(country:price)\tshipping(country:price)\n"
    "SKU-1\tRed Shirt\tA red shirt\thttp://shop.example/1\thttp://shop.example/1.jpg\tin_stock\t10.00 USD\tnew\tAcme\t0012345678905\tUS:6.49 USD\tUK:5.99 GBP\n"
    "SKU-2\tBlue Hat\tA blue hat\thttp://shop.example/2\thttp://shop.example/2.jpg\tin_stock\t5.00 USD\tnew\tAcme\t0012345678912\tUS:6.49 USD\n"
).encode("utf-8")

WIDE_TSV_CHANGED = WIDE_TSV.replace(b"10.00 USD\t", b"9.00 USD\t", 1)


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data

    async def fetch(self, url, basic_auth=None):
        return self.data


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
    fetcher = StubFetcher(WIDE_TSV)
    app = create_app(settings=settings, db_session_factory=factory, fetcher=fetcher)
    yield app, factory, settings, fetcher
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _, _ = app_factory
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
        json={
            "name": "Main",
            "source_format": "wide_tsv",
            "currency": "USD",
            "source_url": "http://shop.example/feed.tsv",
        },
    )
    assert resp.status_code == 201
    return client, resp.json()


async def _trigger_run(app_factory, feed_source_id):
    app, factory, _, _ = app_factory
    client = await logged_in_client(app_factory)
    resp = await client.post(f"/feed-sources/{feed_source_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    run = None
    for _ in range(200):
        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
            if run is not None and run.status in ("success", "error"):
                break
        await asyncio.sleep(0.05)
    assert run is not None and run.status == "success", (
        f"run ended in {(run.status if run else 'unknown')}: "
        f"{getattr(run, 'error_message', None)}"
    )
    return run


def _token_of(feed_source_payload):
    return feed_source_payload["export_url"].rsplit("/", 1)[1].removesuffix(".xml")


async def test_full_pipeline_publishes_gmc_xml_at_token_url(app_factory):
    app, factory, _, _ = app_factory
    client, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])

    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await anonymous.get(f"/export/{_token_of(feed_source)}.xml")
    assert resp.status_code == 200
    body = resp.content
    assert body.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert b'<rss version="2.0" xmlns:g="http://base.google.com/schemas/1.0">' in body
    assert b"<g:id>SKU-1</g:id>" in body

    report = parse_xml(body, REGISTRY)
    assert len(report.products) == 2
    sku1 = next(p for p in report.products if p["id"] == "SKU-1")
    assert sku1["shipping"] == [
        {"country": "US", "price": "6.49 USD"},
        {"country": "UK", "price": "5.99 GBP"},
    ]

    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source["id"])
        )).scalars().all())
        runs = list((await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source["id"])
        )).scalars().all())
    assert len(versions) == 1
    assert versions[0].source == "run"
    assert versions[0].product_count == 2
    assert len(runs) == 1
    assert runs[0].status == "completed"
    assert runs[0].export_version_id == versions[0].id


async def test_second_unchanged_run_is_deduplicated(app_factory):
    _, factory, _, _ = app_factory
    _, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])
    second = await _trigger_run(app_factory, feed_source["id"])

    assert second.statistics["export"]["deduplicated"] is True
    assert second.statistics["export"]["version"] == 1
    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source["id"])
        )).scalars().all())
        runs = list((await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source["id"])
            .order_by(ExportRun.id)
        )).scalars().all())
    assert len(versions) == 1
    assert len(runs) == 2
    assert runs[1].status == "completed"
    assert runs[1].export_version_id == versions[0].id


async def test_changed_run_creates_version_and_diff_shows_field_change(app_factory):
    app, factory, _, fetcher = app_factory
    client, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])

    fetcher.data = WIDE_TSV_CHANGED
    await _trigger_run(app_factory, feed_source["id"])

    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source["id"])
            .order_by(ExportVersion.version_number)
        )).scalars().all())
    assert [v.version_number for v in versions] == [1, 2]

    resp = await client.get(f"/feed-sources/{feed_source['id']}/export-history/2/diff")
    assert resp.status_code == 200
    body = resp.json()
    changed = {entry["product_id"]: entry["fields"] for entry in body["changed"]}
    fields = {f["field"]: (f["old"], f["new"]) for f in changed["SKU-1"]}
    assert fields["price"] == ("10.00 USD", "9.00 USD")


async def test_rollback_republishes_old_version(app_factory):
    app, factory, _, fetcher = app_factory
    client, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])
    fetcher.data = WIDE_TSV_CHANGED
    await _trigger_run(app_factory, feed_source["id"])

    resp = await client.post(f"/feed-sources/{feed_source['id']}/export-history/1/rollback")
    assert resp.status_code == 201
    body = resp.json()
    assert body["version_number"] == 3
    assert body["source"] == "rollback"

    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await anonymous.get(f"/export/{_token_of(feed_source)}.xml")
    assert resp.status_code == 200
    report = parse_xml(resp.content, REGISTRY)
    sku1 = next(p for p in report.products if p["id"] == "SKU-1")
    assert sku1["price"] == "10.00 USD"


async def test_rotated_token_invalidates_old_url(app_factory):
    app, _, _, _ = app_factory
    client, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])
    old_token = _token_of(feed_source)

    resp = await client.post(f"/feed-sources/{feed_source['id']}/export-token/rotate")
    assert resp.status_code == 200
    new_token = resp.json()["export_token"]
    assert new_token != old_token

    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anonymous.get(f"/export/{old_token}.xml")).status_code == 404
    assert (await anonymous.get(f"/export/{new_token}.xml")).status_code == 200
