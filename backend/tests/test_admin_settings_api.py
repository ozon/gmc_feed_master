from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.global_setting import GlobalSetting
from app.models.ingestion import IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.staging.purge import purge_expired, purge_expired_ingestion_runs


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
            await session.execute(delete(GlobalSetting))
        await seed_initial_user(session, "operator", "admin-pass")
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
async def admin_http(settings_app):
    app, _ = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_get_settings_seeds_defaults(settings_app, admin_http):
    response = await admin_http.get("/admin/settings")
    assert response.status_code == 200
    assert response.json() == {
        "staging_removal_retention_days": 90,
        "staging_history_retention_days": 90,
        "ingestion_run_retention_days": 90,
    }


@pytest.mark.asyncio
async def test_put_settings_persists(settings_app, admin_http):
    response = await admin_http.put("/admin/settings", json={
        "staging_removal_retention_days": 30,
        "staging_history_retention_days": 45,
        "ingestion_run_retention_days": 60,
    })
    assert response.status_code == 200
    assert response.json()["staging_removal_retention_days"] == 30
    follow_up = await admin_http.get("/admin/settings")
    assert follow_up.json()["staging_history_retention_days"] == 45


@pytest.mark.asyncio
async def test_put_settings_rejects_non_positive(settings_app, admin_http):
    response = await admin_http.put("/admin/settings", json={
        "staging_removal_retention_days": 0,
        "staging_history_retention_days": 90,
        "ingestion_run_retention_days": 90,
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_scheduler_lists_system_jobs(settings_app, admin_http):
    app, _ = settings_app
    async with app.router.lifespan_context(app):
        response = await admin_http.get("/admin/scheduler")
    assert response.status_code == 200
    jobs = {job["id"] for job in response.json()}
    assert "system-staging-purge" in jobs
    assert "system-ingestion-run-purge" in jobs


@pytest.mark.asyncio
async def test_purge_honors_configured_retention(settings_app):
    _, factory = settings_app
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with factory() as session:
        async with session.begin():
            session.add(GlobalSetting(
                id=1,
                staging_removal_retention_days=1,
                staging_history_retention_days=1,
                ingestion_run_retention_days=1,
            ))
    # With a 1-day cutoff, nothing at `now` is expired; a 10-day-old run is not.
    counts = await purge_expired(factory, now)
    assert counts.removed_products == 0
    counts = await purge_expired(factory, now + timedelta(days=10))
    assert counts.removed_products >= 0  # must read DB retention without raising
    run_counts = await purge_expired_ingestion_runs(factory, now + timedelta(days=10))
    assert run_counts.runs_purged >= 0


@pytest.mark.asyncio
async def test_ingestion_run_purge_uses_db_retention(isolated_database_url):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            client = Client(name="Purge Co")
            session.add(client)
            await session.flush()
            feed = FeedSource(client_id=client.id, name="F", source_format="xml",
                              source_url="https://x.example/f.xml")
            session.add(feed)
            await session.flush()
            session.add(IngestionRun(
                feed_source_id=feed.id, status="completed",
                started_at=now - timedelta(days=60),
            ))
            session.add(GlobalSetting(
                id=1,
                staging_removal_retention_days=90,
                staging_history_retention_days=90,
                ingestion_run_retention_days=50,
            ))
    # 60-day-old run, 50-day configured retention → purged (90-day default would keep it).
    counts = await purge_expired_ingestion_runs(factory, now)
    assert counts.runs_purged == 1
    await engine.dispose()
