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


async def test_registry_attributes_requires_auth(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.get("/registry/attributes")
    assert resp.status_code == 401


async def test_registry_attributes_returns_list_with_expected_shape(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) > 0
    for item in body:
        assert set(item.keys()) == {"name", "kind", "required", "sub_fields", "enum_values", "baseline_required", "max_repeats"}
        assert isinstance(item["sub_fields"], list)
        assert isinstance(item["enum_values"], list)
        for sub in item["sub_fields"]:
            assert "kind" in sub
        for sub in item["sub_fields"]:
            assert set(sub.keys()) == {"name", "type", "required", "kind"}


async def test_registry_attributes_title_is_scalar(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes")
    assert resp.status_code == 200
    body = resp.json()
    title = next((a for a in body if a["name"] == "title"), None)
    assert title is not None
    assert title["kind"] == "scalar"


async def test_registry_attributes_installment_has_sub_fields(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes")
    assert resp.status_code == 200
    body = resp.json()
    installment = next((a for a in body if a["name"] == "installment"), None)
    assert installment is not None
    assert len(installment["sub_fields"]) > 0
    for sub in installment["sub_fields"]:
        assert "name" in sub
        assert "type" in sub
        assert "required" in sub


async def test_registry_attributes_baseline_required_flag(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {a["name"]: a for a in body}

    assert by_name["id"]["baseline_required"] is True
    assert by_name["link"]["baseline_required"] is True
    assert by_name["image_link"]["baseline_required"] is True
    assert by_name["availability"]["baseline_required"] is True
    assert by_name["price"]["baseline_required"] is True
    assert by_name["condition"]["baseline_required"] is True
    assert by_name["title"]["baseline_required"] is True
    assert by_name["structured_title"]["baseline_required"] is True
    assert by_name["description"]["baseline_required"] is True
    assert by_name["structured_description"]["baseline_required"] is True

    assert by_name["brand"]["baseline_required"] is False
    assert by_name["vin"]["baseline_required"] is False
    assert by_name["store_code"]["baseline_required"] is False
    assert by_name["gtin"]["baseline_required"] is False


async def test_registry_attributes_without_feed_source_max_repeats_zero(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes")
    body = resp.json()
    pd = next(a for a in body if a["name"] == "product_detail")
    assert pd["max_repeats"] == 0
    assert pd["sub_fields"][0]["kind"] == "repeated_scalar"


async def test_registry_attributes_with_feed_source_derives_max_repeats(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(
        f"/clients/{created['id']}/feed-sources",
        json={"name": "DE", "source_format": "xml"},
    )).json()
    async with factory() as session, session.begin():
        run = IngestionRun(feed_source_id=feed["id"], status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        session.add(StagingProduct(
            feed_source_id=feed["id"], ingestion_run_id=run.id,
            product_id="a", content_hash="h", config_hash="c",
            status="active", raw_data={"id": "a"},
            processed_data={
                "id": "a",
                "product_detail": [
                    {"section_name": "General", "attribute_name": "Battery",
                     "attribute_value": "5000 mAh"},
                    {"section_name": "General", "attribute_name": "Color",
                     "attribute_value": "Blue"},
                    {"section_name": "Extra"},
                ],
                "additional_image_link": ["x.jpg", "y.jpg"],
            }, excluded=False,
        ))
        session.add(StagingProduct(
            feed_source_id=feed["id"], ingestion_run_id=run.id,
            product_id="b", content_hash="h", config_hash="c",
            status="active", raw_data={"id": "b", "brand": "RawBrand"},
            processed_data=None, excluded=False,
        ))
    resp = await client.get(f"/registry/attributes?feed_source_id={feed['id']}")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {a["name"]: a for a in body}
    assert by_name["product_detail"]["max_repeats"] == 3
    assert by_name["additional_image_link"]["max_repeats"] == 2
    assert by_name["id"]["max_repeats"] == 1
    assert by_name["installment"]["max_repeats"] == 1


async def test_registry_attributes_unknown_feed_source_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes?feed_source_id=99999")
    assert resp.status_code == 404


async def _scoped_client(app_factory, assigned_client_id: int) -> AsyncClient:
    """Log in as a client-scoped 'user' role account."""
    app, _ = app_factory
    from app.persistence.users import create_user
    async with app.state.db_session_factory() as session:
        await create_user(session, "scoped", "scoped-pw", "user", [assigned_client_id])
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "scoped", "password": "scoped-pw"})
    assert resp.status_code == 200
    return client


async def test_registry_attributes_scoped_user_unassigned_feed_source_404(app_factory):
    """RBAC (ADR 0009): a client-scoped user must not read another client's
    feed source data via the registry route's feed_source_id param."""
    client = await logged_in_client(app_factory)
    acme = (await client.post("/clients", json={"name": "Acme"})).json()
    acme_feed = (await client.post(
        f"/clients/{acme['id']}/feed-sources",
        json={"name": "DE", "source_format": "xml"},
    )).json()
    other = (await client.post("/clients", json={"name": "Other Corp"})).json()

    scoped = await _scoped_client(app_factory, other["id"])
    resp = await scoped.get(f"/registry/attributes?feed_source_id={acme_feed['id']}")
    assert resp.status_code == 404


async def test_registry_attributes_scoped_user_assigned_feed_source_200(app_factory):
    client = await logged_in_client(app_factory)
    acme = (await client.post("/clients", json={"name": "Acme"})).json()
    acme_feed = (await client.post(
        f"/clients/{acme['id']}/feed-sources",
        json={"name": "DE", "source_format": "xml"},
    )).json()

    scoped = await _scoped_client(app_factory, acme["id"])
    resp = await scoped.get(f"/registry/attributes?feed_source_id={acme_feed['id']}")
    assert resp.status_code == 200


async def test_registry_attributes_scoped_user_bare_list_allowed(app_factory):
    """Without feed_source_id the registry list stays readable for scoped users."""
    client = await logged_in_client(app_factory)
    acme = (await client.post("/clients", json={"name": "Acme"})).json()
    scoped = await _scoped_client(app_factory, acme["id"])
    resp = await scoped.get("/registry/attributes")
    assert resp.status_code == 200
