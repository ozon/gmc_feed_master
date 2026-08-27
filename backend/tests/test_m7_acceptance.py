"""M7 acceptance gate — QC pipeline end-to-end."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun, ExportRun, QualityFinding
from app.models.staging import StagingProduct
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
    yield app, factory, engine
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_feed_source(app_factory):
    _, factory, _ = app_factory
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
                currency="USD",
                configuration={},
            )
            session.add(feed_source)
            await session.flush()
            return client.id, feed_source.id


async def test_end_to_end_qc_finds_issues(app_factory):
    _, factory, _ = app_factory
    _, feed_source_id = await _seed_feed_source(app_factory)

    async with factory() as session:
        async with session.begin():
            ingestion_run = IngestionRun(
                feed_source_id=feed_source_id,
                status="completed",
                processed_count=3,
                failed_count=0,
            )
            session.add(ingestion_run)
            await session.flush()

            products = [
                {
                    "id": "SKU-1",
                    "title": "Good Product",
                    "description": "A product",
                    "link": "http://example.com/1",
                    "image_link": "http://example.com/1.jpg",
                    "availability": "in_stock",
                    "price": "10 USD",
                    "condition": "new",
                    "brand": "Acme",
                    "gtin": "0012345678905",
                },
                {
                    "id": "SKU-2",
                    "description": "Missing title",
                    "link": "http://example.com/2",
                    "image_link": "http://example.com/2.jpg",
                    "availability": "in_stock",
                    "price": "20 USD",
                    "condition": "new",
                },
                {
                    "id": "SKU-3",
                    "title": "Bad Enum",
                    "description": "Product",
                    "link": "http://example.com/3",
                    "image_link": "http://example.com/3.jpg",
                    "availability": "invalid_status",
                    "price": "30 EUR",
                    "condition": "new",
                    "brand": "Widget",
                },
            ]

            for product in products:
                row = StagingProduct(
                    feed_source_id=feed_source_id,
                    ingestion_run_id=ingestion_run.id,
                    product_id=product["id"],
                    content_hash="abc",
                    config_hash="def",
                    status="active",
                    raw_data=product,
                    processed_data=product,
                )
                session.add(row)

            ingestion_run_id = ingestion_run.id

    from registry.loader import load_registry
    from app.clock import SystemClock
    from app.qc.engine import QcContext, run_engine
    from app.qc.rules import (
        BaselineRequired, BrandRequired, GtinMpn, EnumValues,
        ConditionalRequired, DateFormat, LengthLimits, CardinalityRule,
        CurrencyConsistency, ImageRequirements, VariantConsistency, VolumeDrop,
    )
    from app.qc.persistence import persist_findings

    async with factory() as session:
        feed_source = await session.get(FeedSource, feed_source_id)
        currency = feed_source.currency
        volume_drop_threshold_pct = feed_source.volume_drop_threshold_pct

    registry = load_registry()
    clock = SystemClock()

    product_dicts = []
    product_ids = []
    async with factory() as session:
        result = await session.execute(
            select(StagingProduct).where(
                StagingProduct.feed_source_id == feed_source_id,
                StagingProduct.status == "active",
            )
        )
        for row in result.scalars().all():
            product_dicts.append(row.processed_data or row.raw_data)
            product_ids.append(row.product_id)

    qc_ctx = QcContext(
        feed_source_id=feed_source_id,
        currency=currency,
        volume_drop_threshold_pct=volume_drop_threshold_pct,
        registry=registry,
        clock=clock,
        image_probe=None,
        previous_export_run=None,
    )

    per_product_rules = [
        BaselineRequired(), BrandRequired(), GtinMpn(), EnumValues(),
        ConditionalRequired(), DateFormat(), LengthLimits(), CardinalityRule(),
        CurrencyConsistency(), ImageRequirements(),
    ]
    cross_product_rules = [VariantConsistency(), VolumeDrop()]

    findings = await run_engine(product_dicts, product_ids, qc_ctx, per_product_rules, cross_product_rules)

    await persist_findings(
        lambda: factory(),
        feed_source_id,
        ingestion_run_id,
        findings,
        len(product_dicts),
    )

    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/quality-findings")
    assert resp.status_code == 200
    data = resp.json()

    assert data["counts"]["critical"] >= 1
    assert data["counts"]["warning"] >= 1
    assert len(data["findings"]) >= 2

    async with factory() as session:
        result = await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source_id)
        )
        export_runs = list(result.scalars().all())
        assert len(export_runs) == 1
        assert export_runs[0].status == "pending_export"
        assert export_runs[0].product_count == 3
        assert export_runs[0].critical_finding_count >= 1
