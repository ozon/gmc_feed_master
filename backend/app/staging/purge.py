from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.export import ExportRun
from ..models.ingestion import IngestionRun
from ..models.quality import QualityFinding
from ..models.staging import StagingHistory, StagingProduct

DEFAULT_REMOVAL_RETENTION_DAYS = 90
DEFAULT_HISTORY_RETENTION_DAYS = 90
DEFAULT_INGESTION_RUN_RETENTION_DAYS = 90


async def _retention(session: AsyncSession) -> tuple[int, int, int]:
    from ..models.global_setting import GlobalSetting

    row = await session.get(GlobalSetting, 1)
    if row is None:
        return (
            DEFAULT_REMOVAL_RETENTION_DAYS,
            DEFAULT_HISTORY_RETENTION_DAYS,
            DEFAULT_INGESTION_RUN_RETENTION_DAYS,
        )
    return (
        row.staging_removal_retention_days,
        row.staging_history_retention_days,
        row.ingestion_run_retention_days,
    )


@dataclass(frozen=True)
class PurgeCounts:
    removed_products: int
    history_rows: int


@dataclass(frozen=True)
class IngestionRunPurgeCounts:
    runs_purged: int
    export_runs_detached: int
    findings_deleted: int


async def purge_expired(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
) -> PurgeCounts:
    async with session_factory() as session:
        async with session.begin():
            removal_days, history_days, _ = await _retention(session)
            removal_cutoff = now - timedelta(days=removal_days)
            history_cutoff = now - timedelta(days=history_days)
            expiring = await session.execute(
                select(StagingProduct.id).where(
                    StagingProduct.status == "removed",
                    StagingProduct.removed_at < removal_cutoff,
                )
            )
            expiring_ids = list(expiring.scalars().all())
            cascaded = await session.execute(
                select(func.count())
                .select_from(StagingHistory)
                .where(StagingHistory.staging_product_id.in_(expiring_ids))
            )
            await session.execute(
                delete(StagingProduct).where(StagingProduct.id.in_(expiring_ids))
            )
            history = await session.execute(
                delete(StagingHistory)
                .where(StagingHistory.recorded_at < history_cutoff)
                .returning(StagingHistory.id)
            )
            return PurgeCounts(
                removed_products=len(expiring_ids),
                history_rows=cascaded.scalar_one() + len(history.scalars().all()),
            )


async def purge_expired_ingestion_runs(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
) -> IngestionRunPurgeCounts:
    async with session_factory() as session:
        async with session.begin():
            _, _, ingestion_days = await _retention(session)
            cutoff = now - timedelta(days=ingestion_days)
            candidates = await session.execute(
                select(IngestionRun.id).where(IngestionRun.started_at < cutoff)
            )
            candidate_ids = list(candidates.scalars().all())
            if not candidate_ids:
                return IngestionRunPurgeCounts(
                    runs_purged=0, export_runs_detached=0, findings_deleted=0
                )
            protected = await session.execute(
                select(StagingProduct.ingestion_run_id)
                .where(StagingProduct.ingestion_run_id.in_(candidate_ids))
                .distinct()
            )
            protected_ids = set(protected.scalars().all())
            purged_ids = [pk for pk in candidate_ids if pk not in protected_ids]
            if not purged_ids:
                return IngestionRunPurgeCounts(
                    runs_purged=0, export_runs_detached=0, findings_deleted=0
                )
            detached = await session.execute(
                update(ExportRun)
                .where(ExportRun.ingestion_run_id.in_(purged_ids))
                .values(ingestion_run_id=None)
            )
            findings = await session.execute(
                delete(QualityFinding).where(
                    QualityFinding.ingestion_run_id.in_(purged_ids)
                )
            )
            await session.execute(
                delete(IngestionRun).where(IngestionRun.id.in_(purged_ids))
            )
            return IngestionRunPurgeCounts(
                runs_purged=len(purged_ids),
                export_runs_detached=detached.rowcount,
                findings_deleted=findings.rowcount,
            )
