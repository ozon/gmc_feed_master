### Task 7: Image Probe — Pillow + Cache

**Goal:** Implement `ImageProbe` with httpx fetch, Pillow dimension parsing, and DB-backed cache.

**Files:**
- Create: `backend/app/qc/image_probe.py`
- Create: `backend/tests/test_image_probe.py`

#### Steps

- [ ] **Step 1: Create image probe implementation**

```python
# backend/app/qc/image_probe.py
from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Protocol

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.image_dimension import ImageDimension
from .constants import IMAGE_FETCH_CAP_BYTES, IMAGE_CONCURRENCY

logger = logging.getLogger(__name__)


class ImageProbeImpl:
    def __init__(self, session_factory, client: httpx.AsyncClient) -> None:
        self._session_factory = session_factory
        self._client = client
        self._semaphore = asyncio.Semaphore(IMAGE_CONCURRENCY)

    async def probe(self, url: str) -> tuple[int | None, int | None, str | None]:
        async with self._session_factory() as session:
            cached = await session.execute(
                select(ImageDimension).where(ImageDimension.url == url)
            )
            row = cached.scalar_one_or_none()
            if row is not None:
                if row.fetch_error:
                    return None, None, row.fetch_error
                return row.width, row.height, None

        async with self._semaphore:
            try:
                response = await self._client.get(
                    url,
                    headers={"User-Agent": "GMC-Feed-Engine/1.0"},
                    follow_redirects=True,
                    timeout=30.0,
                )
                response.raise_for_status()

                content_length = int(response.headers.get("content-length", 0))
                if content_length > IMAGE_FETCH_CAP_BYTES:
                    error = f"image too large: {content_length} bytes"
                    await self._cache_error(url, error)
                    return None, None, error

                body = response.content[:IMAGE_FETCH_CAP_BYTES]
                img = Image.open(BytesIO(body))
                width, height = img.size

                await self._cache_dimensions(url, width, height)
                return width, height, None

            except httpx.HTTPStatusError as e:
                error = f"HTTP {e.response.status_code}"
                await self._cache_error(url, error)
                return None, None, error
            except Exception as e:
                error = str(e)[:500]
                await self._cache_error(url, error)
                return None, None, error

    async def _cache_dimensions(self, url: str, width: int, height: int) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                row = ImageDimension(url=url, width=width, height=height)
                session.add(row)

    async def _cache_error(self, url: str, error: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                row = ImageDimension(url=url, fetch_error=error)
                session.add(row)
```

- [ ] **Step 2: Write image probe tests**

```python
# backend/tests/test_image_probe.py
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock
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
    from PIL import Image
    from io import BytesIO
    buf = BytesIO()
    Image.new("RGB", (width, height)).save(buf, format="JPEG")
    return buf.getvalue()


async def test_probe_cache_hit():
    session_factory = AsyncMock()
    mock_session = AsyncMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    cached = ImageDimension(url="http://example.com/img.jpg", width=800, height=600)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = cached
    mock_session.execute = AsyncMock(return_value=mock_result)

    client = httpx.AsyncClient()
    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/img.jpg")
    assert width == 800
    assert height == 600
    assert error is None


async def test_probe_fetch_success():
    jpeg = _make_jpeg_bytes(200, 150)
    transport = FakeTransport({
        "http://example.com/img.jpg": (200, {"content-length": str(len(jpeg))}, jpeg),
    })
    client = httpx.AsyncClient(transport=transport)

    session_factory = AsyncMock()
    mock_session = AsyncMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    # Cache miss
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/img.jpg")
    assert width == 200
    assert height == 150
    assert error is None


async def test_probe_http_error():
    transport = FakeTransport({})
    client = httpx.AsyncClient(transport=transport)

    session_factory = AsyncMock()
    mock_session = AsyncMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    probe = ImageProbeImpl(session_factory, client)
    width, height, error = await probe.probe("http://example.com/missing.jpg")
    assert width is None
    assert height is None
    assert error is not None
```

- [ ] **Step 3: Run image probe tests**

Run: `cd backend && python -m pytest tests/test_image_probe.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/qc/image_probe.py backend/tests/test_image_probe.py
git commit -m "feat(qc): image probe with Pillow and DB cache"
```

---

