from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy import update

from ..models.ingestion import IngestionRun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..clock import Clock

INTERRUPTED_MESSAGE = "interrupted by restart"


async def reconcile_interrupted_runs(
    session_factory: Callable[[], AsyncSession],
    clock: Clock,
) -> int:
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                update(IngestionRun)
                .where(IngestionRun.status.in_(("running", "pending")))
                .values(
                    status="error",
                    error_message=INTERRUPTED_MESSAGE,
                    completed_at=clock.now(),
                )
            )
            return result.rowcount
