from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.cache import AiResultCacheStore
from app.ai.usage import UsageLogWriter, UsageRecord, aggregate_usage, estimate_cost
from app.models.ai import AiProviderConfig, AiUsageLog


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def config_id(session_factory):
    async with session_factory() as session:
        async with session.begin():
            config = AiProviderConfig(
                name="primary", provider_type="openai_compatible",
                base_url="https://api.openai.com/v1", api_key="sk-test",
                model="gpt-4o-mini", max_concurrency=4, timeout_s=30,
                enabled=True, is_default=True,
            )
            session.add(config)
            await session.flush()
            return config.id


@pytest.mark.asyncio
async def test_cache_store_and_lookup_round_trip(session_factory, config_id):
    store = AiResultCacheStore(session_factory)
    hit = await store.lookup(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64
    )
    assert hit is None
    await store.store(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64,
        {"color": "blue"},
    )
    hit = await store.lookup(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64
    )
    assert hit is not None
    assert hit.output == {"color": "blue"}


@pytest.mark.asyncio
async def test_cache_lookup_misses_on_different_template_version(session_factory, config_id):
    store = AiResultCacheStore(session_factory)
    await store.store(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64,
        {"color": "blue"},
    )
    assert await store.lookup(
        "attribute_enrichment", config_id, "gpt-4o-mini", "v2", "a" * 64
    ) is None


@pytest.mark.asyncio
async def test_cache_store_duplicate_key_does_not_raise(session_factory, config_id):
    store = AiResultCacheStore(session_factory)
    await store.store(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64,
        {"color": "blue"},
    )
    # Concurrent insert of the same key must be swallowed, not raised.
    await store.store(
        "attribute_enrichment", config_id, "gpt-4o-mini", "builtin", "a" * 64,
        {"color": "red"},
    )


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


def test_estimate_cost_with_prices():
    cost = estimate_cost(1_000_000, 500_000, Decimal("0.15"), Decimal("0.60"))
    assert cost == Decimal("0.450000")


def test_estimate_cost_without_prices_is_none():
    assert estimate_cost(100, 50, None, Decimal("0.60")) is None
    assert estimate_cost(100, 50, Decimal("0.15"), None) is None


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
