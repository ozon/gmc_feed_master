"""Tests for GET /feed-sources/{id}/fields unified shape (Task 7)."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
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


async def test_fields_requires_auth(app_factory):
    app, _ = app_factory
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anon.get("/feed-sources/1/fields")).status_code == 401


async def test_fields_unknown_feed_source_404(app_factory):
    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/99999/fields")).status_code == 404


async def test_fields_unified_shape_from_mapping_document(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(
        f"/clients/{created['id']}/feed-sources",
        json={"name": "DE", "source_format": "xml"},
    )).json()
    async with factory() as session:
        async with session.begin():
            from app.models import FeedSource as FS
            row = await session.get(FS, feed["id"])
            row.field_mapping = {
                "version": 1, "auto_mapped": False,
                "source_fields": [
                    {"name": "title", "kind": "scalar", "sub_fields": [],
                     "max_repeats": 0},
                    {"name": "shipping", "kind": "repeated_structured",
                     "sub_fields": ["country", "price"], "max_repeats": 3},
                ],
                "mappings": {},
            }

    resp = await client.get(f"/feed-sources/{feed['id']}/fields")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["title"]["kind"] == "scalar"
    assert by_name["title"]["sub_fields"] == []
    assert by_name["title"]["max_repeats"] == 1  # non-repeated -> 1
    ship = by_name["shipping"]
    assert ship["kind"] == "repeated_structured"
    assert ship["max_repeats"] == 3
    assert [s["name"] for s in ship["sub_fields"]] == ["country", "price"]
    assert all(s["kind"] == "repeated_scalar" for s in ship["sub_fields"])
    assert by_name["image_link"]["kind"] == "scalar"  # baseline merged
    names = [f["name"] for f in body["fields"]]
    assert names == sorted(names)


async def test_fields_never_ingested_returns_baselines_only(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(
        f"/clients/{created['id']}/feed-sources",
        json={"name": "DE", "source_format": "xml"},
    )).json()
    resp = await client.get(f"/feed-sources/{feed['id']}/fields")
    assert resp.status_code == 200
    names = {f["name"] for f in resp.json()["fields"]}
    assert {"title", "description", "link", "image_link", "availability",
            "price", "condition"} <= names
    assert all(f["kind"] == "scalar" for f in resp.json()["fields"])
