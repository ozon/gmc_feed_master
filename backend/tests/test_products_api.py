from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(StagingProduct))
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
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _setup_feed(factory, client, products):
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed["id"], status="success",
                               started_at=datetime.now(timezone.utc))
            session.add(run)
            await session.flush()
            for pid, raw, status in products:
                session.add(
                    StagingProduct(
                        feed_source_id=feed["id"], ingestion_run_id=run.id,
                        product_id=pid, content_hash="h", config_hash="c",
                        status=status, raw_data=raw,
                    )
                )
    return feed["id"]


_BASE = {"title": "T", "description": "D", "link": "L", "image_link": "I",
         "availability": "in_stock", "price": "1.00 EUR", "condition": "new"}


async def test_products_requires_auth_and_404(app_factory):
    app, _ = app_factory
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anon.get("/feed-sources/1/products")).status_code == 401
    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/99999/products")).status_code == 404


async def test_products_stage_processed_returns_501(app_factory):
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(app_factory[1], client, [])
    assert (await client.get(f"/feed-sources/{feed_id}/products", params={"stage": "processed"})).status_code == 501


async def test_products_pagination_search_filter_sort(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    products = [
        ("a", {"id": "a", **_BASE, "title": "Alpha Shoe"}, "active"),
        ("b", {"id": "b", **_BASE, "title": "Beta Shirt"}, "active"),
        ("c", {"id": "c", **_BASE, "title": "Gamma Shoe"}, "removed"),
    ]
    feed_id = await _setup_feed(factory, client, products)

    resp = await client.get(f"/feed-sources/{feed_id}/products")
    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 1 and body["page_size"] == 50
    assert [i["product_id"] for i in body["items"]] == ["a", "b", "c"]
    item = body["items"][0]
    for key in ("id", "title", "description", "link", "image_link",
                "availability", "price", "condition", "status", "last_seen_at"):
        assert key in item

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"page_size": 2, "page": 2})
    body = resp.json()
    assert [i["product_id"] for i in body["items"]] == ["c"]

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"q": "shoe"})
    assert [i["product_id"] for i in resp.json()["items"]] == ["a", "c"]

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"q": "a", "status": "active"})
    assert [i["product_id"] for i in resp.json()["items"]] == ["a", "b"]

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"status": "removed"})
    assert [i["product_id"] for i in resp.json()["items"]] == ["c"]

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"sort": "-title"})
    assert [i["title"] for i in resp.json()["items"]] == ["Gamma Shoe", "Beta Shirt", "Alpha Shoe"]
    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"sort": "-product_id"})
    assert [i["product_id"] for i in resp.json()["items"]] == ["c", "b", "a"]

    assert (await client.get(f"/feed-sources/{feed_id}/products", params={"sort": "bogus"})).status_code == 422
    assert (await client.get(f"/feed-sources/{feed_id}/products", params={"status": "bogus"})).status_code == 422


async def test_products_list_returns_fields_union_and_raw_data(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    products = [
        ("a", {"id": "a", **_BASE, "title": "Alpha", "brand": "Acme",
               "custom_label_2": "sale"}, "active"),
        ("b", {"id": "b", **_BASE, "title": "Beta", "brand": "Acme"}, "active"),
    ]
    feed_id = await _setup_feed(factory, client, products)

    body = (await client.get(f"/feed-sources/{feed_id}/products")).json()
    # Union of raw_data keys across the returned rows, sorted.
    assert body["fields"] == [
        "availability", "brand", "condition", "custom_label_2",
        "description", "id", "image_link", "link", "price", "title",
    ]
    # Baseline keys stay on items; raw_data is attached per item.
    for key in ("id", "title", "description", "price", "condition"):
        assert key in body["items"][0]
    assert body["items"][0]["raw_data"]["brand"] == "Acme"
    assert body["items"][1]["raw_data"].get("custom_label_2") is None


async def test_product_detail_returns_full_raw_data(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client,
                                [("a", {"id": "a", **_BASE, "shipping": [{"country": "DE", "price": "1 EUR"}]}, "active")])
    resp = await client.get(f"/feed-sources/{feed_id}/products/a")
    assert resp.status_code == 200
    body = resp.json()
    assert body["product_id"] == "a"
    assert body["status"] == "active"
    assert body["raw_data"]["shipping"] == [{"country": "DE", "price": "1 EUR"}]
    assert (await client.get(f"/feed-sources/{feed_id}/products/missing")).status_code == 404
