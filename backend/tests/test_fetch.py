import httpx
import pytest

from app.ingest.fetch import FetchError, HttpFetcher


class TestFetchSuccess:
    @pytest.mark.asyncio
    async def test_returns_bytes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"hello world")

        transport = httpx.MockTransport(handler)
        fetcher = HttpFetcher()
        async with httpx.AsyncClient(transport=transport) as client:
            result = await fetcher.fetch("https://example.com/feed.xml", _client=client)

        assert result == b"hello world"


class TestFetchTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_fetch_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("read timed out")

        transport = httpx.MockTransport(handler)
        fetcher = HttpFetcher(timeout=1.0)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(FetchError, match="timeout"):
                await fetcher.fetch("https://example.com/slow", _client=client)


class TestFetchNon2xx:
    @pytest.mark.asyncio
    async def test_404_raises_fetch_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        transport = httpx.MockTransport(handler)
        fetcher = HttpFetcher()
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(FetchError, match="404"):
                await fetcher.fetch("https://example.com/missing", _client=client)

    @pytest.mark.asyncio
    async def test_500_raises_fetch_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        transport = httpx.MockTransport(handler)
        fetcher = HttpFetcher()
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(FetchError, match="500"):
                await fetcher.fetch("https://example.com/error", _client=client)


class TestFetchSizeLimit:
    @pytest.mark.asyncio
    async def test_exceeds_max_bytes_raises_fetch_error(self) -> None:
        payload = b"x" * 200

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=payload)

        transport = httpx.MockTransport(handler)
        fetcher = HttpFetcher(max_bytes=100)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(FetchError, match="size limit"):
                await fetcher.fetch("https://example.com/big", _client=client)


class TestFetchBasicAuth:
    @pytest.mark.asyncio
    async def test_auth_header_sent(self) -> None:
        captured_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, content=b"ok")

        transport = httpx.MockTransport(handler)
        fetcher = HttpFetcher()
        async with httpx.AsyncClient(transport=transport) as client:
            await fetcher.fetch(
                "https://example.com/auth",
                basic_auth=("user", "pass"),
                _client=client,
            )

        assert "authorization" in captured_headers
        assert captured_headers["authorization"].startswith("Basic ")
