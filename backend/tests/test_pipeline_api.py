import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.pipeline import ModuleInstance, ModulePipeline
from app.models.plugin import Plugin
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


async def _register_plugin(factory, name="example_upper", enabled=True,
                           extension_point="pipeline_module"):
    manifest = {"id": name, "name": name, "version": "1.0.0",
                "extension_point": extension_point,
                "config_schema": {"type": "object",
                                  "properties": {"suffix": {"type": "string"}},
                                  "required": ["suffix"]},
                "data_schema": {"type": "object"}}
    async with factory() as session:
        async with session.begin():
            session.add(Plugin(name=name, version="1.0.0", enabled=enabled,
                               manifest=manifest))
            await session.flush()


async def test_get_pipeline_empty(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    resp = await client.get(f"/feed-sources/{feed['id']}/pipeline")
    assert resp.status_code == 200
    assert resp.json() == {"instances": []}


async def test_put_pipeline_roundtrip(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()

    class _Plugin:
        def validate_config(self, config):
            if "suffix" not in config:
                raise ValueError("suffix is required")
    app.state.plugin_registry["example_upper"] = _Plugin()

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "name": "Upper",
                       "configuration": {"suffix": "!"}}]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["instances"] == [{"id": body["instances"][0]["id"], "position": 0,
                                  "plugin_id": "example_upper", "name": "Upper",
                                  "configuration": {"suffix": "!"}, "enabled": True}]
    assert (await client.get(f"/feed-sources/{feed['id']}/pipeline")).json() == body

    async with factory() as session:
        fs = await session.get(FeedSource, feed["id"])
        assert fs.active_pipeline_id is not None


async def test_put_pipeline_replaces_instances(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "configuration": {"suffix": "!"}}]})
    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={"instances": []})
    assert resp.status_code == 200
    assert resp.json() == {"instances": []}
    async with factory() as session:
        count = (await session.execute(select(func.count()).select_from(ModuleInstance))).scalar_one()
        assert count == 0


async def test_put_pipeline_validation_failures(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    await _register_plugin(factory, name="disabled_one", enabled=False)
    await _register_plugin(factory, name="not_a_module", extension_point="quality_rule")
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()

    class _Plugin:
        def validate_config(self, config):
            if "suffix" not in config:
                raise ValueError("suffix is required")
    app.state.plugin_registry["example_upper"] = _Plugin()

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "missing", "configuration": {}}]})
    assert resp.status_code == 422 and resp.json()["errors"]

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "disabled_one", "configuration": {}}]})
    assert resp.status_code == 422

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "not_a_module", "configuration": {}}]})
    assert resp.status_code == 422

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "configuration": {}}]})
    assert resp.status_code == 422
    assert any("suffix" in e for e in resp.json()["errors"])


async def test_put_pipeline_same_feed_name_no_collision(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    first_client = (await client.post("/clients", json={"name": "Acme"})).json()
    second_client = (await client.post("/clients", json={"name": "Zeta"})).json()
    feed_a = (await client.post(f"/clients/{first_client['id']}/feed-sources",
                                json={"name": "DE", "source_format": "wide_tsv"})).json()
    feed_b = (await client.post(f"/clients/{second_client['id']}/feed-sources",
                                 json={"name": "DE", "source_format": "wide_tsv"})).json()
    payload = {"instances": [{"plugin_id": "example_upper", "configuration": {"suffix": "!"}}]}
    assert (await client.put(f"/feed-sources/{feed_a['id']}/pipeline", json=payload)).status_code == 200
    assert (await client.put(f"/feed-sources/{feed_b['id']}/pipeline", json=payload)).status_code == 200


async def test_get_pipeline_returns_id_and_enabled(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "name": "Upper",
                       "configuration": {"suffix": "!"}}]})
    assert resp.status_code == 200
    inst = resp.json()["instances"][0]
    assert isinstance(inst["id"], int)
    assert inst["enabled"] is True


