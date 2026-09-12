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


async def _seed_staged_product(factory, title="Blue Shoe", description="A shoe") -> int:
    from app.models.feed_source import FeedSource
    from app.models.ingestion import IngestionRun
    from app.models.staging import StagingProduct
    from app.staging.hashing import content_hash

    async with factory() as session, session.begin():
        client = Client(name="sample-client")
        session.add(client)
        await session.flush()
        feed = FeedSource(client_id=client.id, name="sample-feed", source_format="xml")
        session.add(feed)
        await session.flush()
        run = IngestionRun(feed_source_id=feed.id, status="completed")
        session.add(run)
        await session.flush()
        product = {"id": "p1", "title": title, "description": description}
        session.add(StagingProduct(
            feed_source_id=feed.id, ingestion_run_id=run.id, product_id="p1",
            content_hash=content_hash(product), config_hash="x" * 64,
            status="active", raw_data=product,
        ))
        return feed.id


@pytest.mark.asyncio
async def test_preview_inline_draft_with_inline_product(admin_http):
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "system_prompt": "Check {{title}}.",
        "user_prompt": "{{title}} — {{description}}",
        "variables": ["title", "description"],
        "product": {"title": "Blue Shoe", "description": "A shoe"},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == []
    assert '<data key="title">Blue Shoe</data>' in body["messages"][1]["content"]
    assert sorted(body["used_variables"]) == ["description", "title"]


@pytest.mark.asyncio
async def test_preview_writes_no_usage_rows(settings_app, admin_http):
    _, factory = settings_app
    from sqlalchemy import select

    from app.models.ai import AiUsageLog

    await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "system_prompt": "Check {{title}}.",
        "user_prompt": "{{title}}",
        "variables": ["title"],
        "product": {"title": "T"},
    })
    async with factory() as session:
        assert list((await session.execute(select(AiUsageLog))).scalars()) == []


@pytest.mark.asyncio
async def test_preview_from_staging_sample(settings_app, admin_http):
    _, factory = settings_app
    feed_id = await _seed_staged_product(factory)
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "system_prompt": "Check {{title}}.",
        "user_prompt": "{{title}} — {{description}}",
        "variables": ["title", "description"],
        "feed_source_id": feed_id,
    })
    assert response.status_code == 200
    assert '<data key="title">Blue Shoe</data>' in response.json()["messages"][1]["content"]


@pytest.mark.asyncio
async def test_preview_staging_specific_product_id(settings_app, admin_http):
    _, factory = settings_app
    feed_id = await _seed_staged_product(factory, title="Red Hat")
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "system_prompt": "s {{title}}",
        "user_prompt": "{{title}}",
        "variables": ["title"],
        "feed_source_id": feed_id,
        "product_id": "p1",
    })
    assert response.status_code == 200
    assert '<data key="title">Red Hat</data>' in response.json()["messages"][1]["content"]


@pytest.mark.asyncio
async def test_preview_staging_no_sample_404(settings_app, admin_http):
    _, factory = settings_app
    feed_id = await _seed_staged_product(factory)
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "system_prompt": "s {{title}}",
        "user_prompt": "{{title}}",
        "variables": ["title"],
        "feed_source_id": feed_id,
        "product_id": "nope",
    })
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_preview_rejects_both_template_sources(admin_http):
    created = (await admin_http.post("/admin/ai/prompt-templates", json=_payload())).json()
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "template_id": created["id"],
        "system_prompt": "s {{title}}",
        "user_prompt": "{{title}}",
        "variables": ["title"],
        "product": {"title": "T"},
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_preview_rejects_missing_product_source(admin_http):
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "system_prompt": "s {{title}}",
        "user_prompt": "{{title}}",
        "variables": ["title"],
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_preview_validation_errors_422(admin_http):
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "system_prompt": "s {{secret}}",
        "user_prompt": "{{title}}",
        "variables": ["title", "secret"],
        "product": {"title": "T"},
    })
    assert response.status_code == 422
    assert any("not a canonical variable" in e for e in response.json()["detail"]["errors"])


@pytest.mark.asyncio
async def test_preview_missing_product_field_warns_and_renders_empty(admin_http):
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "system_prompt": "s {{title}}",
        "user_prompt": "{{title}} — {{description}}",
        "variables": ["title", "description"],
        "product": {"title": "T"},  # no description
    })
    assert response.status_code == 200
    body = response.json()
    assert '<data key="description"></data>' in body["messages"][1]["content"]
    assert any("description" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_preview_by_template_id(admin_http):
    created = (await admin_http.post(
        "/admin/ai/prompt-templates", json=_payload(system_prompt="Stored {{title}}.")
    )).json()
    response = await admin_http.post("/admin/ai/prompt-templates/preview", json={
        "task_type": "policy_check",
        "template_id": created["id"],
        "product": {"title": "T", "description": "D"},
    })
    assert response.status_code == 200
    assert "Stored" in response.json()["messages"][0]["content"]
