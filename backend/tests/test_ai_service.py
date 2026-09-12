from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.provider import AiRequest, AiResponse
from app.ai.resilience import RetryPolicy
from app.ai.service import (
    AiChatUnavailable,
    AiService,
    builtin_template_version,
    default_provider_factory,
    resolve_active_template,
)
from app.ai.tasks import TASK_SPECS, TaskSpec
from app.models.ai import AiProviderConfig, AiResultCache, AiUsageLog, PromptTemplate
from app.models.client import Client


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


async def _seed_client_row(session_factory, name: str) -> int:
    async with session_factory() as session, session.begin():
        client = Client(name=name)
        session.add(client)
        await session.flush()
        return client.id


async def _seed_template(
    session_factory, *, task_type="attribute_enrichment", client_id=None,
    version=1, user_prompt="Extract from: {{title}} {{description}}",
    system_prompt="You extract attributes.", active=True,
) -> int:
    async with session_factory() as session, session.begin():
        row = PromptTemplate(
            task_type=task_type, client_id=client_id, version=version,
            name=f"v{version}", system_prompt=system_prompt, user_prompt=user_prompt,
            variables=["title", "description"], is_active=active, created_by="operator",
        )
        session.add(row)
        await session.flush()
        return row.id


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


@pytest.mark.asyncio
async def test_run_task_uses_active_global_template_and_cache_key(session_factory):
    await _seed_default_config(session_factory)
    template_id = await _seed_template(session_factory)
    provider = FakeProvider(responses=[('{"color": "blue"}', (50, 10))])
    service = AiService(session_factory, provider_factory=lambda config: provider)

    result = await service.run_task(
        "attribute_enrichment", {"title": "T", "description": "D"}
    )
    assert result.status == "ok"
    user_content = provider.calls[0].messages[1]["content"]
    assert "Extract from:" in user_content
    assert '<data key="title">T</data>' in user_content

    async with session_factory() as session:
        cache_row = (await session.execute(select(AiResultCache))).scalar_one()
        assert cache_row.template_version == f"tmpl:{template_id}:v1"


@pytest.mark.asyncio
async def test_client_template_overrides_global(session_factory):
    await _seed_default_config(session_factory)
    client_id = await _seed_client_row(session_factory, "acme")
    await _seed_template(session_factory, user_prompt="GLOBAL MARKER {{title}}")
    await _seed_template(
        session_factory, client_id=client_id, version=1,
        user_prompt="CLIENT MARKER {{title}}",
    )
    provider = FakeProvider(responses=[('{"color": "blue"}', (50, 10))])
    service = AiService(session_factory, provider_factory=lambda config: provider)

    await service.run_task(
        "attribute_enrichment", {"title": "T", "description": "D"}, client_id=client_id,
    )
    user_content = provider.calls[0].messages[1]["content"]
    assert "CLIENT MARKER" in user_content
    assert "GLOBAL MARKER" not in user_content


@pytest.mark.asyncio
async def test_new_active_version_invalidates_cache(session_factory):
    await _seed_default_config(session_factory)
    v1_id = await _seed_template(session_factory, version=1, active=True)
    provider = FakeProvider(responses=[
        ('{"color": "blue"}', (50, 10)),
        ('{"color": "red"}', (50, 10)),
    ])
    service = AiService(session_factory, provider_factory=lambda config: provider)
    variables = {"title": "T", "description": "D"}

    await service.run_task("attribute_enrichment", variables)
    assert len(provider.calls) == 1

    # activate v2 (different content) directly in the DB
    v2_id = await _seed_template(
        session_factory, version=2,
        user_prompt="Extract v2: {{title}} {{description}}", active=False,
    )
    async with session_factory() as session, session.begin():
        v1 = await session.get(PromptTemplate, v1_id)
        v1.is_active = False
        v2 = await session.get(PromptTemplate, v2_id)
        v2.is_active = True

    second = await service.run_task("attribute_enrichment", variables)
    assert second.status == "ok"
    assert len(provider.calls) == 2  # cache miss under the new version key

    async with session_factory() as session:
        versions = {
            row.template_version
            for row in (await session.execute(select(AiResultCache))).scalars()
        }
    assert versions == {f"tmpl:{v1_id}:v1", f"tmpl:{v2_id}:v2"}


