from datetime import datetime, timezone

import pytest
import pytest_asyncio
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


async def _make_feed(factory, client, name):
    created = (await client.post("/clients", json={"name": name})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": f"{name}-feed", "source_format": "wide_tsv"},
        )
    ).json()
    return created["id"], feed["id"]


async def _add_staging(factory, feed_id, product_id, status="active", excluded=False):
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed_id, status="success",
                               started_at=datetime.now(timezone.utc))
            session.add(run)
            await session.flush()
            session.add(
                StagingProduct(
                    feed_source_id=feed_id,
                    ingestion_run_id=run.id,
                    product_id=product_id,
                    content_hash="h",
                    config_hash="c",
                    status=status,
                    excluded=excluded,
                    raw_data={"id": product_id, "title": f"Title {product_id}"},
                )
            )


async def _add_export_run(factory, feed_id, status, product_count=1):
    async with factory() as session:
        async with session.begin():
            session.add(
                ExportRun(
                    feed_source_id=feed_id,
                    status=status,
                    product_count=product_count,
                    started_at=datetime.now(timezone.utc),
                )
            )


async def test_summary_requires_auth(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.get("/dashboard/summary")).status_code == 401


async def test_summary_empty(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/dashboard/summary")
    assert resp.status_code == 200
    assert resp.json() == {"counts": {"clients": 0, "feed_sources": 0,
                                      "active_products": 0, "failed_last_exports": 0},
                           "clients": []}


async def test_summary_counts_and_per_feed_fields(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_a = await _make_feed(factory, client, "Acme")
    client_id_b, feed_b = await _make_feed(factory, client, "Zeta")

    await _add_staging(factory, feed_a, "p1")
    await _add_staging(factory, feed_a, "p2")
    await _add_staging(factory, feed_a, "p3", status="removed")
    await _add_staging(factory, feed_a, "p4", excluded=True)
    await _add_staging(factory, feed_b, "q1")

    await _add_export_run(factory, feed_a, "completed")
    await _add_export_run(factory, feed_b, "failed")

    resp = await client.get("/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"] == {"clients": 2, "feed_sources": 2,
                              "active_products": 3, "failed_last_exports": 1}
    by_name = {c["name"]: c for c in body["clients"]}
    feed_a_out = by_name["Acme"]["feed_sources"][0]
    assert feed_a_out["item_count"] == 2
    assert feed_a_out["last_export_status"] == "completed"
    assert feed_a_out["last_export_at"] is not None
    assert feed_a_out["source_format"] == "wide_tsv"
    assert feed_a_out["client_id"] == by_name["Acme"]["id"]
    feed_b_out = by_name["Zeta"]["feed_sources"][0]
    assert feed_b_out["item_count"] == 1
    assert feed_b_out["last_export_status"] == "failed"
    assert feed_b_out["last_run_status"] == "success"


async def test_summary_last_export_uses_latest_run(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_a = await _make_feed(factory, client, "Acme")
    await _add_export_run(factory, feed_a, "failed")
    await _add_export_run(factory, feed_a, "completed")
    body = (await client.get("/dashboard/summary")).json()
    assert body["counts"]["failed_last_exports"] == 0
    assert body["clients"][0]["feed_sources"][0]["last_export_status"] == "completed"
