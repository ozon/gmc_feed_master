from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ai import AiProviderConfig, AiResultCache, AiUsageLog


@pytest_asyncio.fixture
async def session(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_provider_config_round_trip(session):
    async with session.begin():
        session.add(AiProviderConfig(
            name="primary",
            provider_type="openai_compatible",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o-mini",
            max_concurrency=4,
            timeout_s=30,
            enabled=True,
            is_default=True,
        ))
    async with session.begin():
        row = (await session.execute(
            select(AiProviderConfig).where(AiProviderConfig.name == "primary")
        )).scalar_one()
        assert row.input_price_per_mtok is None
        assert row.output_price_per_mtok is None
        assert row.is_default is True


@pytest.mark.asyncio
async def test_ai_result_cache_unique_key(session):
    from sqlalchemy.exc import IntegrityError

    async with session.begin():
        session.add(AiProviderConfig(
            name="primary", provider_type="openai_compatible",
            base_url="http://localhost:11434/v1", api_key="",
            model="llama3.3", max_concurrency=2, timeout_s=60,
            enabled=True, is_default=True,
        ))
    async with session.begin():
        config = (await session.execute(select(AiProviderConfig))).scalar_one()
        session.add(AiResultCache(
            task_type="attribute_enrichment", provider_config_id=config.id,
            model="llama3.3", template_version="builtin",
            input_hash="a" * 64, output={"color": "blue"},
        ))
    # Duplicate key inside one transaction: flush must raise IntegrityError.
    async with session.begin():
        config = (await session.execute(select(AiProviderConfig))).scalar_one()
        session.add(AiResultCache(
            task_type="attribute_enrichment", provider_config_id=config.id,
            model="llama3.3", template_version="builtin",
            input_hash="a" * 64, output={"color": "red"},
        ))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.asyncio
async def test_ai_usage_log_round_trip(session):
    async with session.begin():
        session.add(AiUsageLog(
            client_id=1, feed_source_id=None, task_type="policy_check",
            provider_config_id=1, model="gpt-4o-mini", cache_hit=False,
            prompt_tokens=100, completion_tokens=20,
            cost_usd=0.0001, latency_ms=800, error_code=None,
        ))
    async with session.begin():
        row = (await session.execute(select(AiUsageLog))).scalar_one()
        assert row.task_type == "policy_check"
        assert row.feed_source_id is None
