import logging
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.pipeline.scheduler import job_id


pytestmark = pytest.mark.asyncio

WIDE_TSV = (
    "id\ttitle\tdescription\tlink\timage_link\tavailability\tprice\tcondition\tbrand\tgtin\tshipping(country:price)\tshipping(country:price)\n"
    "SKU-1\tRed Shirt\tA red shirt\thttp://shop.example/1\thttp://shop.example/1.jpg\tin_stock\t10.00 USD\tnew\tAcme\t0012345678905\tUS:6.49 USD\tUK:5.99 GBP\n"
    "SKU-2\tBlue Hat\tA blue hat\thttp://shop.example/2\thttp://shop.example/2.jpg\tin_stock\t5.00 USD\tnew\tAcme\t0012345678912\tUS:6.49 USD\n"
).encode("utf-8")


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data

    async def fetch(self, url, basic_auth=None, _client=None):
        return self.data


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
        public_base_url="http://test.public",
    )
    app = create_app(settings=settings, db_session_factory=factory, fetcher=StubFetcher(WIDE_TSV))
    yield app, factory, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _create_feed_source(app_factory, cron_expression=None):
    client = await logged_in_client(app_factory)
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    payload = {
        "name": "Main",
        "source_format": "wide_tsv",
        "currency": "USD",
        "source_url": "http://shop.example/feed.tsv",
    }
    if cron_expression is not None:
        payload["cron_expression"] = cron_expression
    resp = await client.post(f"/clients/{client_id}/feed-sources", json=payload)
    assert resp.status_code == 201
    return resp.json()


async def test_scheduled_entry_point_drives_full_pipeline(app_factory):
    app, factory, settings = app_factory
    feed_source = await _create_feed_source(app_factory, cron_expression="0 * * * *")
    fs_id = feed_source["id"]

    run_id = await app.state.pipeline_runner.execute(fs_id)

    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
        staged = list(
            (
                await session.execute(
                    select(StagingProduct).where(StagingProduct.feed_source_id == fs_id)
                )
            ).scalars()
        )
        versions = list(
            (
                await session.execute(
                    select(ExportVersion).where(ExportVersion.feed_source_id == fs_id)
                )
            ).scalars()
        )
        export_runs = list(
            (
                await session.execute(
                    select(ExportRun).where(ExportRun.feed_source_id == fs_id)
                )
            ).scalars()
        )
    assert run.status == "success"
    assert run.error_message is None
    assert len(staged) == 2
    assert len(versions) == 1
    assert versions[0].product_count == 2
    assert len(export_runs) == 1
    assert export_runs[0].status == "completed"
    published = Path(settings.export_dir) / "published" / f"{fs_id}.xml"
    assert published.is_file()
    body = published.read_bytes()
    assert b"<g:id>SKU-1</g:id>" in body
    assert b"<g:id>SKU-2</g:id>" in body


async def test_scheduled_overlap_is_skipped_and_logged(app_factory, caplog):
    app, factory, _ = app_factory
    feed_source = await _create_feed_source(app_factory, cron_expression="0 * * * *")
    fs_id = feed_source["id"]

    lock = app.state.lock_registry.get(fs_id)
    await lock.acquire()
    try:
        job = app.state.scheduler_service._scheduler.get_job(job_id(fs_id))
        assert job is not None
        assert job.max_instances == 2
        with caplog.at_level(logging.WARNING, logger="app.pipeline.runner"):
            run_id = await job.func(*job.args)
    finally:
        lock.release()

    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
    assert run.status == "skipped"
    assert run.statistics == {"reason": "previous run still active"}
    assert run.error_message is None
    assert any("previous run still active" in message for message in caplog.messages)
