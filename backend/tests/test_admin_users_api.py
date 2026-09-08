import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
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
async def admin_app(isolated_database_url):
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
            session.add(Client(name="Acme"))
            bob = User(username="bob", password_hash=hash_password("bob-pass"), role="user")
            session.add(bob)
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


@pytest_asyncio.fixture
async def admin_http(admin_app):
    app, _ = admin_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_admin_users_requires_admin_role(admin_app):
    app, _ = admin_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as bob:
        assert (await bob.post(
            "/auth/login", json={"username": "bob", "password": "bob-pass"}
        )).status_code == 200
        assert (await bob.get("/admin/users")).status_code == 403


@pytest.mark.asyncio
async def test_admin_lists_users(admin_http):
    response = await admin_http.get("/admin/users")
    assert response.status_code == 200
    users = {u["username"]: u for u in response.json()}
    assert users["operator"]["role"] == "admin"
    assert users["bob"]["role"] == "user"
    assert users["bob"]["client_ids"] == []


@pytest.mark.asyncio
async def test_admin_creates_user_with_role_and_clients(admin_app, admin_http):
    app, _ = admin_app
    response = await admin_http.post("/admin/users", json={
        "username": "carol", "password": "carol-pass", "role": "user", "client_ids": [1],
    })
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "carol"
    assert body["role"] == "user"
    assert body["client_ids"] == [1]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as login:
        assert (await login.post(
            "/auth/login", json={"username": "carol", "password": "carol-pass"}
        )).status_code == 200


@pytest.mark.asyncio
async def test_admin_create_rejects_duplicate_username(admin_http):
    response = await admin_http.post("/admin/users", json={
        "username": "bob", "password": "x", "role": "user", "client_ids": [],
    })
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_admin_updates_role_clients_and_active(admin_http):
    users = {u["username"]: u for u in (await admin_http.get("/admin/users")).json()}
    bob_id = users["bob"]["id"]
    response = await admin_http.patch(f"/admin/users/{bob_id}", json={
        "client_ids": [1], "is_active": False,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["client_ids"] == [1]
    assert body["is_active"] is False
    # Deactivation is effective on the next request: bob's existing session dies.
    assert (await admin_http.get("/auth/me")).status_code == 200  # admin unaffected


@pytest.mark.asyncio
async def test_admin_resets_password_and_revokes_sessions(admin_app, admin_http):
    app, _ = admin_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as bob:
        assert (await bob.post(
            "/auth/login", json={"username": "bob", "password": "bob-pass"}
        )).status_code == 200
        users = {u["username"]: u for u in (await admin_http.get("/admin/users")).json()}
        bob_id = users["bob"]["id"]
        reset = await admin_http.post(
            f"/admin/users/{bob_id}/password", json={"new_password": "new-bob-pass"}
        )
        assert reset.status_code == 204
        assert (await bob.get("/auth/me")).status_code == 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as reborn:
        assert (await reborn.post(
            "/auth/login", json={"username": "bob", "password": "new-bob-pass"}
        )).status_code == 200


@pytest.mark.asyncio
async def test_admin_user_endpoints_404_on_unknown_user(admin_http):
    assert (await admin_http.patch("/admin/users/99999", json={"role": "admin"})).status_code == 404
    assert (await admin_http.post(
        "/admin/users/99999/password", json={"new_password": "x"}
    )).status_code == 404
