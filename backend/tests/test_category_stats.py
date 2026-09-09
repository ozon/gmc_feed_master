"""Category stats/matches/product routes: buckets, paging, cross-tenant guard."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import hash_password, seed_initial_user
from tests.category_plugin_module import category_plugin as cp

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
    router = APIRouter()
    cp.CategoryPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/category")
    yield app, factory
    await engine.dispose()


async def login(app, username, password):
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    return client


async def admin_client(app_factory):
    app, _ = app_factory
    return await login(app, "operator", "pw")


async def _setup_feed(factory, client):
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    rows = [
        ("p-manual",
         {"id": "p-manual", "title": "Manual Boot", "google_product_category": "53"},
         {"id": "p-manual", "title": "Manual Boot", "google_product_category": "53",
          "_category_provenance": "manual"}),
        ("p-auto",
         {"id": "p-auto", "title": "Auto Shoe", "google_product_category": "166"},
         {"id": "p-auto", "title": "Auto Shoe", "google_product_category": "166",
          "_category_provenance": "auto", "_category_rule_id": "r-auto"}),
        ("p-excl",
         {"id": "p-excl", "title": "Excluded Sock", "google_product_category": ""},
         {"id": "p-excl", "title": "Excluded Sock", "google_product_category": "",
          "_category_provenance": "excluded", "_category_rule_id": "r-excl"}),
        ("p-none",
         {"id": "p-none", "title": "Naked Hat"},
         {"id": "p-none", "title": "Naked Hat"}),
        ("p-removed",
         {"id": "p-removed", "title": "Gone"},
         {"id": "p-removed", "title": "Gone"}),
    ]
    async with factory() as session, session.begin():
        run = IngestionRun(feed_source_id=feed["id"], status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        for pid, raw, processed in rows:
            status = "removed" if pid == "p-removed" else "active"
            session.add(StagingProduct(
                feed_source_id=feed["id"], ingestion_run_id=run.id, product_id=pid,
                content_hash="x", config_hash="x", status=status, excluded=False,
                raw_data=raw, processed_data=processed,
            ))
    return feed


class TestStats:
    async def test_buckets_and_rule_counts(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(f"/plugins/category/stats?feed_source_id={feed['id']}")
        assert resp.status_code == 200
        assert resp.json() == {
            "total": 4,
            "buckets": {"manual": 1, "auto": 1, "excluded": 1, "uncategorized": 1},
            "rules": {"r-auto": 1, "r-excl": 1},
        }

    async def test_unknown_feed_source_404(self, app_factory):
        client = await admin_client(app_factory)
        resp = await client.get("/plugins/category/stats?feed_source_id=99999")
        assert resp.status_code == 404


class TestMatches:
    async def test_paged_matches_with_titles(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(
            f"/plugins/category/matches?feed_source_id={feed['id']}"
            f"&rule_id=r-auto&limit=50&offset=0"
        )
        assert resp.json() == {
            "total": 1,
            "items": [{"product_id": "p-auto", "title": "Auto Shoe"}],
        }

    async def test_unknown_rule_matches_nothing(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(
            f"/plugins/category/matches?feed_source_id={feed['id']}"
            f"&rule_id=r-none&limit=50&offset=0"
        )
        assert resp.json() == {"total": 0, "items": []}


class TestProductRoute:
    async def test_product_state(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(
            f"/plugins/category/product?feed_source_id={feed['id']}&product_id=p-auto"
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "product_id": "p-auto", "title": "Auto Shoe", "provenance": "auto",
            "rule_id": "r-auto", "google_product_category": "166", "status": "active",
        }

    async def test_unknown_product_404(self, app_factory):
        client = await admin_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client)
        resp = await client.get(
            f"/plugins/category/product?feed_source_id={feed['id']}&product_id=nope"
        )
        assert resp.status_code == 404


class TestCrossTenant:
    async def test_scoped_user_gets_404_on_foreign_feed_source(self, app_factory):
        app, factory = app_factory
        admin = await admin_client(app_factory)
        feed = await _setup_feed(factory, admin)
        other = (await admin.post("/clients", json={"name": "Other"})).json()
        async with factory() as session, session.begin():
            from app.models.user_client import UserClient

            bob = User(
                username="bob", password_hash=hash_password("bob-pass"), role="user"
            )
            session.add(bob)
            await session.flush()
            session.add(UserClient(user_id=bob.id, client_id=other["id"]))
        bob_client = await login(app, "bob", "bob-pass")
        resp = await bob_client.get(
            f"/plugins/category/stats?feed_source_id={feed['id']}"
        )
        assert resp.status_code == 404
