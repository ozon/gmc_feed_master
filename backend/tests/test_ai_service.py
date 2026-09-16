from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from app.ai import service as ai_service_module
from app.ai.router import RouterSettings
from app.ai.service import AiResult, AiService


class _FakeModel(BaseModel):
    value: str


def _provider_rows():
    return [SimpleNamespace(
        id=1, name="bulk", provider_type="litellm", base_url="", api_key="",
        model="openai/gpt-4o-mini", tier="bulk", max_concurrency=4, timeout_s=30,
        enabled=True, input_price_per_mtok=None, output_price_per_mtok=None,
    )]


@pytest.fixture()
def service() -> AiService:
    svc = AiService(session_factory=MagicMock(), clock=None)
    # Pre-set router/cache state so run_task does not hit the DB or build a real Router.
    svc._router = MagicMock()
    svc._router_settings = RouterSettings()
    svc._cache = MagicMock()
    svc._cache.lookup = AsyncMock(return_value=None)
    svc._cache.store = AsyncMock()
    svc._cache.request_kwargs = MagicMock(return_value={"cache": {"namespace": "n", "ttl": 1}})
    svc._usage = MagicMock()
    svc._usage.write = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_run_task_returns_validated_value(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))

    completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5), model="gpt-4o-mini"
    )
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(_FakeModel(value="ok"), completion)
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_task("title_optimization", {"title": "t"})
    assert result.status == "ok"
    assert result.value == _FakeModel(value="ok")
    assert result.prompt_tokens == 10
    instructor_client.create_with_completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_task_returns_fallback_on_instructor_failure(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))

    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_task("title_optimization", {"title": "t"})
    assert result.status == "fallback"
    assert result.value is None
    assert result.error_code == "provider_error"


@pytest.mark.asyncio
async def test_run_task_no_provider_is_fallback(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=[]))
    result = await service.run_task("title_optimization", {"title": "t"})
    assert result == AiResult(value=None, status="fallback", error_code="no_provider",
                              prompt_tokens=0, completion_tokens=0)


@pytest.mark.asyncio
async def test_run_task_cache_hit_skips_llm(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    service._cache.lookup = AsyncMock(return_value={"title": "cached"})
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock()
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_task("title_optimization", {"title": "t"})
    assert result.status == "cache_hit"
    assert result.value.title == "cached"
    instructor_client.create_with_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_task_invalid_cached_value_calls_llm(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    service._cache.lookup = AsyncMock(return_value={"not": "valid"})
    completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1), model="m"
    )
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(_FakeModel(value="fresh"), completion)
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_task("title_optimization", {"title": "t"})
    assert result.status == "ok"
    instructor_client.create_with_completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_task_unknown_task_is_fallback(service) -> None:
    result = await service.run_task("nope", {})
    assert result.status == "fallback"
    assert result.error_code == "invalid_task"
