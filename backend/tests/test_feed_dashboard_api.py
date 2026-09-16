from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
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


async def _make_feed(factory, http_client, name):
    created = (await http_client.post("/clients", json={"name": name})).json()
    feed = (
        await http_client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": f"{name}-feed", "source_format": "wide_tsv"},
        )
    ).json()
    return created["id"], feed["id"]


async def _add_run(factory, feed_id, status="success", processed=100, statistics=None,
                   started_days_ago=0, duration_s=None):
    start = datetime.now(timezone.utc) - timedelta(days=started_days_ago)
    async with factory() as session, session.begin():
        session.add(IngestionRun(
                feed_source_id=feed_id,
                status=status,
                started_at=start,
                completed_at=(start + timedelta(seconds=duration_s)) if duration_s else None,
                processed_count=processed,
                statistics=statistics or {},
            ))


async def _add_export_run(factory, feed_id, product_count, started_days_ago=0):
    async with factory() as session, session.begin():
        session.add(ExportRun(
            feed_source_id=feed_id,
            status="pending_export",
            product_count=product_count,
            started_at=datetime.now(timezone.utc) - timedelta(days=started_days_ago),
        ))


async def test_dashboard_requires_auth(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.get("/feed-sources/1/dashboard")).status_code == 401


async def test_dashboard_404_unknown_feed(app_factory):
    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/999999/dashboard")).status_code == 404


