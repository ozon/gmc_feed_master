"""Rules plugin AI routes: template listing and render-only preview."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import IngestionRun
from app.models.ai import PromptTemplate
from app.models.plugin import Plugin as PluginRow
from app.models.staging import StagingProduct
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio

_spec = importlib.util.spec_from_file_location(
    "rules_plugin_ai", Path(__file__).resolve().parents[2] / "plugins/core/rules/plugin.py"
)
assert _spec is not None and _spec.loader is not None
_rules_module = importlib.util.module_from_spec(_spec)
sys.modules["rules_plugin_ai"] = _rules_module
_spec.loader.exec_module(_rules_module)
RulesPlugin = _rules_module.RulesPlugin


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed_initial_user(session, "operator", "pw")
    manifest = json.loads(
        (Path(__file__).resolve().parents[2] / "plugins/core/rules/plugin.json").read_text()
    )
    async with factory() as session, session.begin():
        session.add(PluginRow(name="rules", version="1.0.0", manifest=manifest))
    settings = Settings(_env_file=None, session_secret="test-secret",
                        initial_username="operator", initial_password="pw",
                        database_url=isolated_database_url)
    app = create_app(settings=settings, db_session_factory=factory)
    router = APIRouter()
    RulesPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/rules")
    yield app, factory
    await engine.dispose()


async def _login(app_factory):
    app, _factory = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _feed(factory, client):
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    async with factory() as session, session.begin():
        run = IngestionRun(feed_source_id=feed["id"], status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        session.add(StagingProduct(
            feed_source_id=feed["id"], ingestion_run_id=run.id, product_id="p1",
            content_hash="x", config_hash="x", status="active", excluded=False,
            raw_data={"id": "p1", "title": "Red Socks"},
        ))
        session.add(PromptTemplate(
            task_type="title_optimization", client_id=None, version=1, name="T1",
            system_prompt="sys", user_prompt="Rewrite {{title}}",
            variables=["title"], is_active=True,
        ))
    return feed


async def test_templates_lists_global(app_factory):
    client = await _login(app_factory)
    feed = await _feed(app_factory[1], client)
    resp = await client.get(
        f"/plugins/rules/ai/templates?feed_source_id={feed['id']}"
        "&task_type=title_optimization"
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["name"] for i in items] == ["T1"]


async def test_templates_rejects_unknown_task_type(app_factory):
    client = await _login(app_factory)
    feed = await _feed(app_factory[1], client)
    resp = await client.get(
        f"/plugins/rules/ai/templates?feed_source_id={feed['id']}&task_type=nope"
    )
    assert resp.status_code == 422


async def test_preview_renders_template_without_ai_call(app_factory):
    client = await _login(app_factory)
    feed = await _feed(app_factory[1], client)
    resp = await client.post("/plugins/rules/ai/preview", json={
        "feed_source_id": feed["id"], "taskType": "title_optimization", "templateId": 1,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "Red Socks" in body["messages"][1]["content"]
    assert body["errors"] == []


async def test_preview_missing_feed_source_is_distinct_404(app_factory):
    client = await _login(app_factory)
    resp = await client.post("/plugins/rules/ai/preview", json={
        "feed_source_id": 999, "taskType": "rule_value", "system": "s", "user": "u",
        "variables": [],
    })
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feed source not found"
