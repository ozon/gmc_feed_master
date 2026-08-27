import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


class StubFetcher:
    async def fetch(self, url, basic_auth=None, _client=None):
        return b"<rss><channel></channel></rss>"


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
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
        export_dir=str(tmp_path / "exports"),
    )
    app = create_app(settings=settings, db_session_factory=factory, fetcher=StubFetcher())
    yield app, factory
    await engine.dispose()


async def _logged_in_client(app):
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_feed_source(client):
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={
            "name": "Main",
            "source_format": "xml",
            "source_url": "https://example.com/feed.xml",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_manual_run_task_is_tracked_until_done(app_factory):
    app, factory = app_factory
    client = await _logged_in_client(app)
    fs_id = await _seed_feed_source(client)

    started = asyncio.Event()
    release = asyncio.Event()
    real_execute = app.state.pipeline_runner.execute

    async def gated_execute(feed_source_id, run_id=None):
        started.set()
        await release.wait()
        return await real_execute(feed_source_id, run_id=run_id)

    app.state.pipeline_runner.execute = gated_execute

    resp = await client.post(f"/feed-sources/{fs_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    await started.wait()
    assert len(app.state.background_tasks) == 1

    release.set()
    for _ in range(200):
        if not app.state.background_tasks:
            break
        await asyncio.sleep(0.05)
    assert app.state.background_tasks == set()

    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
    assert run.status == "success"
