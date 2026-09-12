from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.client import Client
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


def _payload(**overrides) -> dict:
    base = {
        "task_type": "policy_check",
        "name": "Policy default",
        "system_prompt": "Check the product {{title}}.",
        "user_prompt": "Title: {{title}}\nDescription: {{description}}",
        "variables": ["title", "description"],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_first_version_activates(admin_http):
    response = await admin_http.post("/admin/ai/prompt-templates", json=_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["is_active"] is True
    assert body["client_id"] is None


@pytest.mark.asyncio
async def test_second_version_deactivates_first(admin_http):
    first = (await admin_http.post("/admin/ai/prompt-templates", json=_payload())).json()
    second = (await admin_http.post(
        "/admin/ai/prompt-templates", json=_payload(name="v2", system_prompt="Second {{title}}")
    )).json()
    assert second["version"] == 2
    listing = (await admin_http.get("/admin/ai/prompt-templates")).json()
    by_id = {row["id"]: row for row in listing}
    assert by_id[first["id"]]["is_active"] is False
    assert by_id[second["id"]]["is_active"] is True


@pytest.mark.asyncio
async def test_create_rejects_non_canonical_placeholder(admin_http):
    response = await admin_http.post(
        "/admin/ai/prompt-templates", json=_payload(user_prompt="{{secret}}")
    )
    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert any("not a canonical variable" in e for e in errors)


@pytest.mark.asyncio
async def test_create_rejects_undeclared_placeholder(admin_http):
    response = await admin_http.post(
        "/admin/ai/prompt-templates", json=_payload(variables=["title"])
    )
    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert any("not declared" in e for e in errors)


@pytest.mark.asyncio
async def test_create_unknown_task_type_422(admin_http):
    response = await admin_http.post(
        "/admin/ai/prompt-templates", json=_payload(task_type="nonexistent")
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_client_template_requires_existing_client(admin_http):
    response = await admin_http.post(
        "/admin/ai/prompt-templates", json=_payload(client_id=999)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_client_and_global_versions_independent(settings_app, admin_http):
    _, factory = settings_app
    async with factory() as session, session.begin():
        session.add(Client(name="acme"))
    client_id = 1
    global_v1 = (await admin_http.post("/admin/ai/prompt-templates", json=_payload())).json()
    client_v1 = (await admin_http.post(
        "/admin/ai/prompt-templates", json=_payload(client_id=client_id)
    )).json()
    assert client_v1["version"] == 1  # client scope has its own counter
    assert global_v1["is_active"] is True
    assert client_v1["is_active"] is True


@pytest.mark.asyncio
async def test_activate_rolls_back_to_old_version(admin_http):
    first = (await admin_http.post("/admin/ai/prompt-templates", json=_payload())).json()
    await admin_http.post(
        "/admin/ai/prompt-templates", json=_payload(name="v2", system_prompt="Second {{title}}")
    )
    response = await admin_http.post(f"/admin/ai/prompt-templates/{first['id']}/activate")
    assert response.status_code == 200
    assert response.json()["is_active"] is True
    listing = (await admin_http.get("/admin/ai/prompt-templates")).json()
    actives = [row for row in listing if row["is_active"]]
    assert len(actives) == 1
    assert actives[0]["id"] == first["id"]


@pytest.mark.asyncio
async def test_activate_unknown_404(admin_http):
    response = await admin_http.post("/admin/ai/prompt-templates/999/activate")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_single_template(admin_http):
    created = (await admin_http.post("/admin/ai/prompt-templates", json=_payload())).json()
    response = await admin_http.get(f"/admin/ai/prompt-templates/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_list_filters_by_task_type(admin_http):
    await admin_http.post("/admin/ai/prompt-templates", json=_payload())
    await admin_http.post("/admin/ai/prompt-templates", json=_payload(
        task_type="attribute_enrichment",
        system_prompt="Extract {{title}}.",
        user_prompt="{{title}} {{description}}",
    ))
    listing = (await admin_http.get(
        "/admin/ai/prompt-templates", params={"task_type": "policy_check"}
    )).json()
    assert len(listing) == 1
    assert listing[0]["task_type"] == "policy_check"


@pytest.mark.asyncio
async def test_routes_forbidden_for_non_admin(settings_app):
    from app.persistence.users import create_user

    app, factory = settings_app
    async with factory() as session, session.begin():
        await create_user(session, "plain", "user-pass", "user", [])
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "plain", "password": "user-pass"}
    )).status_code == 200
    assert (await client.get("/admin/ai/prompt-templates")).status_code == 403
    assert (await client.post("/admin/ai/prompt-templates", json=_payload())).status_code == 403
    await client.aclose()
