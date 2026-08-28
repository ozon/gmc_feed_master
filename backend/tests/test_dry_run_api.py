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
from app.models.quality import QualityFinding
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio

WIDE_TSV = (
    "id\ttitle\tdescription\tlink\timage_link\tavailability\tprice\tcondition\tbrand\tgtin\n"
    "SKU-1\tRed Shirt\tA red shirt\thttp://shop.example/1\thttp://shop.example/1.jpg\tin_stock\t10.00 USD\tnew\tAcme\t0012345678905\n"
    "drop-me\tBlue Hat\tA blue hat\thttp://shop.example/2\thttp://shop.example/2.jpg\tin_stock\t5.00 USD\tnew\tAcme\t0012345678912\n"
    "SKU-3\tBad Row\t\t\thttp://shop.example/3\thttp://shop.example/3.jpg\tin_stock\t7.00 USD\tnew\tAcme\t0012345678929\n"
).encode("utf-8")


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data

    async def fetch(self, url, basic_auth=None, _client=None):
        return self.data


class _StubProbe:
    async def probe(self, url):
        return None, None, "unfetchable in tests"


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
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
        export_dir=str(tmp_path / "exports"),
        public_base_url="http://test.public",
    )
    app = create_app(settings=settings, db_session_factory=factory, fetcher=StubFetcher(WIDE_TSV))
    app.state.image_probe = _StubProbe()
    yield app, factory, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _make_feed(client, source_url="http://source.example/feed.tsv"):
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    feed = (await client.post(f"/clients/{client_id}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv",
                                    "source_url": source_url, "currency": "USD"})).json()
    return feed["id"]


async def test_dry_run_full_pass_no_side_effects(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)
    resp = await client.post(f"/feed-sources/{feed_id}/dry-run", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["processed"] == 3
    assert body["parse_errors"] == 0
    assert body["dropped"] == []
    assert set(body["findings"]) == {"critical", "warning", "info"}
    assert isinstance(body["sample"], list) and len(body["sample"]) == 3
    assert body["sample"][0]["id"] == "SKU-1"
    # no staging writes, no export runs/versions, no findings persisted
    async with factory() as session:
        assert (await session.execute(select(func.count()).select_from(StagingProduct))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(ExportRun))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(QualityFinding))).scalar_one() == 0


async def test_dry_run_limit_caps_rows(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)
    body = (await client.post(f"/feed-sources/{feed_id}/dry-run", json={"limit": 1})).json()
    assert body["total"] == 1
    assert len(body["sample"]) == 1


async def test_dry_run_records_plugin_drops(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)

    class _Upper:
        def validate_config(self, config):
            if "suffix" not in config:
                raise ValueError("suffix is required")

        def process(self, product, config, data, ctx):
            if product.get("id") == "drop-me":
                return None
            return product

    app.state.plugin_registry["example_upper"] = _Upper()
    async with factory() as session:
        async with session.begin():
            plugin = Plugin(name="example_upper", version="1.0.0", enabled=True,
                            manifest={"id": "example_upper", "name": "Example Upper",
                                      "version": "1.0.0", "extension_point": "pipeline_module",
                                      "config_schema": {"type": "object"},
                                      "data_schema": {"type": "object"}})
            session.add(plugin)
            await session.flush()
            pipeline = ModulePipeline(feed_source_id=feed_id, name="p", version="1", definition={})
            session.add(pipeline)
            await session.flush()
            session.add(ModuleInstance(pipeline_id=pipeline.id, plugin_id=plugin.id,
                                       position=0, name="upper", configuration={"suffix": "!"}))
            fs = await session.get(FeedSource, feed_id)
            fs.active_pipeline_id = pipeline.id

    body = (await client.post(f"/feed-sources/{feed_id}/dry-run", json={})).json()
    assert body["processed"] == 2
    assert body["dropped"] == [{"product_id": "drop-me", "plugin_id": "example_upper",
                                "reason": "example_upper dropped the product"}]


async def test_dry_run_findings_grouped_by_severity_and_rule(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)
    resp = await client.post(f"/feed-sources/{feed_id}/dry-run", json={})
    critical = resp.json()["findings"]["critical"]
    assert any(entry["rule"] == "baseline_required" and entry["count"] > 0
               and entry["sample"] for entry in critical)
    entry = next(e for e in critical if e["rule"] == "baseline_required")
    assert set(entry["sample"][0]) == {"product_id", "field", "message"}


async def test_dry_run_source_failure_returns_422(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    # feed without source_url → IngestStep raises ValueError → 422
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    feed = (await client.post(f"/clients/{client_id}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    resp = await client.post(f"/feed-sources/{feed['id']}/dry-run", json={})
    assert resp.status_code == 422 and resp.json()["errors"]


async def test_dry_run_404_and_auth(app_factory):
    app, _, _ = app_factory
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anon.post("/feed-sources/1/dry-run", json={})).status_code == 401
    client = await logged_in_client(app_factory)
    assert (await client.post("/feed-sources/99999/dry-run", json={})).status_code == 404


async def test_dry_run_source_deleted_before_execution_returns_404(app_factory, monkeypatch):
    app, _, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)

    async def _missing(**kwargs):
        raise LookupError(f"feed source {kwargs['feed_source_id']} not found")

    monkeypatch.setattr("app.routes.dry_run.run_dry_run", _missing)
    resp = await client.post(f"/feed-sources/{feed_id}/dry-run", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feed source not found"
