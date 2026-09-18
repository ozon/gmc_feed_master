import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.export.store import ExportFileStore
from app.models import Client, ExportRun, FeedSource, IngestionRun
from app.models.event_log import EventLog
from app.models.staging import StagingProduct
from app.pipeline import ExportStep, RunState, StepContext
from registry.loader import load_registry

pytestmark = pytest.mark.asyncio

REGISTRY = load_registry()
PRODUCTS = [{"id": "SKU-1", "title": "Red Shirt", "price": "10 USD"}]


@pytest_asyncio.fixture
async def env(isolated_database_url, tmp_path):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        client = Client(name="Acme")
        session.add(client)
        await session.flush()
        feed_source = FeedSource(
            client_id=client.id,
            name="Main",
            source_format="tsv",
            export_token="tok-publish-audit",
            history_retention_count=2,
        )
        session.add(feed_source)
        await session.flush()
        run = IngestionRun(feed_source_id=feed_source.id, status="running")
        session.add(run)
        await session.flush()
        session.add(
            ExportRun(
                feed_source_id=feed_source.id,
                ingestion_run_id=run.id,
                status="pending_export",
                product_count=len(PRODUCTS),
            )
        )
        for product in PRODUCTS:
            session.add(
                StagingProduct(
                    feed_source_id=feed_source.id,
                    ingestion_run_id=run.id,
                    product_id=product["id"],
                    content_hash="a" * 64,
                    config_hash="b" * 64,
                    status="active",
                    raw_data=product,
                )
            )
        feed_source_id, run_id, client_id = feed_source.id, run.id, client.id

    step = ExportStep(
        REGISTRY,
        ExportFileStore(tmp_path / "exports"),
        TestClock(datetime(2026, 8, 27, tzinfo=timezone.utc)),
        "http://test.public",
    )
    yield {
        "factory": factory,
        "feed_source_id": feed_source_id,
        "run_id": run_id,
        "client_id": client_id,
        "step": step,
    }
    await engine.dispose()


async def test_successful_export_writes_publish_audit_row(env):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        run_id=env["run_id"],
        feed_source_id=env["feed_source_id"],
        client_id=env["client_id"],
    )
    try:
        ctx = StepContext(
            feed_source_id=env["feed_source_id"],
            session_factory=env["factory"],
            logger=logging.getLogger("test"),
            run_state=RunState(),
            ingestion_run_id=env["run_id"],
            trigger="manual",
        )
        result = await env["step"].execute(ctx)
    finally:
        structlog.contextvars.clear_contextvars()

    assert result.statistics["export"]["products"] == 1

    async with env["factory"]() as session:
        row = (
            await session.execute(
                select(EventLog).where(EventLog.message == "export.publish")
            )
        ).scalar_one()
    assert row.category == "audit"
    assert row.feed_source_id == env["feed_source_id"]
    assert row.client_id == env["client_id"]
    assert row.run_id == env["run_id"]
    assert row.context["target_type"] == "feed_source"
    assert row.context["target_id"] == str(env["feed_source_id"])
    assert row.context["products"] == 1
    assert row.context["version"] == 1
    assert row.context["deduplicated"] is False


async def test_audit_failure_does_not_fail_export(env, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr("app.pipeline.steps.audit", boom)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        run_id=env["run_id"],
        feed_source_id=env["feed_source_id"],
        client_id=env["client_id"],
    )
    try:
        ctx = StepContext(
            feed_source_id=env["feed_source_id"],
            session_factory=env["factory"],
            logger=logging.getLogger("test"),
            run_state=RunState(),
            ingestion_run_id=env["run_id"],
            trigger="manual",
        )
        result = await env["step"].execute(ctx)
    finally:
        structlog.contextvars.clear_contextvars()

    assert result.statistics["export"]["products"] == 1

    async with env["factory"]() as session:
        rows = (
            await session.execute(
                select(EventLog).where(EventLog.message == "export.publish")
            )
        ).scalars().all()
    assert rows == []


async def test_dry_run_does_not_write_publish_audit(env):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        run_id=env["run_id"],
        feed_source_id=env["feed_source_id"],
        client_id=env["client_id"],
    )
    try:
        ctx = StepContext(
            feed_source_id=env["feed_source_id"],
            session_factory=env["factory"],
            logger=logging.getLogger("test"),
            run_state=RunState(),
            ingestion_run_id=env["run_id"],
            trigger="manual",
            dry_run=True,
        )
        result = await env["step"].execute(ctx)
    finally:
        structlog.contextvars.clear_contextvars()

    assert result.statistics["export"]["products"] == 1

    async with env["factory"]() as session:
        rows = (
            await session.execute(
                select(EventLog).where(EventLog.message == "export.publish")
            )
        ).scalars().all()
    assert rows == []
