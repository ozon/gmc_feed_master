import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, FeedSource, IngestionRun
from app.models.pipeline import ModuleInstance, ModulePipeline
from app.models.plugin import Plugin
from app.models.session import Session
from app.models.staging import StagingHistory, StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.staging.purge import purge_expired


pytestmark = pytest.mark.asyncio

TWO_PRODUCTS_TSV = (
    b"sku\ttitle\tean\tmargin\n"
    b"A1\tRed Shirt\t1234567890123\t10\n"
    b"A2\tBlue Hat\t9876543210987\t20\n"
)
ONE_PRODUCT_TSV = (
    b"sku\ttitle\tean\tmargin\n"
    b"A1\tRed Shirt\t1234567890123\t10\n"
)
CHANGED_TITLE_TSV = (
    b"sku\ttitle\tean\tmargin\n"
    b"A1\tRed Shirt\t1234567890123\t10\n"
    b"A2\tGreen Scarf\t9876543210987\t20\n"
)
INVALID_ID_TSV = (
    b"sku\ttitle\tean\n"
    b"\tNo Identifier\t1112223334445\n"
    b"A1\tRed Shirt\t1234567890123\n"
)


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data

    async def fetch(self, url, basic_auth=None, _client=None):
        return self.data


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
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
    )
    fetcher = StubFetcher(TWO_PRODUCTS_TSV)
    app = create_app(settings=settings, db_session_factory=factory, fetcher=cast(Any, fetcher))
    yield app, factory, fetcher
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _create_feed_source(client):
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={
            "name": "Main feed",
            "source_format": "tsv",
            "source_url": "http://test.local/feed.tsv",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _trigger_run(factory, client, feed_source_id):
    resp = await client.post(f"/feed-sources/{feed_source_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    run = None
    for _ in range(200):
        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
            if run is not None and run.status in ("success", "error"):
                break
        await asyncio.sleep(0.05)
    assert run is not None and run.status == "success", (
        f"run ended in {(run.status if run else 'unknown')}: "
        f"{getattr(run, 'error_message', None)}"
    )
    return run_id


async def _latest_run_via_api(client, feed_source_id):
    resp = await client.get(f"/feed-sources/{feed_source_id}/ingestion-runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert runs
    return runs[0]


def _staging_stats(run_payload):
    return run_payload["statistics"]["staging"]


async def _staging_rows(factory, feed_source_id):
    async with factory() as session:
        result = await session.execute(
            select(StagingProduct).where(
                StagingProduct.feed_source_id == feed_source_id
            )
        )
        return {row.product_id: row for row in result.scalars()}


async def _history_count(factory, feed_source_id):
    async with factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(StagingHistory)
            .join(
                StagingProduct,
                StagingHistory.staging_product_id == StagingProduct.id,
            )
            .where(StagingProduct.feed_source_id == feed_source_id)
        )
        return result.scalar_one()


async def test_first_run_stages_everything(app_factory):
    _, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await _create_feed_source(client)

    await _trigger_run(factory, client, fs_id)

    latest = await _latest_run_via_api(client, fs_id)
    stats = _staging_stats(latest)
    assert stats["new"] == 2
    assert stats["changed"] == 0
    assert stats["unchanged"] == 0
    assert stats["removed"] == 0
    assert stats["reactivated"] == 0

    rows = await _staging_rows(factory, fs_id)
    assert set(rows) == {"A1", "A2"}
    assert all(row.status == "active" for row in rows.values())


async def test_identical_second_run_enqueues_nothing(app_factory):
    _, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await _create_feed_source(client)

    await _trigger_run(factory, client, fs_id)
    await _trigger_run(factory, client, fs_id)

    latest = await _latest_run_via_api(client, fs_id)
    stats = _staging_stats(latest)
    assert stats["new"] == 0
    assert stats["changed"] == 0
    assert stats["unchanged"] == 2

    rows = await _staging_rows(factory, fs_id)
    assert len(rows) == 2
    assert await _history_count(factory, fs_id) == 2


async def test_content_change_reprocesses_with_history(app_factory):
    _, factory, fetcher = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await _create_feed_source(client)

    await _trigger_run(factory, client, fs_id)
    fetcher.data = CHANGED_TITLE_TSV
    await _trigger_run(factory, client, fs_id)

    latest = await _latest_run_via_api(client, fs_id)
    stats = _staging_stats(latest)
    assert stats["changed"] == 1
    assert stats["unchanged"] == 1

    assert await _history_count(factory, fs_id) == 3
    rows = await _staging_rows(factory, fs_id)
    assert rows["A2"].raw_data["title"] == "Green Scarf"


async def test_config_change_reprocesses_without_history(app_factory):
    _, factory, fetcher = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await _create_feed_source(client)

    async with factory() as session:
        async with session.begin():
            feed_source = await session.get(FeedSource, fs_id)
            plugin = Plugin(
                name="labelizer",
                version="1.0.0",
                manifest={"id": "labelizer"},
            )
            session.add(plugin)
            await session.flush()
            pipeline = ModulePipeline(
                feed_source_id=fs_id,
                name="pipe",
                version="1",
                definition={},
            )
            session.add(pipeline)
            await session.flush()
            feed_source.active_pipeline_id = pipeline.id
            instance = ModuleInstance(
                pipeline_id=pipeline.id,
                plugin_id=plugin.id,
                position=0,
                name="lbl",
                configuration={"slot": "custom_label_0"},
            )
            session.add(instance)
            await session.flush()
            instance_id = instance.id

    await _trigger_run(factory, client, fs_id)
    fetcher.data = CHANGED_TITLE_TSV
    await _trigger_run(factory, client, fs_id)
    assert await _history_count(factory, fs_id) == 3

    async with factory() as session:
        async with session.begin():
            instance = await session.get(ModuleInstance, instance_id)
            instance.configuration = {"slot": "custom_label_9"}

    await _trigger_run(factory, client, fs_id)

    latest = await _latest_run_via_api(client, fs_id)
    stats = _staging_stats(latest)
    assert stats["changed"] == 2
    assert stats["unchanged"] == 0
    assert await _history_count(factory, fs_id) == 3


async def test_removed_product_flips_status_and_returns(app_factory):
    _, factory, fetcher = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await _create_feed_source(client)

    await _trigger_run(factory, client, fs_id)

    fetcher.data = ONE_PRODUCT_TSV
    await _trigger_run(factory, client, fs_id)
    latest = await _latest_run_via_api(client, fs_id)
    stats = _staging_stats(latest)
    assert stats["removed"] == 1
    assert stats["unchanged"] == 1

    rows = await _staging_rows(factory, fs_id)
    assert rows["A2"].status == "removed"
    assert rows["A2"].removed_at is not None
    assert rows["A1"].status == "active"

    fetcher.data = TWO_PRODUCTS_TSV
    await _trigger_run(factory, client, fs_id)
    latest = await _latest_run_via_api(client, fs_id)
    stats = _staging_stats(latest)
    assert stats["reactivated"] == 1
    assert stats["unchanged"] == 1

    rows = await _staging_rows(factory, fs_id)
    assert rows["A2"].status == "active"
    assert rows["A2"].removed_at is None
    assert await _history_count(factory, fs_id) == 2


async def test_purge_clears_expired_rows_end_to_end(app_factory):
    _, factory, fetcher = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await _create_feed_source(client)

    await _trigger_run(factory, client, fs_id)
    fetcher.data = ONE_PRODUCT_TSV
    await _trigger_run(factory, client, fs_id)

    rows = await _staging_rows(factory, fs_id)
    assert rows["A2"].status == "removed"

    cutoff = datetime.now(timezone.utc) - timedelta(days=91)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "UPDATE staging_products SET removed_at = :cutoff "
                    "WHERE feed_source_id = :fid AND product_id = 'A2'"
                ),
                {"cutoff": cutoff, "fid": fs_id},
            )

    counts = await purge_expired(factory, datetime.now(timezone.utc))

    assert counts.removed_products == 1
    rows = await _staging_rows(factory, fs_id)
    assert set(rows) == {"A1"}
    assert await _history_count(factory, fs_id) == 1