@pytest.mark.asyncio
async def test_resolve_active_template_db_error_returns_none():
    def broken_factory():
        raise RuntimeError("db down")
    assert await resolve_active_template(broken_factory, "policy_check", None) is None


def test_builtin_version_is_content_hashed():
    spec = TASK_SPECS["title_optimization"]
    v1 = builtin_template_version(spec)
    assert v1.startswith("builtin:")
    changed = TaskSpec(system=spec.system + "x", user=spec.user, validate=spec.validate)
    assert builtin_template_version(changed) != v1
    assert builtin_template_version(spec) == v1


@pytest.mark.asyncio
async def test_complete_chat_ok_returns_response_and_logs_usage(session_factory):
    await _seed_default_config(session_factory)
    provider = FakeProvider(responses=[("Hello!", (12, 3))])
    service = AiService(session_factory, provider_factory=lambda config: provider)
    messages = [{"role": "user", "content": "Hi"}]

    result = await service.complete_chat(messages, client_id=1, feed_source_id=2)

    assert result.content == "Hello!"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 3
    assert len(provider.calls) == 1

    async with session_factory() as session:
        rows = list((await session.execute(
            select(AiUsageLog).order_by(AiUsageLog.id)
        )).scalars())
    assert len(rows) == 1
    assert rows[0].task_type == "chat"
    assert rows[0].cache_hit is False
    assert rows[0].prompt_tokens == 12
    assert rows[0].error_code is None


@pytest.mark.asyncio
async def test_complete_chat_no_provider_raises(session_factory):
    service = AiService(session_factory, provider_factory=lambda config: FakeProvider())
    with pytest.raises(AiChatUnavailable) as exc_info:
        await service.complete_chat([{"role": "user", "content": "Hi"}])
    assert exc_info.value.error_code == "no_provider"


@pytest.mark.asyncio
async def test_complete_chat_retries_rate_limit_then_succeeds(session_factory):
    await _seed_default_config(session_factory)
    limit_error = httpx.HTTPStatusError(
        "rate limited", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(429),
    )
    provider = FakeProvider(
        errors=[limit_error, limit_error],
        responses=[("OK", (20, 5))],
    )
    service = AiService(
        session_factory,
        provider_factory=lambda config: provider,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_s=0.0, jitter=0.0),
    )

    result = await service.complete_chat([{"role": "user", "content": "Hi"}])

    assert result.content == "OK"
    assert result.prompt_tokens == 20
    assert len(provider.calls) == 3  # 2 failures + 1 success


@pytest.mark.asyncio
async def test_complete_chat_non_retryable_raises_with_breaker(session_factory):
    await _seed_default_config(session_factory)
    timeout = httpx.TimeoutException("timed out")
    # Non-retryable with max_attempts=1 so it fails immediately
    provider = FakeProvider(errors=[timeout])
    service = AiService(
        session_factory,
        provider_factory=lambda config: provider,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_s=0.0, jitter=0.0),
        breaker_failure_threshold=1, breaker_window_s=60, breaker_cooldown_s=30,
    )
    with pytest.raises(AiChatUnavailable) as exc_info:
        await service.complete_chat([{"role": "user", "content": "Hi"}])
    assert exc_info.value.error_code == "timeout"

    # Breaker should have recorded the failure — next call should be circuit_open
    with pytest.raises(AiChatUnavailable) as exc_info2:
        await service.complete_chat([{"role": "user", "content": "Hi again"}])
    assert exc_info2.value.error_code == "circuit_open"
