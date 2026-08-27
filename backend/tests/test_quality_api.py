import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun, ExportRun, ExportVersion, QualityFinding
from app.models.session import Session
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
            await session.execute(delete(QualityFinding))
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


async def _seed_feed_source(app_factory):
    _, factory = app_factory
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="tsv",
                source_url="http://test.local/feed.tsv",
                configuration={},
            )
            session.add(feed_source)
            await session.flush()
            return client.id, feed_source.id


async def test_404_for_missing_feed_source(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/feed-sources/9999/quality-findings")
    assert resp.status_code == 404


async def test_empty_result_when_no_qc_run(app_factory):
    _, feed_source_id = await _seed_feed_source(app_factory)
    client = await logged_in_client(app_factory)
    resp = await client.get(f"/feed-sources/{feed_source_id}/quality-findings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"] == {"critical": 0, "warning": 0, "info": 0}
    assert data["findings"] == []
    assert data["ingestion_run_id"] is None


async def test_returns_findings(app_factory):
    _, factory = app_factory
    _, feed_source_id = await _seed_feed_source(app_factory)

    async with factory() as session:
        async with session.begin():
            ingestion_run = IngestionRun(feed_source_id=feed_source_id, status="completed")
            session.add(ingestion_run)
            await session.flush()

            export_run = ExportRun(
                feed_source_id=feed_source_id,
                ingestion_run_id=ingestion_run.id,
                status="completed",
                product_count=5,
                critical_finding_count=1,
                warning_finding_count=2,
                info_finding_count=0,
            )
            session.add(export_run)
            await session.flush()

            finding = QualityFinding(
                feed_source_id=feed_source_id,
                ingestion_run_id=ingestion_run.id,
                product_id="SKU-1",
                severity="critical",
                code="enum_values",
                field="availability",
                message="invalid value",
                details={},
            )
            session.add(finding)

    client = await logged_in_client(app_factory)
    resp = await client.get(f"/feed-sources/{feed_source_id}/quality-findings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"]["critical"] == 1
    assert data["counts"]["warning"] == 2
    assert data["counts"]["info"] == 0
    assert len(data["findings"]) == 1
    assert data["findings"][0]["code"] == "enum_values"
    assert data["findings"][0]["severity"] == "critical"
    assert data["findings"][0]["field"] == "availability"
    assert data["findings"][0]["product_id"] == "SKU-1"
