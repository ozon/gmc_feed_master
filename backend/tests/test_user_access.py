import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.client import Client
from app.models.session import Session
from app.models.user import User
from app.models.user_client import UserClient
from app.persistence.users import seed_initial_user
from app.security.passwords import hash_password


@pytest_asyncio.fixture
async def access_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(UserClient))
            await session.execute(delete(User))
            await session.execute(delete(Client))
        await seed_initial_user(session, "operator", "admin-pass")
        async with session.begin():
            session.add(Client(name="Acme"))
            session.add(Client(name="Other Corp"))
            regular = User(username="bob", password_hash="x", role="user")
            session.add(regular)
            session.add(User(username="mallory", password_hash="x", role="user", is_active=False))
            await session.flush()
            session.add(UserClient(user_id=regular.id, client_id=1))
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_login_rejects_inactive_user(access_app):
    app, factory = access_app
    async with factory() as session, session.begin():
        user = (await session.execute(
            select(User).where(User.username == "mallory")
        )).scalar_one()
        user.password_hash = hash_password("inactive-pass")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/auth/login", json={"username": "mallory", "password": "inactive-pass"}
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_reports_role_and_clients(access_app):
    app, _ = access_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        assert (await client.post(
            "/auth/login", json={"username": "operator", "password": "admin-pass"}
        )).status_code == 200
        me = await client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "operator"
        assert me.json()["role"] == "admin"
        assert me.json()["client_ids"] is None


@pytest.mark.asyncio
async def test_auth_me_for_regular_user_lists_assigned_clients(access_app):
    app, factory = access_app
    async with factory() as session, session.begin():
        user = (await session.execute(
            select(User).where(User.username == "bob")
        )).scalar_one()
        user.password_hash = hash_password("bob-pass")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        assert (await client.post(
            "/auth/login", json={"username": "bob", "password": "bob-pass"}
        )).status_code == 200
        me = await client.get("/auth/me")
        assert me.status_code == 200
        body = me.json()
        assert body["role"] == "user"
        assert body["client_ids"] == [1]
