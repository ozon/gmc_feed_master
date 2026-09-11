from __future__ import annotations

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
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
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
        "is_default": True,
    })
    assert create.status_code == 201
    body = create.json()
    assert body["id"] > 0
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
async def test_only_one_default_provider(admin_http):
    await admin_http.post("/admin/ai/providers", json={
        "name": "first", "base_url": "https://api.openai.com/v1",
        "api_key": "k1", "model": "m1", "is_default": True,
    })
    second = await admin_http.post("/admin/ai/providers", json={
        "name": "second", "base_url": "https://api.openai.com/v1",
        "api_key": "k2", "model": "m2", "is_default": True,
    })
    assert second.status_code == 201
    listing = {row["id"]: row for row in (await admin_http.get("/admin/ai/providers")).json()}
    defaults = [row for row in listing.values() if row["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "second"  # newest default wins


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
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
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
    # Prime the per-config caches via a direct call, then verify PATCH clears them.
    service._providers[provider_id] = object()
    service._breakers[provider_id] = object()
    service._semaphores[provider_id] = object()
    patch = await admin_http.patch(
        f"/admin/ai/providers/{provider_id}", json={"model": "m2"},
    )
    assert patch.status_code == 200
    assert provider_id not in service._providers
    assert provider_id not in service._breakers
    assert provider_id not in service._semaphores


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
