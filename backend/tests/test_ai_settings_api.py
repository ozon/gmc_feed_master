"""AI settings endpoints: seed, persist, hot-apply, validation, RBAC."""

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
            await session.execute(delete(AiProviderConfig))
            session.add(AiProviderConfig(
                name="bulk-1", provider_type="litellm", base_url="", api_key="",
                model="openai/gpt-4o-mini", tier="bulk", max_concurrency=2,
                timeout_s=30, enabled=True,
            ))
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


DEFAULTS = {
    "ai_cache_type": "local",
    "ai_cache_namespace": "gmc-ai",
    "ai_cache_ttl_taxonomy_s": 2592000,
    "ai_cache_ttl_content_s": 604800,
    "ai_router_timeout_s": 30,
    "ai_router_num_retries": 2,
    "ai_router_allowed_fails": 3,
    "ai_router_cooldown_s": 30,
    "ai_instructor_max_retries": 2,
    "ai_usage_retention_days": 90,
}


@pytest.mark.asyncio
async def test_get_ai_settings_seeds_defaults(admin_http) -> None:
    response = await admin_http.get("/admin/ai/settings")
    assert response.status_code == 200
    body = response.json()
    for key, value in DEFAULTS.items():
        assert body[key] == value
    assert body["redis_from_env"] is False
    assert body["effective_cache_backend"] == "local"


@pytest.mark.asyncio
async def test_put_ai_settings_persists_and_hot_applies(admin_http, settings_app) -> None:
    app, _ = settings_app
    response = await admin_http.put("/admin/ai/settings", json={
        **DEFAULTS, "ai_cache_namespace": "tenant-x", "ai_router_num_retries": 5,
    })
    assert response.status_code == 200
    assert response.json()["ai_cache_namespace"] == "tenant-x"

    follow = await admin_http.get("/admin/ai/settings")
    assert follow.json()["ai_router_num_retries"] == 5

    service = app.state.ai_service
    assert service._cache is not None
    assert service._router_settings is not None
    assert service._router_settings.num_retries == 5


@pytest.mark.asyncio
async def test_put_ai_settings_rejects_invalid_value(admin_http) -> None:
    response = await admin_http.put("/admin/ai/settings", json={
        **DEFAULTS, "ai_router_timeout_s": 0,
    })
    assert response.status_code == 422
