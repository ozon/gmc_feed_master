import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock
from PIL import Image
from io import BytesIO

from app.qc.image_probe import ImageProbeImpl
from app.models.image_dimension import ImageDimension

pytestmark = pytest.mark.asyncio


class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses):
        self._responses = responses

    async def handle_async_request(self, request):
        url = str(request.url)
        if url in self._responses:
            status, headers, body = self._responses[url]
            return httpx.Response(status, headers=headers, content=body)
        return httpx.Response(404)


def _make_jpeg_bytes(width=100, height=100):
    buf = BytesIO()
    Image.new("RGB", (width, height)).save(buf, format="JPEG")
    return buf.getvalue()


def _mock_session_factory(mock_session):
    factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = ctx
    return factory


def _make_session_mock(execute_return=None):
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = execute_return
    session.execute = AsyncMock(return_value=mock_result)

    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=session)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value = begin_cm

    session.add = MagicMock()
    return session


async def test_probe_cache_hit():
    cached = ImageDimension(url="http://example.com/img.jpg", width=800, height=600)
    mock_session = _make_session_mock(execute_return=cached)

    session_factory = _mock_session_factory(mock_session)
    client = httpx.AsyncClient(transport=FakeTransport({}))

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/img.jpg")
    assert width == 800
    assert height == 600
    assert error is None


async def test_probe_cache_hit_error():
    cached = ImageDimension(url="http://example.com/img.jpg", fetch_error="HTTP 500")
    mock_session = _make_session_mock(execute_return=cached)

    session_factory = _mock_session_factory(mock_session)
    client = httpx.AsyncClient(transport=FakeTransport({}))

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/img.jpg")
    assert width is None
    assert height is None
    assert error == "HTTP 500"


async def test_probe_fetch_success():
    jpeg = _make_jpeg_bytes(200, 150)
    transport = FakeTransport({
        "http://example.com/img.jpg": (200, {"content-length": str(len(jpeg))}, jpeg),
    })
    client = httpx.AsyncClient(transport=transport)

    mock_session = _make_session_mock(execute_return=None)
    session_factory = _mock_session_factory(mock_session)

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/img.jpg")
    assert width == 200
    assert height == 150
    assert error is None


async def test_probe_http_error():
    transport = FakeTransport({})
    client = httpx.AsyncClient(transport=transport)

    mock_session = _make_session_mock(execute_return=None)
    session_factory = _mock_session_factory(mock_session)

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/missing.jpg")
    assert width is None
    assert height is None
    assert error is not None
    assert "404" in error


async def test_probe_content_too_large():
    big_body = b"\x00" * (11 * 1024 * 1024)  # 11 MB
    transport = FakeTransport({
        "http://example.com/big.jpg": (200, {"content-length": str(len(big_body))}, big_body),
    })
    client = httpx.AsyncClient(transport=transport)

    mock_session = _make_session_mock(execute_return=None)
    session_factory = _mock_session_factory(mock_session)

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/big.jpg")
    assert width is None
    assert height is None
    assert error is not None
    assert "too large" in error


async def test_probe_corrupt_image():
    transport = FakeTransport({
        "http://example.com/corrupt.jpg": (200, {"content-length": "5"}, b"not an image"),
    })
    client = httpx.AsyncClient(transport=transport)

    mock_session = _make_session_mock(execute_return=None)
    session_factory = _mock_session_factory(mock_session)

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/corrupt.jpg")
    assert width is None
    assert height is None
    assert error is not None
