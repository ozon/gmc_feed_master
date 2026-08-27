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
        assert set(item.keys()) == {"name", "kind", "required", "sub_fields", "enum_values"}
        assert isinstance(item["sub_fields"], list)
        assert isinstance(item["enum_values"], list)
        for sub in item["sub_fields"]:
            assert set(sub.keys()) == {"name", "type", "required"}


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
