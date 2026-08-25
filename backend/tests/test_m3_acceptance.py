import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Client, FeedSource, IngestionRun
from app.pipeline import LockRegistry, StepContext, StepResult, default_steps
from app.pipeline.runner import PipelineRunner
from registry.model import RegistryDocument


pytestmark = pytest.mark.asyncio

HAPPY_TSV = b"id\ttitle\tprice\n1\tRed Shirt\t19.99\n2\tBlue Hat\t9.50\n3\tGreen Pants\t25.00\n"
ROW_ERROR_TSV = (
    b"id\ttitle\tshipping(country:price)\tshipping(country:price)\n"
    b"1\tRed Shirt\tUS:6.49 USD\tUK:5.99:GBP\n"
    b"2\tBlue Hat\tDE:7.99 EUR\tFR:4.00 EUR\n"
)


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data
        self.calls: list[tuple[str, tuple[str, str] | None]] = []

    async def fetch(self, url, basic_auth=None, _client=None):
        self.calls.append((url, basic_auth))
        return self.data


class CaptureProductsStep:
    name = "capture_products"

    def __init__(self):
        self.captured: list[dict] | None = None

    async def execute(self, ctx: StepContext) -> StepResult:
        self.captured = list(ctx.run_state.products)
        return StepResult()


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_feed_source(session_factory, configuration):
    async with session_factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="tsv",
                source_url="http://test.local/feed.tsv",
                configuration=configuration,
            )
            session.add(feed_source)
            await session.flush()
            return feed_source.id


async def _get_run(factory, run_id):
    async with factory() as session:
        return await session.get(IngestionRun, run_id)


async def test_happy_path_tsv_ingest_end_to_end(session_factory):
    fs_id = await _seed_feed_source(
        session_factory, {"basic_auth": {"username": "u", "password": "p"}}
    )
    fetcher = StubFetcher(HAPPY_TSV)
    capture = CaptureProductsStep()
    steps = [*default_steps(fetcher, RegistryDocument(attributes={})), capture]
    runner = PipelineRunner(LockRegistry(), session_factory, steps)

    run_id = await runner.execute(fs_id)

    run = await _get_run(session_factory, run_id)
    assert run.status == "success"
    assert run.processed_count == 3
    assert run.failed_count == 0
    assert run.completed_at is not None
    assert run.statistics["row_errors"] == []
    assert capture.captured == [
        {"id": "1", "title": "Red Shirt", "price": "19.99"},
        {"id": "2", "title": "Blue Hat", "price": "9.50"},
        {"id": "3", "title": "Green Pants", "price": "25.00"},
    ]
    assert fetcher.calls == [("http://test.local/feed.tsv", ("u", "p"))]


async def test_row_errors_skipped_but_run_succeeds(session_factory):
    fs_id = await _seed_feed_source(session_factory, {})
    fetcher = StubFetcher(ROW_ERROR_TSV)
    capture = CaptureProductsStep()
    steps = [*default_steps(fetcher, RegistryDocument(attributes={})), capture]
    runner = PipelineRunner(LockRegistry(), session_factory, steps)

    run_id = await runner.execute(fs_id)

    run = await _get_run(session_factory, run_id)
    assert run.status == "success"
    assert run.processed_count == 1
    assert run.failed_count == 1
    assert run.statistics["row_errors"] == [
        {
            "line": 2,
            "message": "Column 'shipping' has 3 colon-separated parts but expected 2",
        }
    ]
    assert capture.captured == [
        {
            "id": "2",
            "title": "Blue Hat",
            "shipping": [
                {"country": "DE", "price": "7.99 EUR"},
                {"country": "FR", "price": "4.00 EUR"},
            ],
        }
    ]
