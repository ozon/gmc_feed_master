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
from ..ingest.xml_reader import parse_xml
from ..models.client import Client
from ..models.export import ExportRun, ExportVersion
from ..models.feed_source import FeedSource
from ..schemas.export import ExportFindingCounts, ExportVersionOut
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

    async def list_versions(self, feed_source_id: int) -> list[ExportVersionOut]:
        async with self._session_factory() as session:
            feed_source = await session.get(FeedSource, feed_source_id)
            export_token = feed_source.export_token if feed_source is not None else None
            result = await session.execute(
                select(ExportVersion, ExportRun)
                .join(ExportRun, ExportVersion.export_run_id == ExportRun.id)
                .where(ExportVersion.feed_source_id == feed_source_id)
                .order_by(ExportVersion.version_number.desc())
            )
            return [
                self._version_out(version, run, export_token)
                for version, run in result.all()
            ]

    def _version_out(
        self,
        version: ExportVersion,
        run: ExportRun | None,
        export_token: str | None,
    ) -> ExportVersionOut:
        findings = None
        if version.source != "rollback" and run is not None:
            findings = ExportFindingCounts(
                critical=run.critical_finding_count,
                warning=run.warning_finding_count,
                info=run.info_finding_count,
            )
        url = None
        if export_token is not None:
            url = f"{self._public_base_url.rstrip('/')}/export/{export_token}.xml"
        return ExportVersionOut(
            id=version.id,
            version_number=version.version_number,
            product_count=version.product_count,
            file_hash=version.file_hash,
            source=version.source,
            source_version_id=version.source_version_id,
            created_at=version.created_at,
            findings=findings,
            url=url,
        )

    async def diff(
        self,
        feed_source_id: int,
        version_number: int,
        against: int | None,
        registry: RegistryDocument,
    ) -> dict[str, Any]:
        async with self._session_factory() as session:
            version = (
                await session.execute(
                    select(ExportVersion).where(
                        ExportVersion.feed_source_id == feed_source_id,
                        ExportVersion.version_number == version_number,
                    )
                )
            ).scalar_one_or_none()
            if version is None:
                raise LookupError(f"version {version_number} not found")
            if against is None:
                against = (
                    await session.execute(
                        select(ExportVersion.version_number)
                        .where(
                            ExportVersion.feed_source_id == feed_source_id,
                            ExportVersion.version_number < version_number,
                        )
                        .order_by(ExportVersion.version_number.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if against is None:
                    raise LookupError(f"no preceding version for {version_number}")
            against_version = (
                await session.execute(
                    select(ExportVersion).where(
                        ExportVersion.feed_source_id == feed_source_id,
                        ExportVersion.version_number == against,
                    )
                )
            ).scalar_one_or_none()
            if against_version is None:
                raise LookupError(f"version {against} not found")

        new_products = self._load_version_products(feed_source_id, version_number, registry)
        old_products = self._load_version_products(feed_source_id, against, registry)
        return _field_diff(old_products, new_products, version_number, against)

    def _load_version_products(
        self, feed_source_id: int, version_number: int, registry: RegistryDocument
    ) -> dict[str, dict[str, Any]]:
        data = self._store.read_version(feed_source_id, version_number)
        if data is None:
            raise LookupError(f"version file {version_number} missing")
        report = parse_xml(data, registry)
        return {
            str(product["id"]): product
            for product in report.products
            if product.get("id")
        }

    async def rollback(
        self, feed_source_id: int, version_number: int, registry: RegistryDocument
    ) -> ExportVersionOut:
        async with self._session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, feed_source_id)
                if feed_source is None:
                    raise LookupError(f"feed source {feed_source_id} not found")
                client = await session.get(Client, feed_source.client_id)
                client_name = client.name if client is not None else ""
                source_version = (
                    await session.execute(
                        select(ExportVersion).where(
                            ExportVersion.feed_source_id == feed_source_id,
                            ExportVersion.version_number == version_number,
                        )
                    )
                ).scalar_one_or_none()
        if source_version is None:
            raise LookupError(f"version {version_number} not found")
        data = self._store.read_version(feed_source_id, version_number)
        if data is None:
            raise LookupError(f"version file {version_number} missing")

        report = parse_xml(data, registry)
        products = list(report.products)
        channel = channel_metadata_for(feed_source, client_name, self._public_base_url)
        rendered = render_feed(products, registry, channel)
        file_hash = hashlib.sha256(rendered).hexdigest()

        new_number: int | None = None
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
                    retention = locked.history_retention_count
                    latest = (
                        await session.execute(
                            select(ExportVersion)
                            .where(ExportVersion.feed_source_id == feed_source_id)
                            .order_by(ExportVersion.version_number.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    new_number = (latest.version_number + 1) if latest is not None else 1
                    self._store.write_version(feed_source_id, new_number, rendered)
                    run = ExportRun(
                        feed_source_id=feed_source_id,
                        ingestion_run_id=None,
                        status="rollback",
                        product_count=len(products),
                    )
                    session.add(run)
                    await session.flush()
                    version = ExportVersion(
                        feed_source_id=feed_source_id,
                        export_run_id=run.id,
                        version_number=new_number,
                        file_hash=file_hash,
                        product_count=len(products),
                        source="rollback",
                        source_version_id=source_version.id,
                    )
                    session.add(version)
                    await session.flush()
                    run.export_version_id = version.id
        except Exception:
            if new_number is not None:
                self._store.delete_version_file(feed_source_id, new_number)
            raise

        try:
            self._store.publish(feed_source_id, rendered)
        except Exception:
            await self._mark_run_failed_by_id(version.export_run_id)
            raise
        await self._prune_retention(feed_source_id, retention)
        return self._version_out(version, None, feed_source.export_token)

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

    async def _mark_run_failed_by_id(self, run_id: int) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    run = await session.get(ExportRun, run_id)
                    if run is not None:
                        run.status = "failed"
                        run.completed_at = self._clock.now()
        except Exception:
            logger.exception("failed to mark export run %s failed", run_id)

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


def _field_diff(
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
    version_number: int,
    against: int,
) -> dict[str, Any]:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed: list[dict[str, Any]] = []
    for product_id in sorted(set(old) & set(new)):
        fields = []
        for key in sorted(set(old[product_id]) | set(new[product_id])):
            old_value = old[product_id].get(key)
            new_value = new[product_id].get(key)
            if old_value != new_value:
                fields.append({"field": key, "old": old_value, "new": new_value})
        if fields:
            changed.append({"product_id": product_id, "fields": fields})
    return {
        "version": version_number,
        "against": against,
        "added": added,
        "removed": removed,
        "changed": changed,
    }