async def test_dashboard_empty_feed(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")
    resp = await client.get(f"/feed-sources/{feed_id}/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kpi"] == {"raw_items": 0, "valid_items": 0, "excluded_items": 0,
                           "last_duration_s": None, "readiness_rate": 1.0}
    assert body["volume_trend"] == []
    assert body["stage_funnel"] == []
    assert body["quality"] == {"critical": 0, "warning": 0, "info": 0, "readiness_rate": 1.0}
    assert body["recent_runs"] == []


async def test_dashboard_aggregates_run_statistics(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")

    # Runner-shaped statistics: row_errors at top level (IngestStep), mapping.applied
    # is the honest ingested count; processed_count accumulates across steps.
    stats = {
        "row_errors": [{"line": 3, "message": "bad row"}],
        "mapping": {"applied": 100, "dropped_unmapped_fields": 4, "shape_mismatches": 0},
        "staging": {"enqueue": 96, "failed": 2},
        "plugins": {"processed": 94, "dropped": 2, "errored": 0},
        "qc": {"products": 94, "critical": 3, "warning": 12, "info": 40},
        "export": {"products": 90, "version": 7, "deduplicated": 0},
    }
    await _add_run(factory, feed_id, processed=100, statistics=stats,
                   started_days_ago=0, duration_s=42)
    async with factory() as session, session.begin():
        run = (await session.execute(
            select(IngestionRun)
            .where(IngestionRun.feed_source_id == feed_id)
        )).scalars().first()
        session.add(ExportRun(
            feed_source_id=feed_id,
            ingestion_run_id=run.id,
            status="pending_export",
            product_count=90,
            critical_finding_count=3,
            warning_finding_count=12,
            info_finding_count=40,
            started_at=datetime.now(timezone.utc),
        ))
        for pid in ("a", "b", "c"):
            session.add(StagingProduct(
                feed_source_id=feed_id,
                ingestion_run_id=run.id,
                product_id=pid,
                content_hash="h",
                config_hash="c",
                status="active",
                excluded=False,
                raw_data={"id": pid},
            ))
        session.add(StagingProduct(
            feed_source_id=feed_id,
            ingestion_run_id=run.id,
            product_id="x",
            content_hash="h",
            config_hash="c",
            status="active",
            excluded=True,
            raw_data={"id": "x"},
        ))

    body = (await client.get(f"/feed-sources/{feed_id}/dashboard")).json()
    kpi = body["kpi"]
    assert kpi["raw_items"] == 100
    assert kpi["valid_items"] == 3
    assert kpi["excluded_items"] == 1
    assert kpi["last_duration_s"] == 42.0
    assert abs(kpi["readiness_rate"] - (1 - 3 / 90)) < 1e-9
    assert body["quality"] == {"critical": 3, "warning": 12, "info": 40,
                               "readiness_rate": 1 - 3 / 90}

    funnel = {row["stage"]: row for row in body["stage_funnel"]}
    assert [row["stage"] for row in body["stage_funnel"]] == [
        "ingest", "mapping", "staging", "run_plugins", "quality_check", "export",
    ]
    assert funnel["ingest"]["passed"] == 100
    assert funnel["ingest"]["dropped"] == 1  # top-level row_errors length
    assert funnel["mapping"]["dropped"] == 4
    assert funnel["staging"]["dropped"] == 2
    assert funnel["run_plugins"]["dropped"] == 2
    assert funnel["run_plugins"]["passed"] == 100 - 1 - 4 - 2  # cumulative
    assert funnel["quality_check"]["passed"] == 100 - 1 - 4 - 2 - 2
    assert funnel["quality_check"]["dropped"] == 0
    assert funnel["export"]["passed"] == 90

    assert len(body["recent_runs"]) == 1
    assert body["recent_runs"][0]["duration_s"] == 42.0

    assert len(body["volume_trend"]) == 1
    today = datetime.now(timezone.utc).date()
    assert body["volume_trend"][0]["date"] == str(today)
    assert body["volume_trend"][0]["raw"] == 100
    assert body["volume_trend"][0]["exportable"] == 90


async def test_dashboard_readiness_zero_products(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")
    async with factory() as session, session.begin():
        session.add(ExportRun(
            feed_source_id=feed_id,
            status="pending_export",
            product_count=0,
            started_at=datetime.now(timezone.utc),
        ))
    body = (await client.get(f"/feed-sources/{feed_id}/dashboard")).json()
    assert body["kpi"]["readiness_rate"] == 1.0


async def test_dashboard_raw_items_falls_back_to_processed_count(app_factory):
    # Legacy run with empty statistics: raw_items falls back to processed_count.
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")
    await _add_run(factory, feed_id, processed=37, statistics={})
    body = (await client.get(f"/feed-sources/{feed_id}/dashboard")).json()
    assert body["kpi"]["raw_items"] == 37
    assert body["stage_funnel"] == []  # no statistics → no funnel
    assert body["volume_trend"][0]["raw"] == 37


async def test_dashboard_raw_items_ignores_accumulated_processed(app_factory):
    # processed_count accumulates across steps (3-4x ingested); mapping.applied wins.
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")
    stats = {"mapping": {"applied": 100, "dropped_unmapped_fields": 0}}
    await _add_run(factory, feed_id, processed=394, statistics=stats)
    body = (await client.get(f"/feed-sources/{feed_id}/dashboard")).json()
    assert body["kpi"]["raw_items"] == 100
    funnel = {row["stage"]: row for row in body["stage_funnel"]}
    assert funnel["ingest"]["passed"] == 100
    assert body["volume_trend"][0]["raw"] == 100


async def test_dashboard_trend_not_capped_at_30_export_runs(app_factory):
    # A feed exporting >1x/day must not lose export data to a row cap:
    # 35 runs over 3 days (12/day) → every day keeps exportable=5.
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")
    stats = {"mapping": {"applied": 10}}
    for day in (0, 1, 2):
        for _ in range(12):
            await _add_export_run(factory, feed_id, product_count=5, started_days_ago=day)
        await _add_run(factory, feed_id, processed=10, statistics=stats, started_days_ago=day)
    body = (await client.get(f"/feed-sources/{feed_id}/dashboard")).json()
    assert len(body["volume_trend"]) == 3
    for row in body["volume_trend"]:
        assert row["raw"] == 10
        assert row["exportable"] == 5


async def test_dashboard_denies_cross_tenant_access(app_factory):
    app, factory = app_factory
    admin = await logged_in_client(app_factory)
    _, other_feed_id = await _make_feed(factory, admin, "Other Tenant")
    own_client_id, own_feed_id = await _make_feed(factory, admin, "Own Tenant")

    from app.models.user import User as UserModel
    from app.models.user_client import UserClient
    from app.security.passwords import hash_password
    async with factory() as session, session.begin():
        restricted = UserModel(
            username="bob", password_hash=hash_password("bob-pass"), role="user",
        )
        session.add(restricted)
        await session.flush()
        session.add(UserClient(user_id=restricted.id, client_id=own_client_id))

    restricted_client = AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver",
    )
    resp = await restricted_client.post(
        "/auth/login", json={"username": "bob", "password": "bob-pass"}
    )
    assert resp.status_code == 200
    assert (await restricted_client.get(f"/feed-sources/{other_feed_id}/dashboard")).status_code == 404
    assert (await restricted_client.get(f"/feed-sources/{own_feed_id}/dashboard")).status_code == 200
