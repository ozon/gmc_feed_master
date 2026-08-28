import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.pipeline import ModuleInstance, ModulePipeline
from app.models.plugin import Plugin, PluginConfig, PluginData
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


def make_manifest(**overrides):
    manifest = {
        "id": "title_case",
        "name": "Title Case",
        "version": "1.0.0",
        "extension_point": "pipeline_module",
        "config_schema": {
            "type": "object",
            "properties": {"prefix": {"type": "string"}},
            "additionalProperties": False,
        },
        "data_schema": {"type": "object"},
        "config_scope": ["global", "client"],
    }
    manifest.update(overrides)
    return manifest


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(PluginData))
            await session.execute(delete(PluginConfig))
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Plugin))
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


async def seed_plugin(factory, name="title_case", version="1.0.0", manifest=None, enabled=False):
    async with factory() as session:
        async with session.begin():
            plugin = Plugin(
                name=name,
                version=version,
                manifest=manifest if manifest is not None else make_manifest(),
                enabled=enabled,
            )
            session.add(plugin)
    return plugin.id


async def logged_in_client(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def create_client_and_feed_source(client):
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Main", "source_format": "xml"},
    )
    assert resp.status_code == 201
    return client_id, resp.json()["id"]


async def test_list_plugins_returns_all_rows_including_disabled(app_factory):
    _, factory = app_factory
    await seed_plugin(factory, name="alpha", version="1.0.0", enabled=True)
    await seed_plugin(factory, name="beta", version="2.0.0", enabled=False)
    client = await logged_in_client(app_factory)
    resp = await client.get("/plugins")
    assert resp.status_code == 200
    body = resp.json()
    assert [entry["id"] for entry in body] == ["alpha", "beta"]
    assert body[0]["name"] == "Title Case"
    assert body[0]["version"] == "1.0.0"
    assert body[0]["enabled"] is True
    assert body[1]["enabled"] is False
    assert body[0]["manifest"]["id"] == "title_case"


