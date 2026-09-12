"""Enrichment scan route tests: missing-field query, batched AI, OL write."""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user

_spec = importlib.util.spec_from_file_location(
    "enrichment_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/enrichment/plugin.py",
)
assert _spec is not None and _spec.loader is not None
_enrichment_module = importlib.util.module_from_spec(_spec)
sys.modules["enrichment_plugin"] = _enrichment_module
_spec.loader.exec_module(_enrichment_module)

EnrichmentPlugin = _enrichment_module.EnrichmentPlugin


pytestmark = pytest.mark.asyncio


class FakeAiService:
    """Scripted run_task returning AiResult-shaped results."""

    def __init__(self, script):
        from app.ai.service import AiResult

        self._AiResult = AiResult
        self.script = list(script)
        self.calls: list[dict] = []

    def _result(self, value, status="ok"):
        return self._AiResult(
            value=value, status=status, error_code=None if status == "ok" else "x",
            prompt_tokens=1, completion_tokens=1,
        )

    async def run_task(self, task_type, variables, *, client_id=None, feed_source_id=None):
        self.calls.append({"task_type": task_type, "variables": dict(variables)})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):  # (value, status)
            return self._result(*item)
        return self._result(item)


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            from app.models.plugin import Plugin as _Plugin
            from app.models.plugin import PluginConfig as _PluginConfig
            from app.models.plugin import PluginData as _PluginData

            await session.execute(delete(_PluginData))
            await session.execute(delete(_PluginConfig))
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(StagingProduct))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(_Plugin))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    # Plugin registry row required by _get_payload/_put_payload (manifest
    # declares the feed_source data scope the scan route writes at).
    import json as _json

    from app.models.plugin import Plugin as PluginRow

    manifest = _json.loads(
        (Path(__file__).resolve().parents[2]
         / "plugins/core/enrichment/plugin.json").read_text()
    )
    async with factory() as session, session.begin():
        session.add(PluginRow(
            name="enrichment", version="1.0.0", manifest=manifest,
        ))
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    router = APIRouter()
    EnrichmentPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/enrichment")

    def install(script):
        fake = FakeAiService(script)
        app.state.ai_service = fake
        return fake

    yield app, factory, install
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _factory, _install = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _setup_feed(factory, client, products):
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    async with factory() as session, session.begin():
        run = IngestionRun(feed_source_id=feed["id"], status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        for pid, raw in products:
            session.add(
                StagingProduct(
                    feed_source_id=feed["id"], ingestion_run_id=run.id,
                    product_id=pid, content_hash="x", config_hash="x",
                    status="active", excluded=False, raw_data=raw,
                )
            )
    return feed


async def _plugin_data(factory, feed_source_id):
    async with factory() as session:
        row = (await session.execute(
            select_plugin_data(feed_source_id)
        )).scalar_one_or_none()
        return dict(row.data) if row is not None else None


def select_plugin_data(feed_source_id):
    from sqlalchemy import select

    from app.models.plugin import PluginData

    return (
        select(PluginData)
        .where(PluginData.feed_source_id == feed_source_id)
        .order_by(PluginData.id.desc())
        .limit(1)
    )


def select_plugin_row():
    from sqlalchemy import select

    from app.models.plugin import Plugin

    return select(Plugin).where(Plugin.name == "enrichment")


class TestScanRoute:
    async def test_scan_stores_suggestions(self, app_factory):
        _app, factory, install = app_factory
        install([{"color": "blue"}])
        client = await logged_in_client(app_factory)
        feed = await _setup_feed(factory, client, [
            ("p1", {"id": "p1", "title": "Shirt", "color": ""}),
        ])
        resp = await client.post("/plugins/enrichment/scan", json={
            "feed_source_id": feed["id"], "limit": 20,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"scanned": 1, "with_suggestions": 1, "failed": 0}
        data = await _plugin_data(factory, feed["id"])
        assert data is not None
        assert data["suggestions"]["p1"] == {"color": "blue"}

    async def test_scan_skips_fully_pinned_products(self, app_factory):
        _app, factory, install = app_factory
        fake = install([])
        client = await logged_in_client(app_factory)
        feed = await _setup_feed(factory, client, [
            # only color missing; material/size/gtin present
            ("p1", {"id": "p1", "title": "Shirt", "color": "",
                    "material": "cotton", "size": "M", "gtin": "123"}),
        ])
        # pre-pin color for p1 via plugin data (Plugin row already seeded by fixture)
        from app.models.plugin import PluginData

        async with factory() as session, session.begin():
            plugin = (await session.execute(
                select_plugin_row()
            )).scalar_one()
            session.add(PluginData(
                plugin_id=plugin.id, scope="feed_source",
                feed_source_id=feed["id"], key="default",
                data={"suggestions": {}, "pinned": {"p1": {"color": "navy"}}},
            ))
        resp = await client.post("/plugins/enrichment/scan", json={
            "feed_source_id": feed["id"], "limit": 20,
        })
        assert resp.status_code == 200
        assert resp.json()["scanned"] == 0
        assert fake.calls == []

    async def test_scan_counts_ai_failures(self, app_factory):
        _app, factory, install = app_factory
        install([(None, "fallback")])
        client = await logged_in_client(app_factory)
        feed = await _setup_feed(factory, client, [
            ("p1", {"id": "p1", "title": "Shirt", "color": ""}),
        ])
        resp = await client.post("/plugins/enrichment/scan", json={
            "feed_source_id": feed["id"], "limit": 20,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"scanned": 1, "with_suggestions": 0, "failed": 1}
        data = await _plugin_data(factory, feed["id"])
        assert data is not None
        assert data["suggestions"] == {}

    async def test_scan_without_ai_service_503(self, app_factory):
        app, _factory, _install = app_factory
        app.state.ai_service = None  # create_app installs a real one; scan must refuse
        client = await logged_in_client(app_factory)
        feed = await _setup_feed(_factory, client, [
            ("p1", {"id": "p1", "title": "Shirt", "color": ""}),
        ])
        resp = await client.post("/plugins/enrichment/scan", json={
            "feed_source_id": feed["id"], "limit": 20,
        })
        assert resp.status_code == 503

    async def test_scan_scope_enforced_404(self, app_factory):
        app, factory, install = app_factory
        install([{"color": "blue"}])
        client = await logged_in_client(app_factory)
        feed = await _setup_feed(factory, client, [
            ("p1", {"id": "p1", "title": "Shirt", "color": ""}),
        ])
        # restricted user assigned to an unrelated client
        from app.models.user_client import UserClient
        from app.security.passwords import hash_password

        async with factory() as session, session.begin():
            other = Client(name="Other")
            session.add(other)
            await session.flush()
            bob = User(
                username="bob", password_hash=hash_password("bob-pass"), role="user"
            )
            session.add(bob)
            await session.flush()
            session.add(UserClient(user_id=bob.id, client_id=other.id))
        rclient = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
        assert (await rclient.post(
            "/auth/login", json={"username": "bob", "password": "bob-pass"}
        )).status_code == 200
        resp = await rclient.post("/plugins/enrichment/scan", json={
            "feed_source_id": feed["id"], "limit": 20,
        })
        assert resp.status_code == 404
        await rclient.aclose()
