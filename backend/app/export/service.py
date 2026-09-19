from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.model import RegistryDocument

from ..clock import Clock
from ..ingest.xml_reader import parse_xml
from ..models.client import Client
from ..models.export import ExportRun, ExportVersion
from ..models.feed_source import FeedSource
from ..models.quality import QualityFinding
from ..schemas.export import (
    ExportFindingCounts,
    ExportSource,
    ExportVersionOut,
    FindingRuleDiffOut,
    FindingsDeltaTotals,
    FindingsDiffOut,
)
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
        source: str = "manual",
    ) -> ExportOutcome:
        async with self._session_factory() as session, session.begin():
            feed_source = await session.get(FeedSource, feed_source_id)
            if feed_source is None:
                raise LookupError(f"feed source {feed_source_id} not found")
            client = await session.get(Client, feed_source.client_id)
            client_name = client.name if client is not None else ""
            retention = feed_source.history_retention_count

        try:
            channel = channel_metadata_for(feed_source, client_name, self._public_base_url)
            data = await asyncio.to_thread(render_feed, products, registry, channel)
            file_hash = hashlib.sha256(data).hexdigest()
        except Exception:
            await self._mark_run_failed(feed_source_id, ingestion_run_id)
            raise

        deduplicated = False
        version_number: int | None = None

        try:
            async with self._session_factory() as session, session.begin():
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
                    await asyncio.to_thread(
                        self._store.write_version, feed_source_id, version_number, data
                    )
                    new_version = ExportVersion(
                        feed_source_id=feed_source_id,
                        export_run_id=run.id,
                        version_number=version_number,
                        file_hash=file_hash,
                        product_count=len(products),
                        source=source,
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
                await asyncio.to_thread(self._store.publish, feed_source_id, data)
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
            source=cast(ExportSource, version.source),
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

            # SQLAlchemy Row unpacks as a tuple but is not typed as Iterable[tuple],
            # so C416's dict(rows) rewrite does not typecheck.
            run_ids: dict[int, int | None] = {  # noqa: C416
                number: ingestion_run_id
                for number, ingestion_run_id in (
                    await session.execute(
                        select(ExportVersion.version_number, ExportRun.ingestion_run_id)
                        .join(ExportRun, ExportVersion.export_run_id == ExportRun.id)
                        .where(
                            ExportVersion.feed_source_id == feed_source_id,
                            ExportVersion.version_number.in_([version_number, against]),
                        )
                    )
                ).all()
            }
            run_a = run_ids.get(against)
            run_b = run_ids.get(version_number)
            findings_by_run: dict[int | None, list[QualityFinding]] = {}
            present = [run_id for run_id in (run_a, run_b) if run_id is not None]
            if present:
                rows = (await session.execute(
                    select(QualityFinding).where(
                        QualityFinding.feed_source_id == feed_source_id,
                        QualityFinding.ingestion_run_id.in_(present),
                    )
                )).scalars()
                for row in rows:
                    findings_by_run.setdefault(row.ingestion_run_id, []).append(row)

        new_products = await self._load_version_products(feed_source_id, version_number, registry)
        old_products = await self._load_version_products(feed_source_id, against, registry)
        result = _field_diff(old_products, new_products, version_number, against)
        result["findings"] = _findings_diff(
            findings_by_run.get(run_a, []),
            findings_by_run.get(run_b, []),
            a_qc=run_a is not None,
            b_qc=run_b is not None,
        ).model_dump()
        return result

    async def _load_version_products(
        self, feed_source_id: int, version_number: int, registry: RegistryDocument
    ) -> dict[str, dict[str, Any]]:
        data = await asyncio.to_thread(
            self._store.read_version, feed_source_id, version_number
        )
        if data is None:
            raise LookupError(f"version file {version_number} missing")
        report = parse_xml(data, registry)
        return {
            str(product["id"]): product
            for product in report.products
            if product.get("id")
        }

    async def version_content(self, feed_source_id: int, version_number: int) -> bytes:
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
        data = await asyncio.to_thread(
            self._store.read_version, feed_source_id, version_number
        )
        if data is None:
            raise LookupError(f"version file {version_number} missing")
        return data

    async def rollback(
        self, feed_source_id: int, version_number: int, registry: RegistryDocument
    ) -> ExportVersionOut:
        async with self._session_factory() as session, session.begin():
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
        data = await asyncio.to_thread(
            self._store.read_version, feed_source_id, version_number
        )
        if data is None:
            raise LookupError(f"version file {version_number} missing")

        report = parse_xml(data, registry)
        products = list(report.products)
        channel = channel_metadata_for(feed_source, client_name, self._public_base_url)
        rendered = await asyncio.to_thread(render_feed, products, registry, channel)
        file_hash = hashlib.sha256(rendered).hexdigest()

        new_number: int | None = None
        try:
            async with self._session_factory() as session, session.begin():
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
                await asyncio.to_thread(
                    self._store.write_version, feed_source_id, new_number, rendered
                )
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
            await asyncio.to_thread(self._store.publish, feed_source_id, rendered)
        except Exception:
            await self._mark_run_failed_by_id(version.export_run_id)
            raise
        await self._prune_retention(feed_source_id, retention)
        return self._version_out(version, None, feed_source.export_token)

    async def _mark_run_failed(self, feed_source_id: int, ingestion_run_id: int) -> None:
        try:
            async with self._session_factory() as session, session.begin():
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
            async with self._session_factory() as session, session.begin():
                run = await session.get(ExportRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.completed_at = self._clock.now()
        except Exception:
            logger.exception("failed to mark export run %s failed", run_id)

    async def _prune_retention(self, feed_source_id: int, retention: int) -> None:
        numbers: list[int] = []
        try:
            async with self._session_factory() as session, session.begin():
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


FINDING_SAMPLE_CAP = 20
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


class _FindingRow(Protocol):
    code: str
    severity: str
    product_id: str
    field: str | None


def _findings_diff(
    a: Sequence[_FindingRow],
    b: Sequence[_FindingRow],
    a_qc: bool,
    b_qc: bool,
) -> FindingsDiffOut:
    if not (a_qc and b_qc):
        return FindingsDiffOut(
            a_qc=a_qc,
            b_qc=b_qc,
            totals=FindingsDeltaTotals(added=0, fixed=0, persisted=0),
            rules=[],
        )
    a_map = {(row.code, row.product_id, row.field): row for row in a}
    b_map = {(row.code, row.product_id, row.field): row for row in b}
    added = set(b_map) - set(a_map)
    fixed = set(a_map) - set(b_map)
    persisted = set(a_map) & set(b_map)

    severity_by_code: dict[str, str] = {}
    for row in (*a, *b):
        current = severity_by_code.get(row.code)
        if current is None or _SEVERITY_RANK.get(row.severity, 3) < _SEVERITY_RANK.get(current, 3):
            severity_by_code[row.code] = row.severity

    def products(keys: set[tuple[str, str, str | None]], code: str) -> list[str]:
        return sorted({key[1] for key in keys if key[0] == code})

    rules = [
        FindingRuleDiffOut(
            code=code,
            severity=severity_by_code.get(code, "info"),
            added=sum(1 for key in added if key[0] == code),
            fixed=sum(1 for key in fixed if key[0] == code),
            persisted=sum(1 for key in persisted if key[0] == code),
            sample_added=products(added, code)[:FINDING_SAMPLE_CAP],
            sample_fixed=products(fixed, code)[:FINDING_SAMPLE_CAP],
            sample_persisted=products(persisted, code)[:FINDING_SAMPLE_CAP],
        )
        for code in {key[0] for key in added | fixed | persisted}
    ]
    rules.sort(key=lambda rule: (_SEVERITY_RANK.get(rule.severity, 3), rule.code))

    return FindingsDiffOut(
        a_qc=a_qc,
        b_qc=b_qc,
        totals=FindingsDeltaTotals(
            added=len(added), fixed=len(fixed), persisted=len(persisted)
        ),
        rules=rules,
    )
