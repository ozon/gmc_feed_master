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

REMOVAL_RETENTION_DAYS = 90
HISTORY_RETENTION_DAYS = 90
INGESTION_RUN_RETENTION_DAYS = 90


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
    removal_cutoff = now - timedelta(days=REMOVAL_RETENTION_DAYS)
    history_cutoff = now - timedelta(days=HISTORY_RETENTION_DAYS)

    async with session_factory() as session:
        async with session.begin():
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
    cutoff = now - timedelta(days=INGESTION_RUN_RETENTION_DAYS)

    async with session_factory() as session:
        async with session.begin():
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