async def test_invalid_ids_do_not_block_run(app_factory):
    _, factory, fetcher = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await _create_feed_source(client)

    fetcher.data = INVALID_ID_TSV
    run_id = await _trigger_run(factory, client, fs_id)

    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
    assert run.status == "success"
    assert run.failed_count >= 1

    latest = await _latest_run_via_api(client, fs_id)
    stats = _staging_stats(latest)
    assert stats["failed"] >= 1
    assert stats["new"] == 1

    rows = await _staging_rows(factory, fs_id)
    assert set(rows) == {"A1"}


async def test_migration_head_matches_models(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)

    def _inspect(connection):
        inspector = inspect(connection)
        columns = {c["name"] for c in inspector.get_columns("staging_products")}
        fks = inspector.get_foreign_keys("staging_history")
        return columns, fks

    try:
        async with engine.connect() as connection:
            columns, fks = await connection.run_sync(_inspect)
    finally:
        await engine.dispose()

    assert "removed_at" in columns
    history_fk = [
        fk
        for fk in fks
        if fk["constrained_columns"] == ["staging_product_id"]
    ]
    assert history_fk
    ondelete = history_fk[0].get("ondelete") or (
        history_fk[0].get("options") or {}
    ).get("ondelete")
    assert ondelete == "CASCADE"
