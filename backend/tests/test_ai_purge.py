from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.purge import AiPurgeCounts, purge_expired_ai
from app.models.ai import AiProviderConfig, AiResultCache, AiUsageLog
from app.models.global_setting import GlobalSetting


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)


async def _seed_retention(factory, days: int) -> None:
    async with factory() as session, session.begin():
        await session.execute(delete(GlobalSetting))
        session.add(GlobalSetting(
            id=1,
            staging_removal_retention_days=90,
            staging_history_retention_days=90,
            ingestion_run_retention_days=90,
            ai_usage_retention_days=days,
            ai_cache_retention_days=days,
        ))


async def _seed_rows(factory, config_id: int) -> None:
    days_old = 120  # older than the 90-day default retention
    old_usage = AiUsageLog(
        client_id=1, feed_source_id=None, task_type="policy_check",
        provider_config_id=config_id, model="m", cache_hit=False,
        prompt_tokens=1, completion_tokens=1, cost_usd=None,
        latency_ms=1, error_code=None,
    )
    fresh_usage = AiUsageLog(
        client_id=1, feed_source_id=None, task_type="policy_check",
        provider_config_id=config_id, model="m", cache_hit=False,
        prompt_tokens=1, completion_tokens=1, cost_usd=None,
        latency_ms=1, error_code=None,
    )
    old_cache = AiResultCache(
        task_type="policy_check", provider_config_id=config_id,
        model="m", template_version="builtin", input_hash="o" * 64,
        output={},
    )
    fresh_cache = AiResultCache(
        task_type="policy_check", provider_config_id=config_id,
        model="m", template_version="builtin", input_hash="f" * 64,
        output={},
    )
    async with factory() as session, session.begin():
        session.add_all([old_usage, fresh_usage, old_cache, fresh_cache])
        await session.flush()
        await session.execute(
            update(AiUsageLog)
            .where(AiUsageLog.id == old_usage.id)
            .values(created_at=NOW - timedelta(days=days_old))
        )
        await session.execute(
            update(AiUsageLog)
            .where(AiUsageLog.id == fresh_usage.id)
            .values(created_at=NOW - timedelta(days=1))
        )
        await session.execute(
            update(AiResultCache)
            .where(AiResultCache.id == old_cache.id)
            .values(created_at=NOW - timedelta(days=days_old))
        )
        await session.execute(
            update(AiResultCache)
            .where(AiResultCache.id == fresh_cache.id)
            .values(created_at=NOW - timedelta(days=1))
        )


async def _seed_config(factory) -> int:
    async with factory() as session, session.begin():
        config = AiProviderConfig(
            name="primary", provider_type="openai_compatible",
            base_url="https://api.openai.com/v1", api_key="k",
            model="m", max_concurrency=2, timeout_s=30,
            enabled=True, is_default=True,
        )
        session.add(config)
        await session.flush()
        return config.id


@pytest.mark.asyncio
async def test_purge_deletes_only_expired_rows(session_factory):
    config_id = await _seed_config(session_factory)
    await _seed_retention(session_factory, days=90)
    await _seed_rows(session_factory, config_id)

    counts = await purge_expired_ai(session_factory, NOW)
    assert counts == AiPurgeCounts(usage_rows=1, cache_rows=1)

    async with session_factory() as session:
        remaining_usage = list((await session.execute(select(AiUsageLog))).scalars())
        remaining_cache = list((await session.execute(select(AiResultCache))).scalars())
    assert len(remaining_usage) == 1
    assert len(remaining_cache) == 1


@pytest.mark.asyncio
async def test_purge_respects_configured_retention(session_factory):
    config_id = await _seed_config(session_factory)
    await _seed_retention(session_factory, days=200)  # keep 120-day-old rows
    await _seed_rows(session_factory, config_id)

    counts = await purge_expired_ai(session_factory, NOW)
    assert counts == AiPurgeCounts(usage_rows=0, cache_rows=0)
