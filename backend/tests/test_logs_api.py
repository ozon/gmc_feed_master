import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.event_log import EventLog
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(EventLog))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
        async with session.begin():
            session.add(
                User(
                    username="viewer",
                    password_hash=hash_password("user-pass"),
                    role="user",
                )
            )
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


async def _login(app, username, password):
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    response = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return client


async def test_get_entries_requires_admin(settings_app):
    app, _ = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    response = await user_client.get("/logs/entries")
    assert response.status_code == 403
    await user_client.aclose()


async def test_client_logs_ingested_and_listed(settings_app):
    app, _ = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    ingest = await user_client.post(
        "/logs/client",
        json={
            "entries": [
                {
                    "level": "error",
                    "message": "render failed",
                    "route": "/logs",
                    "request_id": "req-77",
                    "context": {"component": "SystemLogsPage"},
                }
            ]
        },
    )
    assert ingest.status_code == 204
    await user_client.aclose()

    admin_client = await _login(app, "operator", "admin-pass")
    listing = await admin_client.get("/logs/entries?category=client_error")
    assert listing.status_code == 200
    body = listing.json()
    assert body["next_cursor"] is None
    assert body["items"][0]["message"] == "render failed"
    assert body["items"][0]["request_id"] == "req-77"
    assert body["items"][0]["source"] == "frontend"
    await admin_client.aclose()


async def test_client_logs_reject_empty_batch(settings_app):
    app, _ = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    response = await user_client.post("/logs/client", json={"entries": []})
    assert response.status_code == 422
    await user_client.aclose()


async def test_entries_pagination_cursor(settings_app):
    app, factory = settings_app
    from app.event_log import record_event

    async with factory() as session, session.begin():
        for i in range(3):
            await record_event(
                session, category="audit", level="info", source="backend", message=f"m{i}"
            )
    admin_client = await _login(app, "operator", "admin-pass")
    first = (await admin_client.get("/logs/entries?limit=2")).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await admin_client.get(f"/logs/entries?limit=2&cursor={first['next_cursor']}")
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    await admin_client.aclose()
