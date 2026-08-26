from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.staging import StagingHistory, StagingProduct

REMOVAL_RETENTION_DAYS = 90
HISTORY_RETENTION_DAYS = 90


@dataclass(frozen=True)
class PurgeCounts:
    removed_products: int
    history_rows: int


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
