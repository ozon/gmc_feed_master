import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio

EXPECTED_TABLES = {
    "users",
    "sessions",
    "clients",
    "feed_sources",
    "ingestion_runs",
    "staging_products",
    "staging_history",
    "quality_findings",
    "plugins",
    "plugin_configs",
    "plugin_data",
    "module_pipelines",
    "module_instances",
    "export_runs",
    "export_versions",
}


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
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


async def test_m2_acceptance(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)

    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]

    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Main", "source_format": "xml", "cron_expression": "*/5 * * * *"},
    )
    assert resp.status_code == 201
    fs_id = resp.json()["id"]
    assert app.state.scheduler_service.has_job(fs_id)

    resp = await client.post(f"/feed-sources/{fs_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    for _ in range(100):
        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
            if run and run.status == "success":
                break
        await asyncio.sleep(0.1)
    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
    assert run.status == "success"
    assert run.processed_count == 0
    assert run.completed_at is not None

    resp = await client.get(f"/feed-sources/{fs_id}/ingestion-runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 1
    assert runs[0]["id"] == run_id

    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Bad", "source_format": "xml", "cron_expression": "not-cron"},
    )
    assert resp.status_code == 422

    resp = await client.put(f"/feed-sources/{fs_id}", json={"cron_expression": "30 * * * *"})
    assert resp.status_code == 200
    assert app.state.scheduler_service.has_job(fs_id)

    async with factory() as session:
        async with session.begin():
            await session.execute(delete(IngestionRun).where(IngestionRun.feed_source_id == fs_id))

    resp = await client.delete(f"/feed-sources/{fs_id}")
    assert resp.status_code == 204
    assert not app.state.scheduler_service.has_job(fs_id)

    async with factory() as session:
        result = await session.execute(
            text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
        )
        tables = {row[0] for row in result} - {"alembic_version"}
    assert tables == EXPECTED_TABLES