async def test_toggle_enabled_round_trip(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    resp = await client.put("/plugins/title_case/enabled", json={"enabled": True})
    assert resp.status_code == 200
    listing = (await client.get("/plugins")).json()
    assert listing[0]["enabled"] is True
    resp = await client.put("/plugins/title_case/enabled", json={"enabled": False})
    assert resp.status_code == 200
    listing = (await client.get("/plugins")).json()
    assert listing[0]["enabled"] is False


async def test_toggle_enabled_unknown_plugin_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.put("/plugins/nope/enabled", json={"enabled": True})
    assert resp.status_code == 404


async def test_config_global_get_defaults_to_empty_dict(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    resp = await client.get("/plugins/title_case/config")
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_config_put_get_round_trip_per_scope(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    client_id, feed_source_id = await create_client_and_feed_source(client)

    resp = await client.put(
        "/plugins/title_case/config", json={"prefix": "Global"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert (await client.get("/plugins/title_case/config")).json() == {"prefix": "Global"}

    resp = await client.put(
        f"/plugins/title_case/config?client_id={client_id}", json={"prefix": "Client"}
    )
    assert resp.status_code == 200
    assert (
        await client.get(f"/plugins/title_case/config?client_id={client_id}")
    ).json() == {"prefix": "Client"}

    global_payload = await client.get("/plugins/title_case/config")
    assert global_payload.json() == {"prefix": "Global"}


async def test_config_put_replaces_previous_payload(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    first = await client.put("/plugins/title_case/config", json={"prefix": "one"})
    assert first.status_code == 200
    second = await client.put("/plugins/title_case/config", json={})
    assert second.status_code == 200
    assert (await client.get("/plugins/title_case/config")).json() == {}


async def test_config_unknown_plugin_returns_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/plugins/nope/config")
    assert resp.status_code == 404
    resp = await client.put("/plugins/nope/config", json={})
    assert resp.status_code == 404


async def test_config_both_scope_params_returns_422_errors_shape(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    client_id, feed_source_id = await create_client_and_feed_source(client)
    resp = await client.get(
        f"/plugins/title_case/config?client_id={client_id}&feed_source_id={feed_source_id}"
    )
    assert resp.status_code == 422
    assert resp.json() == {"errors": ["pass at most one of client_id, feed_source_id"]}
    resp = await client.put(
        f"/plugins/title_case/config?client_id={client_id}&feed_source_id={feed_source_id}",
        json={},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"] == ["pass at most one of client_id, feed_source_id"]


async def test_config_undeclared_scope_returns_422(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    client_id, feed_source_id = await create_client_and_feed_source(client)
    resp = await client.put(
        f"/plugins/title_case/config?feed_source_id={feed_source_id}", json={}
    )
    assert resp.status_code == 422
    assert resp.json() == {"errors": ["scope not declared for this plugin"]}
    resp = await client.get(f"/plugins/title_case/config?feed_source_id={feed_source_id}")
    assert resp.status_code == 422


async def test_config_ownership_missing_client_returns_404(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    resp = await client.get("/plugins/title_case/config?client_id=999999")
    assert resp.status_code == 404
    resp = await client.put("/plugins/title_case/config?client_id=999999", json={})
    assert resp.status_code == 404


async def test_config_ownership_missing_feed_source_returns_404(app_factory):
    _, factory = app_factory
    manifest = make_manifest(config_scope=["global", "feed_source"])
    await seed_plugin(factory, manifest=manifest)
    client = await logged_in_client(app_factory)
    resp = await client.get("/plugins/title_case/config?feed_source_id=999999")
    assert resp.status_code == 404
    resp = await client.put("/plugins/title_case/config?feed_source_id=999999", json={})
    assert resp.status_code == 404


async def test_config_schema_violation_returns_422_with_errors_key(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    resp = await client.put("/plugins/title_case/config", json={"prefix": 42})
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert isinstance(errors, list) and errors
    assert (await client.get("/plugins/title_case/config")).json() == {}


async def test_data_round_trip_happy_path(app_factory):
    _, factory = app_factory
    manifest = make_manifest(data_schema={"type": "object"}, data_scope=["global"])
    await seed_plugin(factory, manifest=manifest)
    client = await logged_in_client(app_factory)
    assert (await client.get("/plugins/title_case/data")).json() == {}
    resp = await client.put("/plugins/title_case/data", json={"seen": 3})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert (await client.get("/plugins/title_case/data")).json() == {"seen": 3}


async def test_data_empty_declared_scopes_rejects_every_scoped_request(app_factory):
    _, factory = app_factory
    manifest = make_manifest(data_scope=[])
    await seed_plugin(factory, manifest=manifest)
    client = await logged_in_client(app_factory)
    client_id, _ = await create_client_and_feed_source(client)
    resp = await client.put(f"/plugins/title_case/data?client_id={client_id}", json={})
    assert resp.status_code == 422
    assert resp.json() == {"errors": ["scope not declared for this plugin"]}


async def test_data_schema_violation_returns_422_with_errors_key(app_factory):
    _, factory = app_factory
    manifest = make_manifest(
        data_schema={"type": "object", "properties": {"seen": {"type": "integer"}}}
    )
    await seed_plugin(factory, manifest=manifest)
    client = await logged_in_client(app_factory)
    resp = await client.put("/plugins/title_case/data", json={"seen": "many"})
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list) and resp.json()["errors"]
    assert (await client.get("/plugins/title_case/data")).json() == {}


async def test_plugin_endpoints_require_auth(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.get("/plugins")).status_code == 401
    assert (await client.put("/plugins/title_case/enabled", json={"enabled": True})).status_code == 401
    assert (await client.get("/plugins/title_case/config")).status_code == 401
    assert (await client.put("/plugins/title_case/config", json={})).status_code == 401
    assert (await client.get("/plugins/title_case/data")).status_code == 401
    assert (await client.put("/plugins/title_case/data", json={})).status_code == 401


async def test_plugins_list_includes_usage_count(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)

    async with factory() as session:
        async with session.begin():
            used = Plugin(name="used_plugin", version="1.0.0", enabled=True,
                          manifest=make_manifest(id="used_plugin"))
            unused = Plugin(name="unused_plugin", version="1.0.0", enabled=True,
                            manifest=make_manifest(id="unused_plugin"))
            session.add_all([used, unused])
            await session.flush()
            acme = Client(name="Acme")
            session.add(acme)
            await session.flush()
            feed = FeedSource(client_id=acme.id, name="DE", source_format="wide_tsv")
            session.add(feed)
            await session.flush()
            pipeline = ModulePipeline(feed_source_id=feed.id, name="p", version="1", definition={})
            session.add(pipeline)
            await session.flush()
            session.add_all([
                ModuleInstance(pipeline_id=pipeline.id, plugin_id=used.id,
                               position=0, name="a", configuration={}),
                ModuleInstance(pipeline_id=pipeline.id, plugin_id=used.id,
                               position=1, name="b", configuration={}),
            ])

    resp = await client.get("/plugins")
    assert resp.status_code == 200
    by_id = {p["id"]: p for p in resp.json()}
    assert by_id["used_plugin"]["used_by_feed_sources"] == 1
    assert by_id["unused_plugin"]["used_by_feed_sources"] == 0
