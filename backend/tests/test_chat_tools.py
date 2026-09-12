
import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.access import CurrentUser
from app.chat.tools import execute_tool
from app.models import (
    Client,
    ExportRun,
    FeedSource,
    IngestionRun,
    QualityFinding,
    StagingProduct,
)
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        async with session.begin():
            await session.execute(delete(QualityFinding))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(StagingProduct))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")

    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seed(db):
    factory = db
    async with factory() as session, session.begin():
        client1 = Client(name="Client A")
        client2 = Client(name="Client B")
        session.add_all([client1, client2])
        await session.flush()

        fs1 = FeedSource(
            client_id=client1.id,
            name="Feed A",
            source_format="tsv",
            source_url="http://test.local/feed_a.tsv",
            configuration={},
        )
        fs2 = FeedSource(
            client_id=client2.id,
            name="Feed B",
            source_format="xml",
            source_url="http://test.local/feed_b.xml",
            configuration={},
        )
        session.add_all([fs1, fs2])
        await session.flush()

        ingestion = IngestionRun(feed_source_id=fs1.id, status="completed")
        session.add(ingestion)
        await session.flush()

        return client1.id, client2.id, fs1.id, fs2.id, ingestion.id


@pytest_asyncio.fixture
async def client_user(seed, db):
    factory = db
    async with factory() as session, session.begin():
        from app.models.user_client import UserClient

        user = User(
            username="client_user",
            password_hash="fake",
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        session.add(UserClient(user_id=user.id, client_id=seed[0]))
        await session.flush()
    return CurrentUser(
        username="client_user",
        role="user",
        is_active=True,
        client_ids=frozenset({seed[0]}),
    )


@pytest_asyncio.fixture
async def admin_user():
    return CurrentUser(
        username="admin",
        role="admin",
        is_active=True,
        client_ids=None,
    )


async def test_list_feed_sources_client_user(seed, db, client_user):
    factory = db
    async with factory() as session:
        result = await execute_tool(session, client_user, "list_feed_sources", {})
    assert len(result["feed_sources"]) == 1
    assert result["feed_sources"][0]["name"] == "Feed A"


async def test_list_feed_sources_admin(seed, db, admin_user):
    factory = db
    async with factory() as session:
        result = await execute_tool(session, admin_user, "list_feed_sources", {})
    assert len(result["feed_sources"]) == 2


async def test_query_staging_products_search(seed, db, client_user):
    factory = db
    async with factory() as session, session.begin():
        ingestion_id = seed[4]
        sp1 = StagingProduct(
            feed_source_id=seed[2],
            ingestion_run_id=ingestion_id,
            product_id="SKU-1",
            content_hash="h1",
            config_hash="c1",
            raw_data={"title": "Gadget Alpha"},
        )
        sp2 = StagingProduct(
            feed_source_id=seed[2],
            ingestion_run_id=ingestion_id,
            product_id="SKU-2",
            content_hash="h2",
            config_hash="c2",
            raw_data={"title": "Widget Beta"},
        )
        session.add_all([sp1, sp2])
    async with factory() as session:
        result = await execute_tool(
            session, client_user, "query_staging_products", {"search": "Gadget"}
        )
    assert len(result["products"]) == 1
    assert result["products"][0]["product_id"] == "SKU-1"


async def test_query_staging_products_title_truncated(seed, db, client_user):
    factory = db
    long_title = "x" * 600
    async with factory() as session, session.begin():
        sp = StagingProduct(
            feed_source_id=seed[2],
            ingestion_run_id=seed[4],
            product_id="SKU-LONG",
            content_hash="h3",
            config_hash="c3",
            raw_data={"title": long_title},
        )
        session.add(sp)
    async with factory() as session:
        result = await execute_tool(
            session, client_user, "query_staging_products", {"search": "x"}
        )
    assert len(result["products"]) == 1
    title = result["products"][0]["title"]
    assert len(title) == 501
    assert title.endswith("\u2026")


async def test_query_qc_findings_severity_filter(seed, db, client_user):
    factory = db
    async with factory() as session, session.begin():
        ingestion_id = seed[4]
        f1 = QualityFinding(
            feed_source_id=seed[2],
            ingestion_run_id=ingestion_id,
            product_id="SKU-1",
            severity="critical",
            code="enum_values",
            field="availability",
            message="invalid value",
            details={},
        )
        f2 = QualityFinding(
            feed_source_id=seed[2],
            ingestion_run_id=ingestion_id,
            product_id="SKU-2",
            severity="warning",
            code="missing_field",
            field="description",
            message="description is empty",
            details={},
        )
        session.add_all([f1, f2])
    async with factory() as session:
        result = await execute_tool(
            session, client_user, "query_qc_findings", {"severity": "critical"}
        )
    assert len(result["findings"]) == 1
    assert result["findings"][0]["severity"] == "critical"


async def test_query_export_runs(seed, db, client_user):
    factory = db
    async with factory() as session, session.begin():
        er = ExportRun(
            feed_source_id=seed[2],
            ingestion_run_id=seed[4],
            status="completed",
            product_count=10,
            critical_finding_count=1,
            warning_finding_count=2,
            info_finding_count=3,
        )
        session.add(er)
    async with factory() as session:
        result = await execute_tool(
            session, client_user, "query_export_runs", {}
        )
    assert len(result["export_runs"]) == 1
    run = result["export_runs"][0]
    assert run["product_count"] == 10
    assert run["critical"] == 1
    assert run["warning"] == 2
    assert run["info"] == 3
    assert run["started_at"] is not None


async def test_cross_client_feed_source_rejected(seed, db, client_user):
    factory = db
    async with factory() as session:
        result = await execute_tool(
            session,
            client_user,
            "query_staging_products",
            {"feed_source_id": seed[3]},
        )
    assert result == {"error": "feed source not found"}


async def test_cross_client_findings_rejected(seed, db, client_user):
    factory = db
    async with factory() as session:
        result = await execute_tool(
            session,
            client_user,
            "query_qc_findings",
            {"feed_source_id": seed[3]},
        )
    assert result == {"error": "feed source not found"}


async def test_cross_client_export_rejected(seed, db, client_user):
    factory = db
    async with factory() as session:
        result = await execute_tool(
            session,
            client_user,
            "query_export_runs",
            {"feed_source_id": seed[3]},
        )
    assert result == {"error": "feed source not found"}


async def test_unknown_tool(seed, db, client_user):
    factory = db
    async with factory() as session:
        result = await execute_tool(session, client_user, "bogus_tool", {})
    assert "error" in result
    assert "unknown tool" in result["error"]


async def test_invalid_arguments(seed, db, client_user):
    factory = db
    async with factory() as session:
        result = await execute_tool(
            session, client_user, "query_staging_products", "not-a-dict"
        )
    assert "error" in result


async def test_limit_over_50_rejected(seed, db, client_user):
    factory = db
    async with factory() as session:
        result = await execute_tool(
            session, client_user, "query_staging_products", {"limit": 100}
        )
    assert "error" in result
