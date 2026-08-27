from __future__ import annotations

import asyncio
import logging
from io import BytesIO

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
