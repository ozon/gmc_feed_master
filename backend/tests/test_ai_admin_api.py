from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.ai import AiProviderConfig
from app.models.global_setting import GlobalSetting
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
            await session.execute(delete(GlobalSetting))
        await seed_initial_user(session, "operator", "admin-pass")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_http(settings_app):
    app, _ = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver/api")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_create_list_providers_api_key_redacted(admin_http):
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-secret-value",
        "model": "gpt-4o-mini",
        "tier": "bulk",
    })
    assert create.status_code == 201
    body = create.json()
    assert body["id"] > 0
    assert body["tier"] == "bulk"
    assert "is_default" not in body
    assert "api_key" not in body

    listing = await admin_http.get("/admin/ai/providers")
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert "api_key" not in rows[0]
    assert rows[0]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_patch_api_key_semantics(settings_app, admin_http):
    _, factory = settings_app
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-secret-value",
        "model": "gpt-4o-mini",
    })
    provider_id = create.json()["id"]

    # absent api_key -> unchanged
    await admin_http.patch(f"/admin/ai/providers/{provider_id}", json={"model": "gpt-4o-mini-2024"})
    async with factory() as session:
        row = await session.get(AiProviderConfig, provider_id)
        assert row.api_key == "sk-secret-value"
        assert row.model == "gpt-4o-mini-2024"

    # explicit "" -> cleared
    await admin_http.patch(f"/admin/ai/providers/{provider_id}", json={"api_key": ""})
    async with factory() as session:
        row = await session.get(AiProviderConfig, provider_id)
        assert row.api_key == ""


@pytest.mark.asyncio
async def test_providers_group_by_tier(admin_http):
    await admin_http.post("/admin/ai/providers", json={
        "name": "bulk-1", "base_url": "https://api.openai.com/v1",
        "api_key": "k1", "model": "gpt-4o-mini", "tier": "bulk",
    })
    second = await admin_http.post("/admin/ai/providers", json={
        "name": "precision-1", "base_url": "https://api.openai.com/v1",
        "api_key": "k2", "model": "gpt-4o", "tier": "precision",
    })
    assert second.status_code == 201
    rows = (await admin_http.get("/admin/ai/providers")).json()
    assert sorted(row["tier"] for row in rows) == ["bulk", "precision"]
    assert all("is_default" not in row for row in rows)


@pytest.mark.asyncio
async def test_provider_rejects_unknown_tier(admin_http):
    response = await admin_http.post("/admin/ai/providers", json={
        "name": "p", "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini", "tier": "platinum",
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_provider_204_and_gone(admin_http):
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary", "base_url": "https://api.openai.com/v1",
        "api_key": "k", "model": "m",
    })
    provider_id = create.json()["id"]
    deleted = await admin_http.delete(f"/admin/ai/providers/{provider_id}")
    assert deleted.status_code == 204
    listing = await admin_http.get("/admin/ai/providers")
    assert listing.json() == []


@pytest.mark.asyncio
async def test_usage_endpoint_returns_aggregates(settings_app, admin_http):
    from app.ai.usage import UsageLogWriter, UsageRecord

    _, factory = settings_app
    writer = UsageLogWriter(factory)
    await writer.write(UsageRecord(
        client_id=7, feed_source_id=None, task_type="policy_check",
        provider_config_id=1, model="gpt-4o-mini", cache_hit=False,
        prompt_tokens=100, completion_tokens=20, cost_usd=None,
        latency_ms=800, error_code=None,
    ))
    response = await admin_http.get("/admin/ai/usage", params={"group_by": "client"})
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["group_key"] == 7
    assert rows[0]["calls"] == 1


@pytest.mark.asyncio
async def test_usage_endpoint_rejects_bad_group_by(admin_http):
    response = await admin_http.get("/admin/ai/usage", params={"group_by": "bogus"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_admin_routes_forbidden_for_non_admin(settings_app):
    from app.persistence.users import create_user

    app, factory = settings_app
    async with factory() as session, session.begin():
        await create_user(session, "plain", "user-pass", "user", [])
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver/api")
    assert (await client.post(
        "/auth/login", json={"username": "plain", "password": "user-pass"}
    )).status_code == 200
    listing = await client.get("/admin/ai/providers")
    assert listing.status_code == 403
    usage = await client.get("/admin/ai/usage")
    assert usage.status_code == 403
    await client.aclose()


@pytest.mark.asyncio
async def test_patch_invalidates_ai_service_provider_cache(settings_app, admin_http):
    app, _ = settings_app
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary", "base_url": "https://api.openai.com/v1",
        "api_key": "k", "model": "m",
    })
    provider_id = create.json()["id"]
    service = app.state.ai_service
    # Prime the runtime collaborators, then verify PATCH drops them.
    service._router = object()
    service._instructor_client = object()
    service._router_settings = object()
    service._cache = object()
    patch = await admin_http.patch(
        f"/admin/ai/providers/{provider_id}", json={"model": "m2"},
    )
    assert patch.status_code == 200
    assert service._router is None
    assert service._instructor_client is None
    assert service._router_settings is None
    assert service._cache is None


