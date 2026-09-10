"""Category plugin routes: taxonomy endpoints + draft validation."""

from pathlib import Path
from unittest.mock import patch

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
from tests.category_plugin_module import category_plugin as cp

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "category"

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, monkeypatch):
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
    cp.CategoryPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/category")
    yield app, factory, monkeypatch
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


def point_taxonomy_at_fixtures(monkeypatch):
    monkeypatch.setattr(cp, "_taxonomy_directory", lambda: FIXTURES)
    monkeypatch.setattr(cp, "_INDEX", None)


class TestValidateRoute:
    async def test_valid_draft_ok(self, app_factory):
        client = await logged_in_client(app_factory)
        point_taxonomy_at_fixtures(app_factory[2])
        resp = await client.post("/plugins/category/validate", json={
            "rules": [{"id": "r1", "source_field": "product_type", "operator": "eq",
                        "source_value": "Shoes", "taxonomy_id": "166"}],
        })
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_invalid_draft_422(self, app_factory):
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/validate", json={
            "rules": [{"id": "r1", "operator": "nope", "source_value": "x",
                        "taxonomy_id": "1"}],
        })
        assert resp.status_code == 422
        assert resp.json()["errors"]


class TestTaxonomyRoutes:
    async def test_languages_and_invalidation(self, app_factory, tmp_path):
        _, _, mp = app_factory
        mp.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        mp.setattr(cp, "_INDEX", None)
        (tmp_path / "taxonomy-with-ids.en-US.csv").write_text(
            "1,Animals,,,,,,\n", encoding="utf-8"
        )
        client = await logged_in_client(app_factory)
        resp = await client.get("/plugins/category/taxonomy/languages")
        assert resp.json() == {"languages": ["en-US"]}
        (tmp_path / "taxonomy-with-ids.de-DE.csv").write_text(
            "1,Tiere,,,,,,\n", encoding="utf-8"
        )
        cp.taxonomy_index().invalidate()
        resp = await client.get("/plugins/category/taxonomy/languages")
        assert resp.json() == {"languages": ["en-US", "de-DE"]}

    async def test_search_ranks_and_422s_unknown_language(self, app_factory):
        client = await logged_in_client(app_factory)
        point_taxonomy_at_fixtures(app_factory[2])
        resp = await client.get(
            "/plugins/category/taxonomy/search?language=en-US&q=bird&limit=10&offset=0"
        )
        assert [item["id"] for item in resp.json()["items"]] == ["7385", "499954"]
        resp = await client.get("/plugins/category/taxonomy/search?language=xx-XX&q=bird")
        assert resp.status_code == 422

    async def test_taxonomy_validate(self, app_factory):
        client = await logged_in_client(app_factory)
        point_taxonomy_at_fixtures(app_factory[2])
        resp = await client.get("/plugins/category/taxonomy/validate?taxonomy_id=166")
        assert resp.json() == {"valid": True, "path": "Apparel & Accessories"}
        resp = await client.get("/plugins/category/taxonomy/validate?taxonomy_id=999")
        assert resp.json() == {"valid": False, "path": None}


class TestFetchRoute:
    async def test_fetch_rejects_unknown_language(self, app_factory):
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "fr-FR"})
        assert resp.status_code == 422

    async def test_fetch_de_de_converts_and_persists(self, app_factory, tmp_path):
        _, _, mp = app_factory
        mp.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        mp.setattr(cp, "_INDEX", None)
        (tmp_path / "taxonomy-with-ids.en-US.csv").write_text(
            "1,Animals,,,,,,\n", encoding="utf-8"
        )
        upstream = FIXTURES.joinpath("upstream.de-DE.txt").read_text(encoding="utf-8")

        async def fake_fetch(url):
            assert "taxonomy-with-ids.de-DE.txt" in url
            return upstream.encode("utf-8")

        mp.setattr(cp, "_fetch_url", fake_fetch)
        mp.setattr(cp, "MIN_TAXONOMY_ENTRIES", 2)
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "de-DE"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "language": "de-DE", "entries": 3}
        stored = cp.parse_taxonomy_csv(
            (tmp_path / "taxonomy-with-ids.de-DE.csv").read_text(encoding="utf-8")
        )
        assert stored["5001"] == "Sonstiges > Kategorien, Allgemein"
        langs = await client.get("/plugins/category/taxonomy/languages")
        assert langs.json() == {"languages": ["en-US", "de-DE"]}

    async def test_fetch_upstream_failure_502(self, app_factory, tmp_path):
        _, _, mp = app_factory
        mp.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        mp.setattr(cp, "_INDEX", None)

        async def failing_fetch(url):
            raise RuntimeError("boom")

        mp.setattr(cp, "_fetch_url", failing_fetch)
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "de-DE"})
        assert resp.status_code == 502

    async def test_fetch_upstream_too_small_502(self, app_factory, tmp_path):
        _, _, mp = app_factory
        mp.setattr(cp, "_taxonomy_directory", lambda: tmp_path)
        mp.setattr(cp, "_INDEX", None)

        async def tiny_fetch(url):
            return b"1 - Tiere & Tierbedarf\n"

        mp.setattr(cp, "_fetch_url", tiny_fetch)
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "de-DE"})
        assert resp.status_code == 502


class TestFetchRouteUnwritableDirectory:
    async def test_fetch_unwritable_directory_500(self, app_factory, tmp_path):
        _, _, mp = app_factory
        not_a_dir = tmp_path / "not-a-dir.csv"
        not_a_dir.write_text("irrelevant", encoding="utf-8")
        mp.setattr(cp, "_taxonomy_directory", lambda: not_a_dir)
        mp.setattr(cp, "_INDEX", None)
        upstream = FIXTURES.joinpath("upstream.de-DE.txt").read_text(encoding="utf-8")

        async def valid_fetch(url):
            return upstream.encode("utf-8")

        mp.setattr(cp, "_fetch_url", valid_fetch)
        mp.setattr(cp, "MIN_TAXONOMY_ENTRIES", 2)
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/category/taxonomy/fetch", json={"language": "de-DE"})
        assert resp.status_code == 500
        assert "cannot write taxonomy file" in resp.json()["detail"]


class TestDatabaseUnavailableRoutes:
    async def test_stats_matches_product_503_when_db_missing(
        self, isolated_database_url
    ):
        from app.db import engine as db_engine

        url = isolated_database_url
        isolation_engine = create_async_engine(url, pool_size=2, max_overflow=0)
        isolation_factory = async_sessionmaker(isolation_engine, expire_on_commit=False)
        async with isolation_factory() as session:
            async with session.begin():
                from app.models.session import Session as DbSession

                await session.execute(delete(DbSession))
                await session.execute(delete(User))
            await seed_initial_user(session, "operator", "pw")
        settings = Settings(
            _env_file=None,
            session_secret="test-secret",
            initial_username="operator",
            initial_password="pw",
            database_url=url,
        )

        async def none_db_session():
            return None

        app = create_app(settings=settings, db_session_factory=isolation_factory)
        router = APIRouter()
        with patch.object(db_engine, "get_db_session", none_db_session):
            cp.CategoryPlugin().register_routes(router)
        app.include_router(router, prefix="/plugins/category")
        client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
        resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
        assert resp.status_code == 200

        resp = await client.get("/plugins/category/stats?feed_source_id=999")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "database unavailable"

        resp = await client.get("/plugins/category/matches?feed_source_id=999&rule_id=r1")
        assert resp.status_code == 503

        resp = await client.get("/plugins/category/product?feed_source_id=999&product_id=p1")
        assert resp.status_code == 503
        await isolation_engine.dispose()
