from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.provider import AiRequest, AiResponse
from app.ai.resilience import RetryPolicy
from app.ai.service import AiService, default_provider_factory
from app.models.ai import AiProviderConfig, AiUsageLog


class FakeProvider:
    """Test double recording calls, returning canned responses or raising."""

    def __init__(self, responses=None, errors=None):
        self.responses = list(responses or [])
        self.errors = list(errors or [])
        self.calls: list[AiRequest] = []

    async def complete(self, request: AiRequest) -> AiResponse:
        self.calls.append(request)
        if self.errors:
            raise self.errors.pop(0)
        content, tokens = self.responses.pop(0)
        return AiResponse(
            content=content, prompt_tokens=tokens[0], completion_tokens=tokens[1],
            model="fake", latency_ms=5,
        )


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_default_config(session_factory) -> int:
    async with session_factory() as session, session.begin():
        config = AiProviderConfig(
            name="primary", provider_type="openai_compatible",
            base_url="https://api.openai.com/v1", api_key="sk-test",
            model="gpt-4o-mini", max_concurrency=4, timeout_s=1,
            enabled=True, is_default=True,
        )
        session.add(config)
        await session.flush()
        return config.id


@pytest.mark.asyncio
async def test_run_task_ok_and_cached_on_second_call(session_factory):
    await _seed_default_config(session_factory)
    provider = FakeProvider(
        responses=[('{"color": "blue"}', (50, 10))],
    )
    service = AiService(session_factory, provider_factory=lambda config: provider)
    variables = {"title": "Blue Cotton Shirt", "description": "A shirt"}

    first = await service.run_task("attribute_enrichment", variables)
    assert first.status == "ok"
    assert first.value == {"color": "blue"}
    assert first.prompt_tokens == 50
    assert len(provider.calls) == 1

    second = await service.run_task("attribute_enrichment", variables)
    assert second.status == "cache_hit"
    assert second.value == {"color": "blue"}
    assert second.prompt_tokens == 0
    assert len(provider.calls) == 1  # no second provider call


@pytest.mark.asyncio
async def test_run_task_no_provider_returns_fallback(session_factory):
    service = AiService(session_factory, provider_factory=lambda config: FakeProvider())
    result = await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "no_provider"
    assert result.value is None


@pytest.mark.asyncio
async def test_run_task_retries_rate_limit_then_falls_back(session_factory):
    await _seed_default_config(session_factory)
    limit_error = httpx.HTTPStatusError(
        "rate limited", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(429),
    )
    provider = FakeProvider(errors=[limit_error, limit_error, limit_error])
    service = AiService(
        session_factory,
        provider_factory=lambda config: provider,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_s=0.0, jitter=0.0),
    )
    result = await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "rate_limited"
    assert len(provider.calls) == 3  # exactly max_attempts


@pytest.mark.asyncio
async def test_run_task_invalid_response_is_fallback_without_retry(session_factory):
    await _seed_default_config(session_factory)
    provider = FakeProvider(responses=[("not json", (10, 2))])
    service = AiService(session_factory, provider_factory=lambda config: provider)
    result = await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "invalid_response"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_run_task_opens_circuit_after_failures(session_factory):
    await _seed_default_config(session_factory)
    timeout = httpx.TimeoutException("timed out")
    provider = FakeProvider(errors=[timeout] * 6)
    service = AiService(
        session_factory,
        provider_factory=lambda config: provider,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_s=0.0, jitter=0.0),
        breaker_failure_threshold=2, breaker_window_s=60, breaker_cooldown_s=30,
    )
    # call 1: timeout -> fallback; call 2: timeout -> breaker opens
    await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    await service.run_task("attribute_enrichment", {"title": "T", "description": "D"})
    # call 3: circuit open — no provider attempt at all
    result = await service.run_task("attribute_enrichment", {"title": "T2", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "circuit_open"
    assert len(provider.calls) == 2  # third call never reached the provider


@pytest.mark.asyncio
async def test_usage_row_written_on_ok_and_cache_hit(session_factory):
    await _seed_default_config(session_factory)
    provider = FakeProvider(responses=[('{"color": "blue"}', (50, 10))])
    service = AiService(session_factory, provider_factory=lambda config: provider)
    variables = {"title": "Shirt", "description": "D"}
    await service.run_task("attribute_enrichment", variables)
    await service.run_task("attribute_enrichment", variables)

    async with session_factory() as session:
        rows = list((await session.execute(
            select(AiUsageLog).order_by(AiUsageLog.id)
        )).scalars())
    assert len(rows) == 2
    assert rows[0].cache_hit is False
    assert rows[0].prompt_tokens == 50
    assert rows[1].cache_hit is True
    assert rows[1].prompt_tokens == 0


@pytest.mark.asyncio
async def test_run_task_invalid_task_type_is_fallback(session_factory):
    await _seed_default_config(session_factory)
    provider = FakeProvider()
    service = AiService(session_factory, provider_factory=lambda config: provider)
    result = await service.run_task("nonexistent_task", {"title": "T", "description": "D"})
    assert result.status == "fallback"
    assert result.error_code == "invalid_task"
    assert len(provider.calls) == 0


@pytest.mark.asyncio
async def test_invalidate_rebuilds_provider_on_next_call(session_factory):
    await _seed_default_config(session_factory)
    seen: list[str] = []
    factory_calls: list[int] = []

    def tracking_factory(config):
        factory_calls.append(config.id)
        provider = FakeProvider(responses=[('{"color": "blue"}', (10, 2))])
        seen.append(f"provider-{config.id}")
        return provider

    service = AiService(session_factory, provider_factory=tracking_factory)
    # first call builds and caches the provider
    await service.run_task("attribute_enrichment", {"title": "A", "description": "D"})
    assert len(factory_calls) == 1
    # invalidate -> next call rebuilds
    service.invalidate(1)
    await service.run_task("attribute_enrichment", {"title": "B", "description": "D"})
    assert len(factory_calls) == 2


def test_default_provider_factory_builds_openai_compatible():
    from app.ai.openai_compat import OpenAICompatibleProvider

    config = AiProviderConfig(
        id=1, name="primary", provider_type="openai_compatible",
        base_url="https://api.openai.com/v1", api_key="sk",
        model="gpt-4o-mini", max_concurrency=4, timeout_s=30,
        enabled=True, is_default=True,
    )
    provider = default_provider_factory(config)
    assert isinstance(provider, OpenAICompatibleProvider)
