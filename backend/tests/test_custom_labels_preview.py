"""Custom Labels preview endpoint tests: auth, 404, 422, live match counts."""

from datetime import datetime, timezone

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
from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
)
from tests.labels_plugin_module import labels_plugin as _labels_module

CustomLabelsPlugin = _labels_module.CustomLabelsPlugin
evaluate_rules = _labels_module.evaluate_rules


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
    router = APIRouter()
    CustomLabelsPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/custom_labels")
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
                    product_id=pid, content_hash="x", config_hash="x",
                    status=status, excluded=excluded, raw_data=raw,
                )
            )
    return feed


def _rule(rule_id, slot, **over):
    rule = {
        "id": rule_id, "name": rule_id, "isActive": True, "targetSlot": slot,
        "matchField": "id", "valueTemplate": "{brand} - " + rule_id,
        "fallbackTemplate": "",
    }
    rule.update(over)
    return rule


ROWS = [
    ("a1", {"id": "a1", "brand": "Acme"}, "active", False),
    ("a2", {"id": "a2", "brand": "Beta"}, "active", False),
    ("a3", {"id": "a3", "brand": "Acme"}, "removed", False),   # filtered: status
    ("a4", {"id": "a4", "brand": "Acme"}, "active", True),    # filtered: excluded
    ("nobrand", {"id": "nobrand", "brand": ""}, "active", False),
]


class TestPreviewRoute:
    async def test_mounted_route_returns_counts(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            _rule("r1", "custom_label_0", matchField="brand"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "Acme"},
        })
        assert resp.status_code == 200
        body = resp.json()
        # active, non-excluded rows only: a1, a2, nobrand
        assert body["total"] == 3
        assert body["rules"]["r1"] == {"matched": 1, "labeled": 1, "sample": ["a1"]}
        assert body["slots"]["custom_label_0"] == {
            "labeled": 1, "coverage": 33.3, "rules": ["r1"],
        }

    async def test_labeled_any_counts_products_labeled_in_any_slot(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            _rule("r1", "custom_label_0", matchField="brand"),
            _rule("r2", "custom_label_1", matchField="id", valueTemplate="fixed"),
            _rule("r3", "custom_label_2", matchField="id", valueTemplate="both"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "Acme", "r2": "nobrand", "r3": "a1"},
        })
        assert resp.status_code == 200
        body = resp.json()
        # active, non-excluded rows: a1 (brand Acme), a2 (brand Beta), nobrand (brand "")
        # a1 labeled in slot 0 (brand Acme) AND slot 2 (id a1) -> counted ONCE.
        # nobrand labeled in slot 1 (id match, token-free template).
        # a2 (brand Beta, id a2) labeled nowhere -> labeledAny counts the UNION, not the sum.
        assert body["total"] == 3
        assert body["labeledAny"] == 2
        assert body["slots"]["custom_label_0"]["labeled"] == 1
        assert body["slots"]["custom_label_1"]["labeled"] == 1
        assert body["slots"]["custom_label_2"]["labeled"] == 1
        # union is NOT the sum: slot labeleds sum to 3, labeledAny is 2
        assert body["labeledAny"] == sum(
            entry["labeled"] for entry in body["slots"].values()
        ) - 1

    async def test_first_match_wins_and_token_skip(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            # first rule matches a1 but its brand token renders; second matches too
            _rule("r1", "custom_label_1", matchField="brand"),
            _rule("r2", "custom_label_1", matchField="id"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "Acme", "r2": "a2"},
        })
        body = resp.json()
        # r1 matches a1 (Acme) and wins it; r2 matches a2 and wins it.
        assert body["rules"]["r1"]["matched"] == 1
        assert body["rules"]["r1"]["labeled"] == 1
        assert body["rules"]["r2"]["matched"] == 1
        assert body["rules"]["r2"]["labeled"] == 1
        assert body["slots"]["custom_label_1"]["labeled"] == 2

    async def test_token_skip_shadowed_rule_is_matched_not_labeled(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            # nobrand matches r2 by its id, but its empty brand -> token skips
            _rule("r1", "custom_label_2", matchField="brand"),
            _rule("r2", "custom_label_2", matchField="id",
                  valueTemplate="{brand} - r2"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "", "r2": "nobrand"},
        })
        body = resp.json()
        # r1 matches nothing (empty value list); r2 matches nobrand but token skips.
        assert body["rules"]["r2"]["matched"] == 1
        assert body["rules"]["r2"]["labeled"] == 0
        assert body["slots"]["custom_label_2"]["labeled"] == 0

    async def test_match_all_counts_every_product(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [_rule("all1", "custom_label_3", matchMode="all")]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {},
        })
        body = resp.json()
        assert body["total"] == 3
        assert body["rules"]["all1"]["matched"] == 3
        assert body["rules"]["all1"]["labeled"] == 2  # nobrand token-skips

    async def test_fallback_credits_slot_not_rule(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            _rule("r1", "custom_label_4", matchField="id",
                  valueTemplate="{brand} - r1", fallbackTemplate="NOBRAND"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "nobrand"},
        })
        body = resp.json()
        # nobrand matches r1; template token-skips; fallback renders -> slot labeled
        assert body["rules"]["r1"]["labeled"] == 0
        assert body["slots"]["custom_label_4"]["labeled"] == 1

    async def test_inactive_rules_are_excluded(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [_rule("off", "custom_label_0", isActive=False)]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"], "rules": rules, "slotIds": {},
        })
        body = resp.json()
        assert body["rules"] == {}
        assert body["slots"] == {}

    async def test_sample_cap(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [_rule("all1", "custom_label_0", matchMode="all")]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"], "rules": rules,
            "slotIds": {}, "sample_size": 2,
        })
        assert resp.json()["rules"]["all1"]["sample"] == ["a1", "a2"]

    async def test_empty_feed_returns_zero_total(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, [])
        rules = [_rule("r1", "custom_label_0", matchMode="all")]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"], "rules": rules, "slotIds": {},
        })
        body = resp.json()
        assert body["total"] == 0
        assert body["slots"]["custom_label_0"]["coverage"] == 0

    async def test_unknown_feed_404(self, app_factory):
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": 99999, "rules": [], "slotIds": {},
        })
        assert resp.status_code == 404

    async def test_invalid_draft_422(self, app_factory, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", lambda: _registry())
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [_rule("bad", "custom_label_9")]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"], "rules": rules, "slotIds": {},
        })
        assert resp.status_code == 422
        assert any("targetSlot" in e for e in resp.json()["errors"])

    async def test_requires_auth(self, app_factory):
        app, _ = app_factory
        client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
        resp = await client.post("/plugins/custom_labels/preview", json={})
        assert resp.status_code in (401, 422)  # not logged in

    async def test_preview_accepts_frontend_scoped_rules_with_origin_key(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            {**_rule("r1", "custom_label_0", matchMode="all"), "origin": "global"},
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {},
            "sample_size": 5,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] > 0
        assert body["rules"]["r1"]["matched"] > 0


def _registry():
    def attr(name, kind=AttributeKind.SCALAR, fields=()):
        return RegistryAttribute(
            name=name, kind=kind, type="string",
            required=RequirementStatus.OPTIONAL,
            domain=FeedDomain.PRIMARY,
            export_status=ExportStatus.EXPORTABLE,
            fields=fields,
        )

    return RegistryDocument(attributes={
        "id": attr("id"),
        "brand": attr("brand"),
        "item_group_id": attr("item_group_id"),
        "price": attr("price", AttributeKind.STRUCTURED,
                      (SubField("value", "String", RequirementStatus.REQUIRED),)),
    })
