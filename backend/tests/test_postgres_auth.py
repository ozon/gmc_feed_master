import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.clock import TestClock


@pytest_asyncio.fixture
async def postgres_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
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


@pytest.mark.asyncio
async def test_persisted_logout_clears_cookie_and_invalidates_session(postgres_app):
    client = await client_factory(postgres_app)
    assert (await client.post("/auth/login", json={"username": "operator", "password": "old"})).status_code == 200

    response = await client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    cookie = response.headers["set-cookie"].lower()
    assert "gmc_session=" in cookie
    assert "max-age=0" in cookie
    assert "expires=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert (await client.get("/auth/me")).status_code == 401
    await client.aclose()


@pytest.mark.asyncio
async def test_persisted_interaction_renews_idle_expiry(postgres_app):
    app, _ = postgres_app
    clock = TestClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    app.state.clock = clock
    client = await client_factory(postgres_app)
    assert (await client.post("/auth/login", json={"username": "operator", "password": "old"})).status_code == 200

    clock.advance(minutes=29)
    assert (await client.post("/auth/interaction")).status_code == 200
    clock.advance(minutes=29)
    assert (await client.get("/auth/me")).status_code == 200
    await client.aclose()


@pytest.mark.asyncio
async def test_startup_seeds_once_and_session_survives_new_app_instance(
    isolated_database_url,
):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="first-password",
        database_url=isolated_database_url,
    )
    first_app = create_app(settings=settings, db_session_factory=factory)
    async with first_app.router.lifespan_context(first_app):
        first = AsyncClient(transport=ASGITransport(app=first_app), base_url="https://testserver")
        assert (await first.post("/auth/login", json={"username": "operator", "password": "first-password"})).status_code == 200
        token = first.cookies["gmc_session"]
        await first.aclose()

    second_settings = settings.model_copy(update={"initial_password": "replacement"})
    second_app = create_app(settings=second_settings, db_session_factory=factory)
    async with second_app.router.lifespan_context(second_app):
        second = AsyncClient(transport=ASGITransport(app=second_app), base_url="https://testserver")
        second.cookies.set("gmc_session", token)
        assert (await second.get("/auth/me")).status_code == 200
        assert (await second.post("/auth/login", json={"username": "operator", "password": "replacement"})).status_code == 401
        assert (await second.post("/auth/login", json={"username": "operator", "password": "first-password"})).status_code == 200
        await second.aclose()
    await engine.dispose()
