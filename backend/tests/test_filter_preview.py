"""Filter preview endpoint tests: auth, 404, 422, live pass/fail counts."""

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
    "filter_plugin_preview",
    Path(__file__).resolve().parents[2] / "plugins/core/filter/plugin.py",
)
assert _spec is not None and _spec.loader is not None
_filter_module = importlib.util.module_from_spec(_spec)
sys.modules["filter_plugin_preview"] = _filter_module
_spec.loader.exec_module(_filter_module)

FilterPlugin = _filter_module.FilterPlugin


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
            await session.execute(delete(StagingProduct))
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


async def _setup_feed(factory, client, products):
    """products: list of (product_id, raw_data, status, excluded) tuples."""
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
        for pid, raw, status, excluded in products:
            session.add(
                StagingProduct(
                    feed_source_id=feed["id"], ingestion_run_id=run.id,
                    product_id=pid, content_hash="h", config_hash="c",
                    status=status, raw_data=raw,
                    processed_data=None, excluded=excluded,
                )
            )
    return feed["id"]


def _mount_filter(app):
    router = APIRouter()
    FilterPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/filter")


_BASE = {"title": "T", "price": "1.00 EUR", "brand": "Acme"}


async def test_preview_requires_auth(app_factory):
    app, _ = app_factory
    _mount_filter(app)
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await anon.post(
        "/plugins/filter/preview", json={"feed_source_id": 1, "conditions": []}
    )
    assert resp.status_code == 401


async def test_preview_unknown_feed_source_404(app_factory):
    app, _ = app_factory
    _mount_filter(app)
    client = await logged_in_client(app_factory)
    resp = await client.post(
        "/plugins/filter/preview",
        json={"feed_source_id": 99999, "conditions": []},
    )
    assert resp.status_code == 404


async def test_preview_invalid_conditions_422(app_factory):
    app, factory = app_factory
    _mount_filter(app)
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client, [])
    resp = await client.post(
        "/plugins/filter/preview",
        json={"feed_source_id": feed_id, "conditions": [{"field": "f", "op": "nope"}]},
    )
    assert resp.status_code == 422
    assert "errors" in resp.json()


async def test_preview_counts_pass_fail(app_factory):
    app, factory = app_factory
    _mount_filter(app)
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client, [
        ("a", {"id": "a", **_BASE}, "active", False),
        ("b", {"id": "b", **_BASE, "brand": "Globex"}, "active", False),
        ("c", {"id": "c", **_BASE}, "active", True),  # excluded -> not counted
        ("d", {"id": "d", **_BASE}, "removed", False),  # removed -> not counted
    ])
    resp = await client.post(
        "/plugins/filter/preview",
        json={
            "feed_source_id": feed_id,
            "conditions": [{"field": "brand", "op": "equals", "arg": "Acme"}],
        },
    )
    body = resp.json()
    assert body == {"total": 2, "pass": 1, "fail": 1}
