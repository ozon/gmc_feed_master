from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.model import RegistryDocument

from ..clock import Clock
from ..models.client import Client
from ..models.export import ExportRun, ExportVersion
from ..models.feed_source import FeedSource
from .renderer import ChannelMetadata, render_feed
from .store import ExportFileStore

logger = logging.getLogger(__name__)


def generate_export_token() -> str:
    return secrets.token_urlsafe(32)


def channel_metadata_for(
    feed_source: FeedSource, client_name: str, public_base_url: str
) -> ChannelMetadata:
    configuration = feed_source.configuration or {}
    return ChannelMetadata(
        title=configuration.get("channel_title") or feed_source.name,
        link=configuration.get("channel_link") or public_base_url,
        description=configuration.get("channel_description") or client_name,
    )


@dataclass(frozen=True)
class ExportOutcome:
    version_number: int
    product_count: int
    deduplicated: bool


class ExportService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        store: ExportFileStore,
        clock: Clock,
        public_base_url: str,
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._clock = clock
        self._public_base_url = public_base_url

    async def export_for_run(
        self,
        feed_source_id: int,
        ingestion_run_id: int,
        products: Sequence[dict[str, Any]],
        registry: RegistryDocument,
    ) -> ExportOutcome:
        async with self._session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, feed_source_id)
                if feed_source is None:
                    raise LookupError(f"feed source {feed_source_id} not found")
                client = await session.get(Client, feed_source.client_id)
                client_name = client.name if client is not None else ""
                retention = feed_source.history_retention_count

        try:
            channel = channel_metadata_for(feed_source, client_name, self._public_base_url)
            data = render_feed(products, registry, channel)
            file_hash = hashlib.sha256(data).hexdigest()
        except Exception:
            await self._mark_run_failed(feed_source_id, ingestion_run_id)
            raise

        deduplicated = False
        version_number: int | None = None

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    locked = (
                        await session.execute(
                            select(FeedSource)
                            .where(FeedSource.id == feed_source_id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if locked is None:
                        raise LookupError(f"feed source {feed_source_id} not found")

                    latest = (
                        await session.execute(
                            select(ExportVersion)
                            .where(ExportVersion.feed_source_id == feed_source_id)
                            .order_by(ExportVersion.version_number.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    run = (
                        await session.execute(
                            select(ExportRun).where(
                                ExportRun.feed_source_id == feed_source_id,
                                ExportRun.ingestion_run_id == ingestion_run_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if run is None:
                        raise LookupError(
                            f"export run for ingestion run {ingestion_run_id} not found"
                        )

                    if latest is not None and latest.file_hash == file_hash:
                        deduplicated = True
                        version_number = latest.version_number
                        run.export_version_id = latest.id
                    else:
                        version_number = (latest.version_number + 1) if latest is not None else 1
                        self._store.write_version(feed_source_id, version_number, data)
                        new_version = ExportVersion(
                            feed_source_id=feed_source_id,
                            export_run_id=run.id,
                            version_number=version_number,
                            file_hash=file_hash,
                            product_count=len(products),
                            source="run",
                        )
                        session.add(new_version)
                        await session.flush()
                        run.export_version_id = new_version.id
                    run.status = "completed"
                    run.completed_at = self._clock.now()
        except Exception:
            if not deduplicated and version_number is not None:
                self._store.delete_version_file(feed_source_id, version_number)
            await self._mark_run_failed(feed_source_id, ingestion_run_id)
            raise

        try:
            if not (deduplicated and self._store.published_exists(feed_source_id)):
                self._store.publish(feed_source_id, data)
        except Exception:
            await self._mark_run_failed(feed_source_id, ingestion_run_id)
            raise

        if not deduplicated:
            await self._prune_retention(feed_source_id, retention)

        return ExportOutcome(
            version_number=version_number,
            product_count=len(products),
            deduplicated=deduplicated,
        )

    async def list_versions(self, feed_source_id: int) -> list[ExportVersion]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ExportVersion)
                .where(ExportVersion.feed_source_id == feed_source_id)
                .order_by(ExportVersion.version_number.desc())
            )
            return list(result.scalars().all())

    async def _mark_run_failed(self, feed_source_id: int, ingestion_run_id: int) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    run = (
                        await session.execute(
                            select(ExportRun).where(
                                ExportRun.feed_source_id == feed_source_id,
                                ExportRun.ingestion_run_id == ingestion_run_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if run is not None:
                        run.status = "failed"
                        run.completed_at = self._clock.now()
        except Exception:
            logger.exception(
                "failed to mark export run failed for feed source %s", feed_source_id
            )

    async def _prune_retention(self, feed_source_id: int, retention: int) -> None:
        numbers: list[int] = []
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    stale = (
                        await session.execute(
                            select(ExportVersion)
                            .where(ExportVersion.feed_source_id == feed_source_id)
                            .order_by(ExportVersion.version_number.desc())
                            .offset(max(retention, 1))
                        )
                    ).scalars().all()
                    numbers = [row.version_number for row in stale]
                    for row in stale:
                        await session.delete(row)
            for number in numbers:
                self._store.delete_version_file(feed_source_id, number)
        except Exception:
            logger.exception(
                "retention prune failed for feed source %s", feed_source_id
            )