@pytest.mark.asyncio
async def test_provider_test_endpoint_reports_error(settings_app, admin_http):
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "primary", "base_url": "https://api.openai.com/v1",
        "api_key": "k", "model": "m", "timeout_s": 1,
    })
    provider_id = create.json()["id"]
    # No real network in CI: the probe call fails fast (1s timeout) and the
    # endpoint reports {"status": "error", "error_code": ...} instead of raising.
    response = await admin_http.post(f"/admin/ai/providers/{provider_id}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "error_code" in body


@pytest.mark.asyncio
async def test_ai_cache_and_usage_endpoints(admin_http) -> None:
    assert (await admin_http.get("/admin/ai/cache")).status_code == 200
    assert (await admin_http.get("/admin/ai/cache/stats")).status_code == 200
    assert (await admin_http.get("/admin/ai/usage/summary")).status_code == 200
    assert (await admin_http.get("/admin/ai/usage/timeseries")).status_code == 200
    cleared = await admin_http.post("/admin/ai/cache/clear", json={})
    assert cleared.status_code == 200
    assert "removed" in cleared.json()


@pytest.mark.asyncio
async def test_provider_presets_endpoint(admin_http):
    response = await admin_http.get("/admin/ai/provider-presets")
    assert response.status_code == 200
    keys = [preset["vendor_key"] for preset in response.json()]
    assert keys == ["openai", "anthropic", "google", "openrouter", "mistral", "groq", "custom"]
    custom = response.json()[-1]
    assert custom["requires_base_url"] is True
    assert custom["supports_catalog"] is False


@pytest.mark.asyncio
async def test_model_catalog_seeds_and_filters(admin_http, monkeypatch):
    from app.ai import model_catalog

    monkeypatch.setattr(model_catalog, "load_bundled", lambda: [
        model_catalog.CatalogEntry(
            vendor="openai", model_id="openai/gpt-4o", display_name="gpt-4o",
            mode="chat", context_window=128000, max_output_tokens=16384,
            input_price_per_mtok=Decimal("2.500000"),
            output_price_per_mtok=Decimal("10.000000"),
            supports_vision=True, supports_function_calling=True,
        ),
        model_catalog.CatalogEntry(
            vendor="anthropic", model_id="anthropic/claude", display_name="claude",
            mode="chat", context_window=200000, max_output_tokens=8192,
            input_price_per_mtok=None, output_price_per_mtok=None,
            supports_vision=False, supports_function_calling=True,
        ),
    ])
    response = await admin_http.get("/admin/ai/model-catalog", params={"vendor": "openai"})
    assert response.status_code == 200
    body = response.json()
    assert [entry["model_id"] for entry in body["entries"]] == ["openai/gpt-4o"]
    entry = body["entries"][0]
    assert entry["is_recommended"] is True
    assert entry["supports_vision"] is True
    assert body["sync"]["source"] == "bundled"


@pytest.mark.asyncio
async def test_model_catalog_refresh_endpoint(settings_app, admin_http, monkeypatch):
    from app.ai import model_catalog

    app, _ = settings_app
    entries = [
        model_catalog.CatalogEntry(
            vendor="openai", model_id=f"openai/model-{i}", display_name=f"model-{i}",
            mode="chat", context_window=1000, max_output_tokens=100,
            input_price_per_mtok=None, output_price_per_mtok=None,
            supports_vision=False, supports_function_calling=False,
        )
        for i in range(60)
    ]
    monkeypatch.setattr(model_catalog, "parse_catalog", lambda raw: entries)

    def handler(request):
        return httpx.Response(200, json={"ok": True})

    app.state.catalog_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = await admin_http.post("/admin/ai/model-catalog/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "github"
    assert body["last_error"] is None


@pytest.mark.asyncio
async def test_create_provider_normalizes_legacy_type(settings_app, admin_http):
    _, factory = settings_app
    create = await admin_http.post("/admin/ai/providers", json={
        "name": "legacy", "provider_type": "openai_compatible",
        "base_url": "https://api.example.com/v1", "api_key": "k", "model": "gpt-4o-mini",
    })
    assert create.status_code == 201
    provider_id = create.json()["id"]
    async with factory() as session:
        row = await session.get(AiProviderConfig, provider_id)
        assert row.provider_type == "litellm"
        assert row.model == "openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_model_catalog_refresh_job_constants():
    from app.ai import model_catalog

    assert model_catalog.MODEL_CATALOG_REFRESH_JOB_ID == "system-ai-model-catalog-refresh"
    assert model_catalog.MODEL_CATALOG_REFRESH_CRON == "0 4 * * *"
