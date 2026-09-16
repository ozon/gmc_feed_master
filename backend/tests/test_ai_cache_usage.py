from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.usage import UsageLogWriter, UsageRecord, aggregate_usage
from app.models.ai import AiUsageLog


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_usage_writer_persists_row(session_factory):
    writer = UsageLogWriter(session_factory)
    await writer.write(UsageRecord(
        client_id=7, feed_source_id=None, task_type="policy_check",
        provider_config_id=1, model="gpt-4o-mini", cache_hit=False,
        prompt_tokens=100, completion_tokens=20,
        cost_usd=Decimal("0.000100"), latency_ms=800, error_code=None,
    ))
    async with session_factory() as session:
        rows = list((await session.execute(select(AiUsageLog))).scalars())
        assert len(rows) == 1
        assert rows[0].client_id == 7
        assert rows[0].cost_usd == Decimal("0.000100")


@pytest.mark.asyncio
async def test_usage_writer_never_raises_on_db_error(session_factory):
    async def broken_factory():
        raise RuntimeError("db down")
    writer = UsageLogWriter(broken_factory)  # type: ignore[arg-type]
    await writer.write(UsageRecord(
        client_id=None, feed_source_id=None, task_type="policy_check",
        provider_config_id=None, model="x", cache_hit=False,
        prompt_tokens=0, completion_tokens=0, cost_usd=None,
        latency_ms=0, error_code="timeout",
    ))  # must not raise


@pytest.mark.asyncio
async def test_aggregate_usage_group_by_client(session_factory):
    writer = UsageLogWriter(session_factory)
    for client_id in (7, 7, 9):
        await writer.write(UsageRecord(
            client_id=client_id, feed_source_id=None, task_type="policy_check",
            provider_config_id=1, model="gpt-4o-mini", cache_hit=False,
            prompt_tokens=100, completion_tokens=20,
            cost_usd=Decimal("0.000100"), latency_ms=800, error_code=None,
        ))
    async with session_factory() as session:
        rows = await aggregate_usage(session, group_by="client")
    by_key = {r["group_key"]: r for r in rows}
    assert by_key[7]["calls"] == 2
    assert by_key[9]["calls"] == 1
    assert by_key[7]["prompt_tokens"] == 200


@pytest.mark.asyncio
async def test_summarize_usage_totals_and_savings(session_factory):
    from app.ai.usage import summarize_usage

    writer = UsageLogWriter(session_factory)
    await writer.write(UsageRecord(
        client_id=None, feed_source_id=None, task_type="title_optimization",
        provider_config_id=None, model="bulk", cache_hit=False,
        prompt_tokens=100, completion_tokens=20,
        cost_usd=Decimal("0.0010"), latency_ms=10, error_code=None,
    ))
    await writer.write(UsageRecord(
        client_id=None, feed_source_id=None, task_type="title_optimization",
        provider_config_id=None, model="bulk", cache_hit=True,
        prompt_tokens=100, completion_tokens=20,
        cost_usd=Decimal("0.0010"), latency_ms=0, error_code=None,
    ))
    async with session_factory() as session:
        summary = await summarize_usage(session)
    assert summary["calls"] == 2
    assert summary["cache_hits"] == 1
    assert summary["hit_ratio"] == 0.5
    assert summary["cost_saved_usd"] == Decimal("0.0010")
    assert summary["saved_prompt_tokens"] == 100
