from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from typing_extensions import Self

from app.ai import service as ai_service_module
from app.ai.router import RouterSettings
from app.ai.service import AiResult, AiService, resolve_template_by_id


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


@pytest.mark.asyncio
async def test_llm_call_does_not_receive_cache_control(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_resolve_template", AsyncMock(
        return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1")
    ))
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1), model="m"
    )
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(_FakeModel(value="ok"), completion)
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    await service.run_task("title_optimization", {"title": "t"})
    call_kwargs = instructor_client.create_with_completion.await_args.kwargs
    assert "cache" not in call_kwargs


@pytest.mark.asyncio
async def test_apply_settings_keeps_previous_on_cache_failure(service, monkeypatch) -> None:
    from types import SimpleNamespace

    from app.ai import service as svc_mod

    before = service._cache
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc_mod, "build_router", lambda rows, cfg: object())
    monkeypatch.setattr(svc_mod, "build_instructor", lambda router: object())
    monkeypatch.setattr(
        svc_mod, "NativeCache", lambda **kwargs: SimpleNamespace(enabled=False)
    )
    row = SimpleNamespace(
        ai_router_timeout_s=30, ai_router_num_retries=2, ai_router_allowed_fails=3,
        ai_router_cooldown_s=30, ai_instructor_max_retries=2, ai_cache_type="disk",
        ai_cache_namespace="x", ai_cache_ttl_taxonomy_s=1, ai_cache_ttl_content_s=1,
    )
    with pytest.raises(ValueError):
        await service.apply_settings(row)
    assert service._cache is before


from app.ai.schemas import RuleValueResult


@pytest.mark.asyncio
async def test_run_task_passes_pinned_template_id(service, monkeypatch) -> None:
    resolve = AsyncMock(return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1"))
    monkeypatch.setattr(service, "_resolve_template", resolve)
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(_FakeModel(value="ok"), SimpleNamespace(usage=None, model="m"))
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    await service.run_task("title_optimization", {"title": "t"}, template_id=7)
    resolve.assert_awaited_once_with("title_optimization", None, 7)


class _FakeTemplateSessionFactory:
    """Minimal async-context-manager session exposing an async get()."""

    def __init__(self, row: Any, *, error: bool = False) -> None:
        self._row = row
        self._error = error

    def __call__(self) -> _FakeTemplateSessionFactory:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, model: Any, pk: Any) -> Any:
        if self._error:
            raise RuntimeError("db down")
        return self._row


def _template_row(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": 7,
        "version": 3,
        "is_active": True,
        "client_id": None,
        "system_prompt": "sys",
        "user_prompt": "usr",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_resolve_template_by_id_active_global_row() -> None:
    factory: Any = _FakeTemplateSessionFactory(_template_row())
    resolved = await resolve_template_by_id(factory, 7, None)
    assert resolved == ai_service_module.ResolvedTemplate("sys", "usr", "tmpl:7:v3")


@pytest.mark.asyncio
async def test_resolve_template_by_id_inactive_row_is_none() -> None:
    factory: Any = _FakeTemplateSessionFactory(_template_row(is_active=False))
    assert await resolve_template_by_id(factory, 7, None) is None


@pytest.mark.asyncio
async def test_resolve_template_by_id_other_client_row_is_none() -> None:
    factory: Any = _FakeTemplateSessionFactory(_template_row(client_id=42))
    assert await resolve_template_by_id(factory, 7, 99) is None


@pytest.mark.asyncio
async def test_resolve_template_by_id_matching_client_row() -> None:
    factory: Any = _FakeTemplateSessionFactory(_template_row(client_id=42))
    resolved = await resolve_template_by_id(factory, 7, 42)
    assert resolved == ai_service_module.ResolvedTemplate("sys", "usr", "tmpl:7:v3")


@pytest.mark.asyncio
async def test_resolve_template_by_id_missing_row_is_none() -> None:
    factory: Any = _FakeTemplateSessionFactory(None)
    assert await resolve_template_by_id(factory, 7, None) is None


@pytest.mark.asyncio
async def test_resolve_template_by_id_db_error_is_none() -> None:
    factory: Any = _FakeTemplateSessionFactory(None, error=True)
    assert await resolve_template_by_id(factory, 7, None) is None


@pytest.mark.asyncio
async def test_run_inline_task_returns_value(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(
            RuleValueResult(value="Blue"),
            SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2), model="m"
            ),
        )
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_inline_task("sys", "Title {{title}}", {"title": "Hat"})
    assert result.status == "ok"
    assert result.value.value == "Blue"
    assert result.prompt_tokens == 3


@pytest.mark.asyncio
async def test_run_inline_task_missing_variable_is_fallback(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    result = await service.run_inline_task("sys", "Title {{title}}", {})
    assert result.status == "fallback"
    assert result.error_code == "invalid_task"


@pytest.mark.asyncio
async def test_run_inline_task_lenient_renders_missing_variable_empty(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(
            RuleValueResult(value="Blue"),
            SimpleNamespace(usage=None, model="m"),
        )
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_inline_task("sys", "Title {{title}}", {}, lenient=True)
    assert result.status == "ok"
    messages = instructor_client.create_with_completion.await_args.kwargs["messages"]
    assert '<data key="title"></data>' in messages[1]["content"]


@pytest.mark.asyncio
async def test_run_inline_task_no_provider_is_fallback(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=[]))
    result = await service.run_inline_task("sys", "u", {})
    assert result.status == "fallback"
    assert result.error_code == "no_provider"
