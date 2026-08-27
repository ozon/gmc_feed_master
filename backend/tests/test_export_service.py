from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.export.renderer import ChannelMetadata
from app.export.service import ExportOutcome, ExportService, channel_metadata_for, generate_export_token
from app.export.store import ExportFileStore
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from registry.loader import load_registry

pytestmark = pytest.mark.asyncio

REGISTRY = load_registry()
PRODUCTS = [
    {"id": "SKU-1", "title": "Red Shirt", "price": "10 USD"},
    {"id": "SKU-2", "title": "Blue Hat", "price": "5 USD"},
]


@pytest_asyncio.fixture
async def env(isolated_database_url, tmp_path):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = ExportFileStore(tmp_path / "exports")
    clock = TestClock(datetime(2026, 8, 27, tzinfo=timezone.utc))
    service = ExportService(factory, store, clock, "http://test.public")

    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main",
                source_format="tsv",
                export_token="tok-service-test",
                history_retention_count=2,
            )
            session.add(feed_source)
            await session.flush()
            feed_source_id = feed_source.id

    yield {"factory": factory, "store": store, "clock": clock, "service": service, "feed_source_id": feed_source_id}
    await engine.dispose()


async def _start_run(env):
    factory = env["factory"]
    async with factory() as session:
        async with session.begin():
            ingestion_run = IngestionRun(feed_source_id=env["feed_source_id"], status="running")
            session.add(ingestion_run)
            await session.flush()
            session.add(ExportRun(
                feed_source_id=env["feed_source_id"],
                ingestion_run_id=ingestion_run.id,
                status="pending_export",
                product_count=len(PRODUCTS),
            ))
            return ingestion_run.id


async def _versions(factory, feed_source_id):
    async with factory() as session:
        result = await session.execute(
            select(ExportVersion)
            .where(ExportVersion.feed_source_id == feed_source_id)
            .order_by(ExportVersion.version_number)
        )
        return list(result.scalars().all())


async def _export_runs(factory, feed_source_id):
    async with factory() as session:
        result = await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source_id)
        )
        return list(result.scalars().all())


def test_generate_export_token_shape():
    tokens = {generate_export_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(token) == 43 for token in tokens)


def test_channel_metadata_for_uses_config_then_fallbacks():
    class FS:
        name = "Feed name"
        configuration = {}

    meta = channel_metadata_for(FS(), "Client name", "http://base")
    assert meta == ChannelMetadata(title="Feed name", link="http://base", description="Client name")

    FS.configuration = {
        "channel_title": "T", "channel_link": "http://l", "channel_description": "D",
    }
    meta = channel_metadata_for(FS(), "Client name", "http://base")
    assert meta == ChannelMetadata(title="T", link="http://l", description="D")


async def test_first_export_creates_version_publishes_and_wires_run(env):
    run_id = await _start_run(env)
    outcome = await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    assert outcome == ExportOutcome(version_number=1, product_count=2, deduplicated=False)
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert [v.version_number for v in versions] == [1]
    assert versions[0].source == "run"
    assert versions[0].product_count == 2
    assert len(versions[0].file_hash) == 64
    assert env["store"].published_exists(env["feed_source_id"])
    assert env["store"].read_version(env["feed_source_id"], 1) == env["store"].published_path(env["feed_source_id"]).read_bytes()

    runs = await _export_runs(env["factory"], env["feed_source_id"])
    assert runs[0].status == "completed"
    assert runs[0].export_version_id == versions[0].id
    assert runs[0].completed_at == datetime(2026, 8, 27, tzinfo=timezone.utc)


async def test_unchanged_second_export_is_deduplicated(env):
    run_id = await _start_run(env)
    await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    run_id_2 = await _start_run(env)
    outcome = await env["service"].export_for_run(env["feed_source_id"], run_id_2, PRODUCTS, REGISTRY)

    assert outcome.deduplicated is True
    assert outcome.version_number == 1
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert len(versions) == 1
    runs = await _export_runs(env["factory"], env["feed_source_id"])
    second = next(r for r in runs if r.ingestion_run_id == run_id_2)
    assert second.status == "completed"
    assert second.export_version_id == versions[0].id


async def test_changed_content_creates_new_version(env):
    run_id = await _start_run(env)
    await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    run_id_2 = await _start_run(env)
    changed = [dict(PRODUCTS[0], title="Green Scarf"), PRODUCTS[1]]
    outcome = await env["service"].export_for_run(env["feed_source_id"], run_id_2, changed, REGISTRY)

    assert outcome == ExportOutcome(version_number=2, product_count=2, deduplicated=False)
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[0].file_hash != versions[1].file_hash


async def test_dedupe_restores_missing_published_file(env):
    run_id = await _start_run(env)
    await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)
    env["store"].published_path(env["feed_source_id"]).unlink()

    run_id_2 = await _start_run(env)
    outcome = await env["service"].export_for_run(env["feed_source_id"], run_id_2, PRODUCTS, REGISTRY)

    assert outcome.deduplicated is True
    assert env["store"].published_exists(env["feed_source_id"])
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert len(versions) == 1


async def test_retention_prunes_oldest_versions_and_files(env):
    titles = ["t1", "t2", "t3"]
    for index, title in enumerate(titles):
        run_id = await _start_run(env)
        products = [dict(PRODUCTS[0], title=title), PRODUCTS[1]]
        await env["service"].export_for_run(env["feed_source_id"], run_id, products, REGISTRY)

    versions = await _versions(env["factory"], env["feed_source_id"])
    assert [v.version_number for v in versions] == [2, 3]
    assert env["store"].read_version(env["feed_source_id"], 1) is None
    assert env["store"].read_version(env["feed_source_id"], 2) is not None


async def test_render_failure_marks_run_failed(env, monkeypatch):
    run_id = await _start_run(env)

    def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr("app.export.service.render_feed", boom)
    with pytest.raises(ValueError):
        await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    runs = await _export_runs(env["factory"], env["feed_source_id"])
    assert runs[0].status == "failed"
    assert runs[0].completed_at == datetime(2026, 8, 27, tzinfo=timezone.utc)
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert versions == []


async def test_publish_failure_marks_run_failed_and_keeps_version(env, monkeypatch):
    run_id = await _start_run(env)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(env["store"], "publish", boom)
    with pytest.raises(OSError):
        await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    runs = await _export_runs(env["factory"], env["feed_source_id"])
    assert runs[0].status == "failed"
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert [v.version_number for v in versions] == [1]