async def test_put_pipeline_upsert_keeps_ids(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    first = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "name": "Upper",
                       "configuration": {"suffix": "!"}}]})).json()
    first_id = first["instances"][0]["id"]

    # Re-save: same instance (id passed back), reordered name edit, one new instance.
    second = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [
            {"id": first_id, "plugin_id": "example_upper", "name": "Upper v2",
             "configuration": {"suffix": "?"}, "enabled": False},
            {"plugin_id": "example_upper", "name": "Upper2",
             "configuration": {"suffix": "!"}},
        ]})).json()
    ids = [i["id"] for i in second["instances"]]
    assert ids[0] == first_id          # upsert preserved the row
    assert ids[1] != first_id          # new row got a new id
    assert second["instances"][0]["name"] == "Upper v2"
    assert second["instances"][0]["enabled"] is False

    # Save again dropping the second instance: row removed, first stays.
    third = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"id": first_id, "plugin_id": "example_upper",
                       "name": "Upper v2", "configuration": {"suffix": "?"}}] })).json()
    assert [i["id"] for i in third["instances"]] == [first_id]
    async with factory() as session:
        count = (await session.execute(select(func.count()).select_from(ModuleInstance))).scalar_one()
        assert count == 1


async def test_put_pipeline_reorder_swaps_positions(app_factory):
    # Regression guard for uq_module_instances_pipeline_position: naive
    # in-place UPDATEs collide on any swap; the handler must two-pass.
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    put = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [
            {"plugin_id": "example_upper", "name": "A", "configuration": {"suffix": "a"}},
            {"plugin_id": "example_upper", "name": "B", "configuration": {"suffix": "b"}},
        ]})).json()
    id_a, id_b = put["instances"][0]["id"], put["instances"][1]["id"]

    # Swap the two rows.
    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [
            {"id": id_b, "plugin_id": "example_upper", "name": "B", "configuration": {"suffix": "b"}},
            {"id": id_a, "plugin_id": "example_upper", "name": "A", "configuration": {"suffix": "a"}},
        ]})
    assert resp.status_code == 200
    assert [i["id"] for i in resp.json()["instances"]] == [id_b, id_a]
    async with factory() as session:
        fs = await session.get(FeedSource, feed["id"])
        pipeline = await session.get(ModulePipeline, fs.active_pipeline_id)
        assert pipeline.definition["instances"][0]["name"] == "B"
        assert pipeline.definition["instances"][0]["plugin_id"] == "example_upper"


async def test_put_pipeline_rejects_foreign_instance_id(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    seeded = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "configuration": {"suffix": "!"}}]})
    assert seeded.status_code == 200
    # Instance id belonging to another pipeline would be rejected; simulate with a bogus id.
    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"id": 999999, "plugin_id": "example_upper",
                       "configuration": {"suffix": "!"}}]})
    assert resp.status_code == 422
    assert any("unknown instance" in e for e in resp.json()["errors"])


async def test_patch_instance_enabled(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    put = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "configuration": {"suffix": "!"}}]})).json()
    inst_id = put["instances"][0]["id"]

    resp = await client.patch(f"/feed-sources/{feed['id']}/pipeline/instances/{inst_id}",
                              json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json() == {"id": inst_id, "enabled": False}

    got = (await client.get(f"/feed-sources/{feed['id']}/pipeline")).json()
    assert got["instances"][0]["enabled"] is False

    # definition JSONB mirrors rows
    async with factory() as session:
        fs = await session.get(FeedSource, feed["id"])
        pipeline = await session.get(ModulePipeline, fs.active_pipeline_id)
        assert pipeline.definition["instances"][0]["enabled"] is False


async def test_patch_instance_not_found(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    resp = await client.patch(f"/feed-sources/{feed['id']}/pipeline/instances/999999",
                              json={"enabled": True})
    assert resp.status_code == 404
