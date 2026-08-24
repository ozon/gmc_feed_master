import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.main import create_app
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


@pytest_asyncio.fixture
async def postgres_app():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL via asyncpg")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the asyncpg driver")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "old")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="old",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
    await engine.dispose()


async def client_factory(postgres_app):
    app, _ = postgres_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    return client


@pytest.mark.asyncio
async def test_password_change_revokes_every_session(postgres_app):
    first = await client_factory(postgres_app)
    second = await client_factory(postgres_app)
    assert (await first.post("/auth/login", json={"username": "operator", "password": "old"})).status_code == 200
    assert (await second.post("/auth/login", json={"username": "operator", "password": "old"})).status_code == 200
    response = await first.post(
        "/auth/password", json={"current_password": "old", "new_password": "new"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert (await first.get("/auth/me")).status_code == 401
    assert (await second.get("/auth/me")).status_code == 401
    old_client = await client_factory(postgres_app)
    assert (await old_client.post(
        "/auth/login", json={"username": "operator", "password": "old"}
    )).status_code == 401
    fresh = await client_factory(postgres_app)
    assert (await fresh.post(
        "/auth/login", json={"username": "operator", "password": "new"}
    )).status_code == 200
    await first.aclose()
    await second.aclose()
    await old_client.aclose()
    await fresh.aclose()


@pytest.mark.asyncio
async def test_password_change_rejects_wrong_current_and_empty_new(postgres_app):
    client = await client_factory(postgres_app)
    assert (await client.post("/auth/login", json={"username": "operator", "password": "old"})).status_code == 200
    wrong = await client.post(
        "/auth/password", json={"current_password": "wrong", "new_password": "new"}
    )
    empty = await client.post(
        "/auth/password", json={"current_password": "old", "new_password": ""}
    )
    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "Invalid credentials"}
    assert empty.status_code == 422
    await client.aclose()
