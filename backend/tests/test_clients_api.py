import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def test_create_client_returns_201(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Acme"
    assert body["status"] == "active"
    assert body["contact_details"] == {}
    assert "id" in body
    assert "created_at" in body


async def test_create_client_duplicate_name_returns_409(app_factory):
    client = await logged_in_client(app_factory)
    assert (await client.post("/clients", json={"name": "Acme"})).status_code == 201
    assert (await client.post("/clients", json={"name": "Acme"})).status_code == 409


async def test_list_clients_ordered_by_name(app_factory):
    client = await logged_in_client(app_factory)
    await client.post("/clients", json={"name": "Zeta"})
    await client.post("/clients", json={"name": "Alpha"})
    resp = await client.get("/clients")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert names == ["Alpha", "Zeta"]


async def test_create_feed_source_without_cron_no_job(app_factory):
    app, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Main", "source_format": "xml"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Main"
    assert body["source_format"] == "xml"
    assert body["cron_expression"] is None
    fs_id = body["id"]
    assert not app.state.scheduler_service.has_job(fs_id)


async def test_create_feed_source_with_valid_cron_registers_job(app_factory):
    app, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Main", "source_format": "xml", "cron_expression": "0 * * * *"},
    )
    assert resp.status_code == 201
    fs_id = resp.json()["id"]
    assert app.state.scheduler_service.has_job(fs_id)


async def test_create_feed_source_invalid_cron_returns_422(app_factory):
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Main", "source_format": "xml", "cron_expression": "not a cron"},
    )
    assert resp.status_code == 422


async def test_create_feed_source_unknown_client_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.post(
        "/clients/999999/feed-sources",
        json={"name": "Main", "source_format": "xml"},
    )
    assert resp.status_code == 404


async def test_list_feed_sources_unknown_client_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/clients/999999/feed-sources")
    assert resp.status_code == 404


async def test_list_feed_sources_ordered_by_name(app_factory):
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    await client.post(f"/clients/{client_id}/feed-sources", json={"name": "Zeta", "source_format": "xml"})
    await client.post(f"/clients/{client_id}/feed-sources", json={"name": "Alpha", "source_format": "xml"})
    resp = await client.get(f"/clients/{client_id}/feed-sources")
    assert resp.status_code == 200
    names = [fs["name"] for fs in resp.json()]
    assert names == ["Alpha", "Zeta"]


async def test_update_feed_source_cron_reschedules(app_factory):
    app, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    fs_id = (
        await client.post(
            f"/clients/{client_id}/feed-sources",
            json={"name": "Main", "source_format": "xml", "cron_expression": "0 * * * *"},
        )
    ).json()["id"]
    resp = await client.put(f"/feed-sources/{fs_id}", json={"cron_expression": "30 * * * *"})
    assert resp.status_code == 200
    assert resp.json()["cron_expression"] == "30 * * * *"
    assert app.state.scheduler_service.has_job(fs_id)


async def test_update_feed_source_clear_cron_unregisters(app_factory):
    app, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    fs_id = (
        await client.post(
            f"/clients/{client_id}/feed-sources",
            json={"name": "Main", "source_format": "xml", "cron_expression": "0 * * * *"},
        )
    ).json()["id"]
    resp = await client.put(f"/feed-sources/{fs_id}", json={"cron_expression": None})
    assert resp.status_code == 200
    assert resp.json()["cron_expression"] is None
    assert not app.state.scheduler_service.has_job(fs_id)


async def test_update_feed_source_invalid_cron_returns_422(app_factory):
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    fs_id = (
        await client.post(
            f"/clients/{client_id}/feed-sources",
            json={"name": "Main", "source_format": "xml"},
        )
    ).json()["id"]
    resp = await client.put(f"/feed-sources/{fs_id}", json={"cron_expression": "bad"})
    assert resp.status_code == 422


async def test_update_feed_source_unknown_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.put("/feed-sources/999999", json={"name": "X"})
    assert resp.status_code == 404


