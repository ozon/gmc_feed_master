import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.client import Client
from app.models.plugin import Plugin
from app.models.session import Session
from app.models.user import User
from app.models.user_client import UserClient
from app.persistence.users import seed_initial_user
from app.security.passwords import hash_password


@pytest_asyncio.fixture
async def scope_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(UserClient))
            await session.execute(delete(Client))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
        async with session.begin():
            acme = Client(name="Acme")
            session.add(acme)
            await session.flush()
            bob = User(username="bob", password_hash=hash_password("bob-pass"), role="user")
            session.add(bob)
            await session.flush()
            session.add(UserClient(user_id=bob.id, client_id=acme.id))
        manifest = {
            "id": "custom_labels",
            "name": "Custom Labels",
            "version": "1.0.0",
            "extension_point": "pipeline_module",
            "config_schema": {"type": "object", "properties": {"slotRules": {"type": "array"}}},
            "data_schema": {"type": "object", "properties": {"slotIds": {"type": "object"}}},
            "config_scope": ["global", "client"],
            "data_scope": ["client", "feed_source"],
        }
        async with session.begin():
            session.add(Plugin(name="custom_labels", version="1.0.0", manifest=manifest, enabled=True))
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app
    await engine.dispose()


async def _login(client: AsyncClient, username: str, password: str) -> None:
    response = await client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_scoped_user_cannot_read_or_write_global_plugin_config(scope_app):
    app = scope_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as bob:
        await _login(bob, "bob", "bob-pass")
        assert (await bob.get("/plugins/custom_labels/config")).status_code == 403
        assert (await bob.put(
            "/plugins/custom_labels/config", json={"slotRules": []}
        )).status_code == 403


@pytest.mark.asyncio
async def test_scoped_user_cannot_read_or_write_global_plugin_data(scope_app):
    app = scope_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as bob:
        await _login(bob, "bob", "bob-pass")
        assert (await bob.get("/plugins/custom_labels/data")).status_code == 403
        assert (await bob.put(
            "/plugins/custom_labels/data", json={"slotIds": {}}
        )).status_code == 403


@pytest.mark.asyncio
async def test_admin_can_read_global_plugin_config(scope_app):
    app = scope_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as admin:
        await _login(admin, "operator", "admin-pass")
        assert (await admin.get("/plugins/custom_labels/config")).status_code == 200


@pytest.mark.asyncio
async def test_scoped_user_can_use_client_tier(scope_app):
    app = scope_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as bob:
        await _login(bob, "bob", "bob-pass")
        response = await bob.get("/plugins/custom_labels/config?client_id=1")
        assert response.status_code == 200
        assert response.json() == {}


@pytest.mark.asyncio
async def test_malformed_scope_query_params_return_422(scope_app):
    app = scope_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as bob:
        await _login(bob, "bob", "bob-pass")
        assert (await bob.get("/plugins?client_id=abc")).status_code == 422
        assert (await bob.get("/plugins/custom_labels/config?feed_source_id=xyz")).status_code == 422
