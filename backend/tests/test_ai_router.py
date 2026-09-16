from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai import router as ai_router


def _row(**kw):
    base = {
        "id": 1, "name": "bulk-1", "provider_type": "litellm", "base_url": "",
        "api_key": "", "model": "openai/gpt-4o-mini", "tier": "bulk",
        "max_concurrency": 4, "timeout_s": 30, "enabled": True,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_deployment_for_litellm_row() -> None:
    dep = ai_router.deployment_for(_row())
    assert dep["model_name"] == "bulk"
    assert dep["litellm_params"]["model"] == "openai/gpt-4o-mini"
    assert dep["litellm_params"]["timeout"] == 30


def test_deployment_for_legacy_openai_compatible_row() -> None:
    dep = ai_router.deployment_for(
        _row(provider_type="openai_compatible", model="gpt-4o-mini",
             base_url="https://api.example.com/v1", api_key="sk-x")
    )
    assert dep["litellm_params"]["model"] == "openai/gpt-4o-mini"
    assert dep["litellm_params"]["api_base"] == "https://api.example.com/v1"
    assert dep["litellm_params"]["api_key"] == "sk-x"


def test_deployment_does_not_double_prefix_already_prefixed_model() -> None:
    dep = ai_router.deployment_for(
        _row(provider_type="openai_compatible", model="openai/gpt-4o-mini")
    )
    assert dep["litellm_params"]["model"] == "openai/gpt-4o-mini"


def test_build_router_skips_disabled_rows(monkeypatch) -> None:
    captured = {}

    class FakeRouter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(ai_router, "Router", FakeRouter)
    cfg = ai_router.RouterSettings(30, 2, 3, 30, 2)
    ai_router.build_router([_row(enabled=True), _row(id=2, enabled=False)], cfg)
    assert [d["model_name"] for d in captured["model_list"]] == ["bulk"]
    assert captured["fallbacks"] == [{"bulk": ["precision"]}]
    assert captured["num_retries"] == 2
    assert captured["allowed_fails"] == 3
    assert captured["cooldown_time"] == 30
    assert captured["timeout"] == 30


@pytest.mark.asyncio
async def test_load_router_settings_uses_defaults_when_no_row() -> None:
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args):
            return None

    def factory():
        return FakeSession()

    cfg = await ai_router.load_router_settings(factory)
    assert cfg == ai_router.RouterSettings(30, 2, 3, 30, 2)


@pytest.mark.asyncio
async def test_load_router_settings_reads_row() -> None:
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args):
            return SimpleNamespace(
                ai_router_timeout_s=45,
                ai_router_num_retries=1,
                ai_router_allowed_fails=5,
                ai_router_cooldown_s=15,
                ai_instructor_max_retries=4,
            )

    def factory():
        return FakeSession()

    cfg = await ai_router.load_router_settings(factory)
    assert cfg == ai_router.RouterSettings(45, 1, 5, 15, 4)