async def test_delete_feed_source_removes_job_and_lock(app_factory):
    app, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    fs_id = (
        await client.post(
            f"/clients/{client_id}/feed-sources",
            json={"name": "Main", "source_format": "xml", "cron_expression": "0 * * * *"},
        )
    ).json()["id"]
    app.state.lock_registry.get(fs_id)
    resp = await client.delete(f"/feed-sources/{fs_id}")
    assert resp.status_code == 204
    assert not app.state.scheduler_service.has_job(fs_id)
    assert not app.state.lock_registry.is_locked(fs_id)


async def test_delete_feed_source_unknown_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.delete("/feed-sources/999999")
    assert resp.status_code == 404


async def test_update_client_fields(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    resp = await client.put(
        f"/clients/{created['id']}",
        json={"name": "Acme GmbH", "status": "paused", "contact_details": {"email": "a@b.c"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Acme GmbH"
    assert body["status"] == "paused"
    assert body["contact_details"] == {"email": "a@b.c"}


async def test_update_client_partial_keeps_other_fields(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    resp = await client.put(f"/clients/{created['id']}", json={"status": "paused"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Acme"
    assert resp.json()["status"] == "paused"


async def test_update_client_not_found(app_factory):
    client = await logged_in_client(app_factory)
    assert (await client.put("/clients/99999", json={"name": "X"})).status_code == 404


async def test_update_client_duplicate_name_returns_409(app_factory):
    client = await logged_in_client(app_factory)
    await client.post("/clients", json={"name": "Acme"})
    other = (await client.post("/clients", json={"name": "Zeta"})).json()
    assert (await client.put(f"/clients/{other['id']}", json={"name": "Acme"})).status_code == 409


async def test_update_client_explicit_null_name_is_ignored(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    resp = await client.put(f"/clients/{created['id']}", json={"name": None})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Acme"


async def test_update_client_empty_status_returns_422(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    resp = await client.put(f"/clients/{created['id']}", json={"status": ""})
    assert resp.status_code == 422


async def test_all_endpoints_require_auth(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post("/clients", json={"name": "X"})).status_code == 401
    assert (await client.get("/clients")).status_code == 401
    assert (await client.post("/clients/1/feed-sources", json={"name": "X", "source_format": "xml"})).status_code == 401
    assert (await client.get("/clients/1/feed-sources")).status_code == 401
    assert (await client.put("/feed-sources/1", json={"name": "X"})).status_code == 401
    assert (await client.delete("/feed-sources/1")).status_code == 401


async def test_feed_source_update_volume_threshold_and_configuration(app_factory):
    client = await logged_in_client(app_factory)
    created_client = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created_client['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    resp = await client.put(
        f"/feed-sources/{feed['id']}",
        json={
            "volume_drop_threshold_pct": 35,
            "configuration": {"basic_auth": {"username": "u", "password": "p"}},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["volume_drop_threshold_pct"] == 35
    assert body["configuration"] == {"basic_auth": {"username": "u", "password": "p"}}


async def test_feed_source_update_volume_threshold_out_of_range(app_factory):
    client = await logged_in_client(app_factory)
    created_client = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created_client['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    resp = await client.put(f"/feed-sources/{feed['id']}", json={"volume_drop_threshold_pct": 101})
    assert resp.status_code == 422


async def test_get_feed_source_returns_detail(app_factory):
    app, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    fs_id = (
        await client.post(
            f"/clients/{client_id}/feed-sources",
            json={"name": "Main", "source_format": "xml"},
        )
    ).json()["id"]

    resp = await client.get(f"/feed-sources/{fs_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == fs_id
    assert body["client_id"] == client_id
    assert body["name"] == "Main"
    assert body["export_url"].endswith(".xml")


async def test_get_feed_source_unknown_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/999999")).status_code == 404


async def test_trigger_run_requires_runner(app_factory):
    app, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    fs_id = (
        await client.post(
            f"/clients/{client_id}/feed-sources",
            json={"name": "Main", "source_format": "xml"},
        )
    ).json()["id"]

    runner = app.state.pipeline_runner
    del app.state.pipeline_runner
    try:
        resp = await client.post(f"/feed-sources/{fs_id}/run")
    finally:
        app.state.pipeline_runner = runner

    assert resp.status_code == 503
