import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.pipeline import LockRegistry, StepContext, StepResult, default_steps
from app.pipeline.runner import PipelineRunner
from registry.loader import load_registry


pytestmark = pytest.mark.asyncio

FEED_TSV = (
    b"sku\ttitle\tean\tmargin\n"
    b"A1\tRed Shirt\t1234567890123\t10\n"
    b"A2\tBlue Hat\t9876543210987\t20\n"
)


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data

    async def fetch(self, url, basic_auth=None, _client=None):
        return self.data


class CaptureProductsStep:
    name = "capture_products"

    def __init__(self):
        self.captured: list[dict] | None = None

    async def execute(self, ctx: StepContext) -> StepResult:
        self.captured = list(ctx.run_state.products)
        return StepResult()


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
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


async def _seed_feed_source(factory):
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
            return feed_source.id


async def _get_run(factory, run_id):
    async with factory() as session:
        return await session.get(IngestionRun, run_id)


async def _get_field_mapping(factory, feed_source_id):
    async with factory() as session:
        feed_source = await session.get(FeedSource, feed_source_id)
        return feed_source.field_mapping


def _build_runner(factory, capture):
    fetcher = StubFetcher(FEED_TSV)
    steps = [*default_steps(fetcher, load_registry()), capture]
    return PipelineRunner(LockRegistry(), factory, steps)


async def test_field_mapping_end_to_end(app_factory):
    _, factory = app_factory
    fs_id = await _seed_feed_source(factory)

    capture = CaptureProductsStep()
    runner = _build_runner(factory, capture)
    run_id = await runner.execute(fs_id)

    run = await _get_run(factory, run_id)
    assert run.status == "success"

    assert capture.captured == [
        {"id": "A1", "title": "Red Shirt", "gtin": ["1234567890123"]},
        {"id": "A2", "title": "Blue Hat", "gtin": ["9876543210987"]},
    ]
    for product in capture.captured:
        assert "margin" not in product

    doc = await _get_field_mapping(factory, fs_id)
    assert doc["auto_mapped"] is True
    assert [field["name"] for field in doc["source_fields"]] == [
        "sku",
        "title",
        "ean",
        "margin",
    ]
    assert doc["mappings"] == {
        "sku": {"target": "id", "origin": "synonym"},
        "title": {"target": "title", "origin": "auto"},
        "ean": {"target": "gtin", "origin": "synonym"},
    }

    client = await logged_in_client(app_factory)
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {
                "sku": {"target": "id"},
                "title": {"target": "title"},
                "ean": {"target": "gtin"},
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json()["mappings"] == {
        "sku": {"target": "id", "origin": "manual"},
        "title": {"target": "title", "origin": "manual"},
        "ean": {"target": "gtin", "origin": "manual"},
    }

    rerun_capture = CaptureProductsStep()
    rerun_runner = _build_runner(factory, rerun_capture)
    rerun_id = await rerun_runner.execute(fs_id)

    rerun = await _get_run(factory, rerun_id)
    assert rerun.status == "success"
    assert rerun_capture.captured == []

    doc = await _get_field_mapping(factory, fs_id)
    assert doc["auto_mapped"] is True
    assert [field["name"] for field in doc["source_fields"]] == [
        "sku",
        "title",
        "ean",
        "margin",
    ]
    assert doc["mappings"] == {
        "sku": {"target": "id", "origin": "manual"},
        "title": {"target": "title", "origin": "manual"},
        "ean": {"target": "gtin", "origin": "manual"},
    }
