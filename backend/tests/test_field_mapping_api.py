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


async def create_feed_source(client, name="Main"):
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": name, "source_format": "xml"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def seed_field_mapping(factory, feed_source_id, doc):
    async with factory() as session:
        async with session.begin():
            feed_source = await session.get(FeedSource, feed_source_id)
            feed_source.field_mapping = doc


def source_field(name, kind, sub_fields=()):
    return {"name": name, "kind": kind, "sub_fields": list(sub_fields)}


async def test_get_field_mapping_missing_feed_source_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/feed-sources/999999/field-mapping")
    assert resp.status_code == 404


async def test_get_field_mapping_never_ingested_returns_empty_document(app_factory):
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    resp = await client.get(f"/feed-sources/{fs_id}/field-mapping")
    assert resp.status_code == 200
    assert resp.json() == {
        "version": 1,
        "auto_mapped": False,
        "source_fields": [],
        "mappings": {},
    }


async def test_put_field_mapping_stores_manual_entries(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1,
            "auto_mapped": True,
            "source_fields": [source_field("product_name", "scalar")],
            "mappings": {"product_name": {"target": "id", "origin": "auto"}},
        },
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {
                "product_name": {"target": "title"},
                "mystery_field": {"target": "shipping.country"},
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mappings"] == {
        "product_name": {"target": "title", "origin": "manual"},
        "mystery_field": {"target": "shipping.country", "origin": "manual"},
    }
    assert body["auto_mapped"] is True
    assert body["source_fields"] == [source_field("product_name", "scalar")]
    persisted = (await client.get(f"/feed-sources/{fs_id}/field-mapping")).json()
    assert persisted == body


async def test_put_field_mapping_empty_mappings_clears(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1,
            "auto_mapped": True,
            "source_fields": [source_field("product_name", "scalar")],
            "mappings": {"product_name": {"target": "title", "origin": "manual"}},
        },
    )
    resp = await client.put(f"/feed-sources/{fs_id}/field-mapping", json={"mappings": {}})
    assert resp.status_code == 200
    assert resp.json()["mappings"] == {}


async def test_put_field_mapping_unknown_attribute_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1,
            "auto_mapped": True,
            "source_fields": [source_field("product_name", "scalar")],
            "mappings": {"product_name": {"target": "title", "origin": "manual"}},
        },
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"product_name": {"target": "bogus_attribute"}}},
    )
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert isinstance(errors, list) and errors
    persisted = (await client.get(f"/feed-sources/{fs_id}/field-mapping")).json()
    assert persisted["mappings"] == {"product_name": {"target": "title", "origin": "manual"}}


async def test_put_field_mapping_invalid_sub_field_returns_422(app_factory):
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"a": {"target": "shipping.bogus"}, "b": {"target": "title.nope"}}},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_field_mapping_duplicate_target_returns_422(app_factory):
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"a": {"target": "title"}, "b": {"target": "title"}}},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_field_mapping_kind_incompatible_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1,
            "auto_mapped": True,
            "source_fields": [source_field("box", "structured")],
            "mappings": {},
        },
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"box": {"target": "gtin"}}},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_field_mapping_scalar_source_to_sub_field_allowed(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1,
            "auto_mapped": True,
            "source_fields": [source_field("months_count", "scalar")],
            "mappings": {},
        },
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"months_count": {"target": "installment.months"}}},
    )
    assert resp.status_code == 200
    assert resp.json()["mappings"] == {
        "months_count": {"target": "installment.months", "origin": "manual"}
    }


async def test_put_field_mapping_missing_feed_source_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.put(
        "/feed-sources/999999/field-mapping",
        json={"mappings": {"a": {"target": "title"}}},
    )
    assert resp.status_code == 404


async def test_post_auto_never_ingested_returns_422(app_factory):
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    resp = await client.post(f"/feed-sources/{fs_id}/field-mapping/auto")
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_post_auto_missing_feed_source_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.post("/feed-sources/999999/field-mapping/auto")
    assert resp.status_code == 404


async def test_post_auto_preserves_manual_and_recomputes(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1,
            "auto_mapped": False,
            "source_fields": [
                source_field("product_name", "scalar"),
                source_field("ean", "scalar"),
            ],
            "mappings": {
                "product_name": {"target": "id", "origin": "manual"},
                "stale": {"target": "title", "origin": "auto"},
            },
        },
    )
    resp = await client.post(f"/feed-sources/{fs_id}/field-mapping/auto")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mappings"]["product_name"] == {"target": "id", "origin": "manual"}
    assert body["mappings"]["ean"] == {"target": "gtin", "origin": "synonym"}
    assert "stale" not in body["mappings"]
    assert body["auto_mapped"] is True
    persisted = (await client.get(f"/feed-sources/{fs_id}/field-mapping")).json()
    assert persisted == body


async def test_field_mapping_endpoints_require_auth(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.get("/feed-sources/1/field-mapping")).status_code == 401
    assert (
        await client.put("/feed-sources/1/field-mapping", json={"mappings": {}})
    ).status_code == 401
    assert (await client.post("/feed-sources/1/field-mapping/auto")).status_code == 401
