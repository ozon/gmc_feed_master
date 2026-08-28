from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.export.store import ExportFileStore
from app.main import create_app
from app.models import (
    Client,
    ExportRun,
    ExportVersion,
    FeedSource,
    IngestionRun,
    ModuleInstance,
    ModulePipeline,
    Plugin,
    PluginConfig,
    PluginData,
    QualityFinding,
    StagingHistory,
    StagingProduct,
)
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(StagingHistory))
            await session.execute(delete(StagingProduct))
            await session.execute(delete(QualityFinding))
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(ModuleInstance))
            await session.execute(
                update(FeedSource).values(active_pipeline_id=None)
            )
            await session.execute(delete(ModulePipeline))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(PluginData))
            await session.execute(delete(PluginConfig))
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
        export_dir=str(tmp_path / "exports"),
        public_base_url="http://test.public",
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _full_tree(factory, client):
    """Create client + feed source with rows in EVERY child table; return ids."""
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed["id"], status="success",
                               started_at=datetime.now(timezone.utc))
            session.add(run); await session.flush()
            product = StagingProduct(feed_source_id=feed["id"], ingestion_run_id=run.id,
                                     product_id="p1", content_hash="h", config_hash="c",
                                     status="active", raw_data={"id": "p1"})
            session.add(product); await session.flush()
            session.add(StagingHistory(staging_product_id=product.id, snapshot={"id": "p1"}))
            session.add(QualityFinding(feed_source_id=feed["id"], ingestion_run_id=run.id,
                                       code="r", severity="warning", field="title",
                                       message="m", product_id="p1"))
            export_run = ExportRun(feed_source_id=feed["id"], ingestion_run_id=run.id,
                                   status="completed", product_count=1)
            session.add(export_run); await session.flush()
            version = ExportVersion(feed_source_id=feed["id"], export_run_id=export_run.id,
                                    version_number=1, file_hash="x" * 64, product_count=1)
            session.add(version); await session.flush()
            export_run.export_version_id = version.id
            pipeline = ModulePipeline(feed_source_id=feed["id"], name="p", version="1", definition={})
            session.add(pipeline); await session.flush()
            plugin = Plugin(name="example_upper", version="1.0.0", enabled=True,
                            manifest={"id": "example_upper", "extension_point": "pipeline_module"})
            session.add(plugin); await session.flush()
            session.add(ModuleInstance(pipeline_id=pipeline.id, plugin_id=plugin.id,
                                       position=0, name="i", configuration={}))
            session.add(PluginConfig(plugin_id=plugin.id, scope="feed_source",
                                     feed_source_id=feed["id"], key="default", config={"a": 1}))
            session.add(PluginConfig(plugin_id=plugin.id, scope="client",
                                     client_id=created["id"], key="default", config={"b": 2}))
            session.add(PluginData(plugin_id=plugin.id, scope="feed_source",
                                   feed_source_id=feed["id"], key="default", data={"c": 3}))
            fs = await session.get(FeedSource, feed["id"])
            fs.active_pipeline_id = pipeline.id
    return created["id"], feed["id"]


async def test_delete_feed_source_cascades_everything(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id, feed_id = await _full_tree(factory, client)
    resp = await client.delete(f"/feed-sources/{feed_id}")
    assert resp.status_code == 204
    async with factory() as session:
        for model in (StagingHistory, StagingProduct, QualityFinding, ExportVersion,
                      ExportRun, ModuleInstance, ModulePipeline, IngestionRun):
            count = (await session.execute(select(func.count()).select_from(model))).scalar_one()
            assert count == 0, model.__name__
        assert (await session.execute(select(func.count()).select_from(PluginConfig)
                .where(PluginConfig.feed_source_id == feed_id))).scalar_one() == 0
        assert await session.get(Client, client_id) is not None  # client survives


async def test_delete_client_cascades_all_feeds(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id, feed_id = await _full_tree(factory, client)
    resp = await client.delete(f"/clients/{client_id}")
    assert resp.status_code == 204
    async with factory() as session:
        assert await session.get(Client, client_id) is None
        assert await session.get(FeedSource, feed_id) is None
        assert (await session.execute(select(func.count()).select_from(PluginConfig)
                .where(PluginConfig.client_id == client_id))).scalar_one() == 0


async def test_delete_feed_source_rejected_while_run_active(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    client_id, feed_id = await _full_tree(factory, client)
    lock = app.state.lock_registry.get(feed_id)
    async with lock:
        assert (await client.delete(f"/feed-sources/{feed_id}")).status_code == 409
        assert (await client.delete(f"/clients/{client_id}")).status_code == 409
    assert (await client.delete(f"/feed-sources/{feed_id}")).status_code == 204


async def test_delete_removes_published_files(app_factory):
    app, factory, settings = app_factory
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    store = ExportFileStore(Path(settings.export_dir))
    store.publish(feed["id"], b"<xml/>")
    store.write_version(feed["id"], 1, b"<xml/>")
    assert store.published_exists(feed["id"])

    assert (await client.delete(f"/feed-sources/{feed['id']}")).status_code == 204
    assert not store.published_exists(feed["id"])
    assert not (Path(settings.export_dir) / "versions" / str(feed["id"])).exists()
