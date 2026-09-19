from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
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
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver/api")
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

    admin_client = await _login(app, "operator", "admin-pass")
    # Login is itself audited; reset so the page contains exactly the seeded rows.
    async with factory() as session, session.begin():
        await session.execute(delete(EventLog))
        for i in range(3):
            await record_event(
                session, category="audit", level="info", source="backend", message=f"m{i}"
            )
    first = (await admin_client.get("/logs/entries?limit=2")).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await admin_client.get(f"/logs/entries?limit=2&cursor={first['next_cursor']}")
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    await admin_client.aclose()


async def test_client_logs_redact_sensitive_context_and_strip_url_query(settings_app):
    app, factory = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    ingest = await user_client.post(
        "/logs/client",
        json={
            "entries": [
                {
                    "level": "error",
                    "message": "boom",
                    "url": "/orders?token=super-secret",
                    "context": {"password": "hunter2", "keep": "ok"},
                }
            ]
        },
    )
    assert ingest.status_code == 204
    await user_client.aclose()

    async with factory() as session, session.begin():
        row = (
            await session.execute(select(EventLog).where(EventLog.message == "boom"))
        ).scalar_one()
    assert row.context["password"] == "[REDACTED]"
    assert row.context["keep"] == "ok"
    assert row.context["url"] == "/orders"


async def test_client_logs_reject_oversize_context(settings_app):
    app, _ = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    response = await user_client.post(
        "/logs/client",
        json={
            "entries": [
                {"level": "error", "message": "big", "context": {"blob": "x" * 8100}}
            ]
        },
    )
    assert response.status_code == 422
    await user_client.aclose()


async def test_client_logs_reject_oversize_body(settings_app):
    app, _ = settings_app
    user_client = await _login(app, "viewer", "user-pass")
    entries = [
        {"level": "error", "message": f"m{i}", "context": {"blob": "x" * 7000}}
        for i in range(5)
    ]
    response = await user_client.post("/logs/client", json={"entries": entries})
    assert response.status_code == 413
    await user_client.aclose()


async def test_entries_from_to_filter(settings_app):
    app, factory = settings_app
    async with factory() as session, session.begin():
        session.add_all(
            [
                EventLog(
                    category="audit",
                    level="info",
                    source="backend",
                    message="old",
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                ),
                EventLog(
                    category="audit",
                    level="info",
                    source="backend",
                    message="in-range",
                    created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                ),
                EventLog(
                    category="audit",
                    level="info",
                    source="backend",
                    message="future",
                    created_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
                ),
            ]
        )
    admin_client = await _login(app, "operator", "admin-pass")
    listing = await admin_client.get(
        "/logs/entries?from=2026-05-01T00:00:00Z&to=2026-07-01T00:00:00Z"
    )
    assert listing.status_code == 200
    messages = [item["message"] for item in listing.json()["items"]]
    assert messages == ["in-range"]
    await admin_client.aclose()


async def test_entries_q_escapes_like_wildcards(settings_app):
    app, factory = settings_app
    async with factory() as session, session.begin():
        session.add_all(
            [
                EventLog(category="audit", level="info", source="backend", message="50% off"),
                EventLog(category="audit", level="info", source="backend", message="plain"),
            ]
        )
    admin_client = await _login(app, "operator", "admin-pass")
    listing = await admin_client.get("/logs/entries?q=%25")
    assert listing.status_code == 200
    messages = [item["message"] for item in listing.json()["items"]]
    assert messages == ["50% off"]
    await admin_client.aclose()


async def test_client_logs_rate_limit_exceeded(settings_app):
    app, _ = settings_app
    from app.routes.logs import _CLIENT_LOG_MAX_PER_WINDOW

    admin_client = await _login(app, "operator", "admin-pass")
    body = {"entries": [{"level": "error", "message": "spam"}]}
    last = None
    for _ in range(_CLIENT_LOG_MAX_PER_WINDOW + 1):
        last = await admin_client.post("/logs/client", json=body)
    assert last is not None and last.status_code == 429
    await admin_client.aclose()


async def test_unhandled_exception_persisted_as_server_error(settings_app):
    app, factory = settings_app

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver/api")
    with pytest.raises(RuntimeError, match="kaboom"):
        await client.get("https://testserver/boom", headers={"X-Request-ID": "srv-err-req-1"})
    await client.aclose()

    async with factory() as session:
        row = (
            await session.execute(
                select(EventLog).where(EventLog.category == "server_error")
            )
        ).scalar_one()
    assert row.message == "kaboom"
    assert row.request_id == "srv-err-req-1"
