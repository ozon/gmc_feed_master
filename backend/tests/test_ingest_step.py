import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingest import FetchError, IngestReport, RowError, read_feed
from app.pipeline import IngestStep, RunState, StepContext, StepResult
from registry.model import RegistryDocument

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "feeds"


class StubFetcher:
    def __init__(self, data: bytes = b"", error: Exception | None = None):
        self.data = data
        self.error = error
        self.calls: list[tuple[str, tuple[str, str] | None]] = []

    async def fetch(self, url, basic_auth=None, _client=None):
        self.calls.append((url, basic_auth))
        if self.error is not None:
            raise self.error
        return self.data


class FakeSession:
    def __init__(self, feed_source):
        self._feed_source = feed_source

    async def get(self, model, pk):
        return self._feed_source

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSessionFactory:
    def __init__(self, feed_source):
        self._feed_source = feed_source

    def __call__(self):
        return FakeSession(self._feed_source)


def _feed_source(source_format="tsv", source_url="https://example.com/feed", configuration=None):
    return SimpleNamespace(
        source_format=source_format,
        source_url=source_url,
        configuration=configuration if configuration is not None else {},
    )


def _ctx(session_factory, run_state=None):
    return StepContext(
        feed_source_id=1,
        session_factory=session_factory,
        logger=logging.getLogger("test"),
        run_state=run_state if run_state is not None else RunState(),
    )


def _step(fetcher=None):
    return IngestStep(
        fetcher if fetcher is not None else StubFetcher(),
        RegistryDocument(attributes={}),
    )


class TestReadFeed:
    @pytest.mark.parametrize("source_format", ["tsv", "csv", "wide_tsv"])
    def test_dispatches_delimited(self, source_format):
        report = read_feed(b"id,title\n1,Red Shirt\n", source_format, RegistryDocument(attributes={}))
        assert isinstance(report, IngestReport)

    def test_dispatches_xml(self):
        report = read_feed(b"<rss><channel></channel></rss>", "xml", RegistryDocument(attributes={}))
        assert isinstance(report, IngestReport)

    def test_unsupported_format_raises(self):
        with pytest.raises(ValueError, match="unsupported source format"):
            read_feed(b"", "json", RegistryDocument(attributes={}))


class TestIngestStepHappyPath:
    @pytest.mark.asyncio
    async def test_tsv_populates_run_state_and_counts(self):
        data = b"id\ttitle\n1\tRed Shirt\n2\tBlue Hat\n"
        fetcher = StubFetcher(data=data)
        run_state = RunState()
        ctx = _ctx(FakeSessionFactory(_feed_source()), run_state)

        result = await _step(fetcher).execute(ctx)

        assert result.processed_count == 2
        assert result.failed_count == 0
        assert run_state.products == [
            {"id": "1", "title": "Red Shirt"},
            {"id": "2", "title": "Blue Hat"},
        ]
        assert fetcher.calls == [("https://example.com/feed", None)]

    @pytest.mark.asyncio
    async def test_xml_products_parsed(self):
        data = (_FIXTURES / "simple_rss.xml").read_bytes()
        fetcher = StubFetcher(data=data)
        run_state = RunState()
        ctx = _ctx(FakeSessionFactory(_feed_source(source_format="xml")), run_state)

        result = await _step(fetcher).execute(ctx)

        assert result.processed_count == 3
        assert result.failed_count == 0
        assert run_state.products[0] == {
            "id": "1",
            "title": "Red Shirt",
            "price": "19.99 USD",
            "link": "https://example.com/1",
        }

    @pytest.mark.asyncio
    async def test_basic_auth_passed_to_fetcher(self):
        fetcher = StubFetcher(data=b"id\n1\n")
        source = _feed_source(configuration={"basic_auth": {"username": "u", "password": "p"}})
        ctx = _ctx(FakeSessionFactory(source))

        await _step(fetcher).execute(ctx)

        assert fetcher.calls == [("https://example.com/feed", ("u", "p"))]


class TestIngestStepFailures:
    @pytest.mark.asyncio
    async def test_missing_feed_source_raises(self):
        with pytest.raises(LookupError, match="feed source"):
            await _step().execute(_ctx(FakeSessionFactory(None)))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("source_url", [None, ""])
    async def test_missing_source_url_raises(self, source_url):
        source = _feed_source(source_url=source_url)
        with pytest.raises(ValueError, match="source_url"):
            await _step().execute(_ctx(FakeSessionFactory(source)))

    @pytest.mark.asyncio
    async def test_fetch_error_propagates(self):
        fetcher = StubFetcher(error=FetchError("HTTP 500 from https://example.com/feed"))
        ctx = _ctx(FakeSessionFactory(_feed_source()))
        with pytest.raises(FetchError, match="500"):
            await _step(fetcher).execute(ctx)


class TestIngestStepRowErrors:
    @pytest.mark.asyncio
    async def test_row_errors_counted_and_statistics_truncated_to_100(self):
        header = "id\tshipping(country:price)\n"
        rows = "".join(f"{i}\tUS:6.49:extra\n" for i in range(1, 121))
        fetcher = StubFetcher(data=(header + rows).encode())
        run_state = RunState()
        ctx = _ctx(FakeSessionFactory(_feed_source()), run_state)

        result = await _step(fetcher).execute(ctx)

        assert result.processed_count == 0
        assert result.failed_count == 120
        assert run_state.products == []
        row_errors = result.statistics["row_errors"]
        assert len(row_errors) == 100
        assert row_errors[0] == {
            "line": 2,
            "message": "Column 'shipping' has 3 colon-separated parts but expected 2",
        }
        assert row_errors[99]["line"] == 101
        assert all(set(entry) == {"line", "message"} for entry in row_errors)

    @pytest.mark.asyncio
    async def test_row_errors_logged_as_warning(self, caplog):
        data = b"id\tshipping(country:price)\n1\tUS:6.49:extra\n"
        fetcher = StubFetcher(data=data)
        ctx = _ctx(FakeSessionFactory(_feed_source()))

        with caplog.at_level(logging.WARNING, logger="test"):
            result = await _step(fetcher).execute(ctx)

        assert result.failed_count == 1
        assert any("row error" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_no_row_errors_no_warning(self, caplog):
        fetcher = StubFetcher(data=b"id\n1\n")
        ctx = _ctx(FakeSessionFactory(_feed_source()))

        with caplog.at_level(logging.WARNING, logger="test"):
            await _step(fetcher).execute(ctx)

        assert not caplog.records

    @pytest.mark.asyncio
    async def test_empty_row_errors_statistics_present(self):
        fetcher = StubFetcher(data=b"id\n1\n")
        ctx = _ctx(FakeSessionFactory(_feed_source()))

        result = await _step(fetcher).execute(ctx)

        assert result.statistics["row_errors"] == []


class TestIngestStepContract:
    def test_name_is_ingest(self):
        assert _step().name == "ingest"

    def test_result_is_step_result(self):
        step = _step()
        assert isinstance(step, IngestStep)
        assert StepResult() == StepResult(processed_count=0, failed_count=0)
