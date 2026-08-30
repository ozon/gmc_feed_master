from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.export import ExportRun
from app.models.feed_source import FeedSource
from app.models.ingestion import IngestionRun
from app.models.quality import QualityFinding
from app.models.staging import StagingProduct
from app.staging.purge import IngestionRunPurgeCounts, purge_expired_ingestion_runs

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


class FactoryAdapter:
    def __init__(self, factory):
        self._factory = factory

    def __call__(self):
        return self._factory()


async def _seed(session):
    client = Client(name="Acme")
    session.add(client)
    await session.flush()
    feed_source = FeedSource(client_id=client.id, name="US", source_format="tsv")
    session.add(feed_source)
    await session.flush()
    return feed_source


async def _env(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    return engine, factory, feed_source.id


async def _run(factory, feed_source_id, days_old, status="success"):
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed_source_id, status=status)
            session.add(run)
            await session.flush()
            pk = run.id
        async with session.begin():
            await session.execute(
                text("UPDATE ingestion_runs SET started_at = :t WHERE id = :pk"),
                {"t": NOW - timedelta(days=days_old), "pk": pk},
            )
    return pk


async def _export_run(factory, feed_source_id, ingestion_run_id, status="success"):
    async with factory() as session:
        async with session.begin():
            row = ExportRun(
                feed_source_id=feed_source_id,
                ingestion_run_id=ingestion_run_id,
                status=status,
            )
            session.add(row)
            await session.flush()
            return row.id


async def _finding(factory, feed_source_id, ingestion_run_id, product_id="sku-1"):
    async with factory() as session:
        async with session.begin():
            row = QualityFinding(
                feed_source_id=feed_source_id,
                ingestion_run_id=ingestion_run_id,
                product_id=product_id,
                severity="warning",
                code="missing-field",
                message="field is missing",
            )
            session.add(row)
            await session.flush()
            return row.id


async def _staging_product(factory, feed_source_id, ingestion_run_id, product_id):
    async with factory() as session:
        async with session.begin():
            row = StagingProduct(
                feed_source_id=feed_source_id,
                ingestion_run_id=ingestion_run_id,
                product_id=product_id,
                content_hash="h",
                config_hash="c",
                status="active",
                raw_data={},
            )
            session.add(row)
            await session.flush()
            return row.id


async def _all_ids(factory, model):
    async with factory() as session:
        return set((await session.execute(select(model.id))).scalars().all())


async def test_purges_old_run_without_dependents(isolated_database_url):
    engine, factory, fs_id = await _env(isolated_database_url)
    run_id = await _run(factory, fs_id, days_old=91)

    counts = await purge_expired_ingestion_runs(FactoryAdapter(factory), NOW)

    assert counts == IngestionRunPurgeCounts(
        runs_purged=1, export_runs_detached=0, findings_deleted=0
    )
    assert await _all_ids(factory, IngestionRun) == set()
    await engine.dispose()


async def test_keeps_recent_run(isolated_database_url):
    engine, factory, fs_id = await _env(isolated_database_url)
    run_id = await _run(factory, fs_id, days_old=10)

    counts = await purge_expired_ingestion_runs(FactoryAdapter(factory), NOW)

    assert counts == IngestionRunPurgeCounts(
        runs_purged=0, export_runs_detached=0, findings_deleted=0
    )
    assert await _all_ids(factory, IngestionRun) == {run_id}
    await engine.dispose()


async def test_detaches_export_run_and_purges_old_run(isolated_database_url):
    engine, factory, fs_id = await _env(isolated_database_url)
    run_id = await _run(factory, fs_id, days_old=91)
    export_run_id = await _export_run(factory, fs_id, run_id)

    counts = await purge_expired_ingestion_runs(FactoryAdapter(factory), NOW)

    assert counts == IngestionRunPurgeCounts(
        runs_purged=1, export_runs_detached=1, findings_deleted=0
    )
    async with factory() as session:
        exports = list((await session.execute(select(ExportRun))).scalars())
    assert [row.id for row in exports] == [export_run_id]
    assert exports[0].ingestion_run_id is None
    await engine.dispose()


async def test_keeps_run_referenced_by_staging_product(isolated_database_url):
    engine, factory, fs_id = await _env(isolated_database_url)
    run_id = await _run(factory, fs_id, days_old=91)
    await _staging_product(factory, fs_id, run_id, "sku-1")
    export_run_id = await _export_run(factory, fs_id, run_id)
    finding_id = await _finding(factory, fs_id, run_id)

    counts = await purge_expired_ingestion_runs(FactoryAdapter(factory), NOW)

    assert counts == IngestionRunPurgeCounts(
        runs_purged=0, export_runs_detached=0, findings_deleted=0
    )
    assert await _all_ids(factory, IngestionRun) == {run_id}
    async with factory() as session:
        exports = list((await session.execute(select(ExportRun))).scalars())
    assert [row.id for row in exports] == [export_run_id]
    assert exports[0].ingestion_run_id == run_id
    assert await _all_ids(factory, QualityFinding) == {finding_id}
    await engine.dispose()


async def test_deletes_findings_of_purged_run(isolated_database_url):
    engine, factory, fs_id = await _env(isolated_database_url)
    run_id = await _run(factory, fs_id, days_old=91)
    finding_id = await _finding(factory, fs_id, run_id)

    counts = await purge_expired_ingestion_runs(FactoryAdapter(factory), NOW)

    assert counts == IngestionRunPurgeCounts(
        runs_purged=1, export_runs_detached=0, findings_deleted=1
    )
    assert await _all_ids(factory, QualityFinding) == set()
    assert await _all_ids(factory, IngestionRun) == set()
    await engine.dispose()


async def test_rollback_export_run_is_untouched(isolated_database_url):
    engine, factory, fs_id = await _env(isolated_database_url)
    await _run(factory, fs_id, days_old=91)
    rollback_id = await _export_run(factory, fs_id, None)

    counts = await purge_expired_ingestion_runs(FactoryAdapter(factory), NOW)

    assert counts == IngestionRunPurgeCounts(
        runs_purged=1, export_runs_detached=0, findings_deleted=0
    )
    async with factory() as session:
        exports = list((await session.execute(select(ExportRun))).scalars())
    assert [row.id for row in exports] == [rollback_id]
    assert exports[0].ingestion_run_id is None
    await engine.dispose()


async def test_purge_on_empty_tables_is_zero(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    counts = await purge_expired_ingestion_runs(FactoryAdapter(factory), NOW)

    assert counts == IngestionRunPurgeCounts(
        runs_purged=0, export_runs_detached=0, findings_deleted=0
    )
    await engine.dispose()
