import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


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


async def _seed_feed_source(app_factory) -> tuple[int, int]:
    """Create a client and feed source, return (client_id, feed_source_id)."""
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    fs_id = (
        await client.post(
            f"/clients/{client_id}/feed-sources",
            json={"name": "Main", "source_format": "xml"},
        )
    ).json()["id"]
    return client, fs_id


async def test_trigger_unknown_feed_source_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.post("/feed-sources/999999/run")
    assert resp.status_code == 404


async def test_trigger_returns_202_with_run_id(app_factory):
    client, fs_id = await _seed_feed_source(app_factory)
    resp = await client.post(f"/feed-sources/{fs_id}/run")
    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body
    run_id = body["run_id"]
    assert isinstance(run_id, int)

    app, factory = app_factory
    for _ in range(50):
        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
            if run and run.status in ("success", "error", "skipped"):
                break
        await asyncio.sleep(0.1)
    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
    assert run is not None
    assert run.status == "success"
    assert run.processed_count == 0
    assert run.failed_count == 0


async def test_trigger_while_lock_held_ends_skipped(app_factory):
    app, factory = app_factory
    client, fs_id = await _seed_feed_source(app_factory)
    lock = app.state.lock_registry.get(fs_id)
    await lock.acquire()
    try:
        resp = await client.post(f"/feed-sources/{fs_id}/run")
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]
        for _ in range(50):
            async with factory() as session:
                run = await session.get(IngestionRun, run_id)
                if run and run.status in ("success", "error", "skipped"):
                    break
            await asyncio.sleep(0.1)
        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
        assert run.status == "skipped"
    finally:
        lock.release()


async def test_history_returns_ordered_results(app_factory):
    app, factory = app_factory
    client, fs_id = await _seed_feed_source(app_factory)

    r1 = await client.post(f"/feed-sources/{fs_id}/run")
    r2 = await client.post(f"/feed-sources/{fs_id}/run")
    await asyncio.sleep(0.2)

    resp = await client.get(f"/feed-sources/{fs_id}/ingestion-runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 2
    ids = [r["id"] for r in runs]
    assert ids[0] > ids[1]
    for r in runs:
        assert "id" in r
        assert "status" in r
        assert "started_at" in r
        assert "completed_at" in r
        assert "processed_count" in r
        assert "failed_count" in r
        assert "error_message" in r
        assert "statistics" in r


async def test_history_pagination(app_factory):
    app, factory = app_factory
    client, fs_id = await _seed_feed_source(app_factory)

    for _ in range(3):
        await client.post(f"/feed-sources/{fs_id}/run")
    await asyncio.sleep(0.3)

    resp = await client.get(f"/feed-sources/{fs_id}/ingestion-runs?limit=2&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp = await client.get(f"/feed-sources/{fs_id}/ingestion-runs?limit=2&offset=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_history_unknown_feed_source_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/feed-sources/999999/ingestion-runs")
    assert resp.status_code == 404


async def test_trigger_unauthenticated_returns_401(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post("/feed-sources/1/run")).status_code == 401
    assert (await client.get("/feed-sources/1/ingestion-runs")).status_code == 401
