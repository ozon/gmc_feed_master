from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiUsageLog

AI_PURGE_JOB_ID = "system-ai-purge"

DEFAULT_AI_USAGE_RETENTION_DAYS = 90


@dataclass(frozen=True)
class AiPurgeCounts:
    usage_rows: int


async def _retention(session: AsyncSession) -> int:
    from ..models.global_setting import GlobalSetting

    row = await session.get(GlobalSetting, 1)
    if row is None:
        return DEFAULT_AI_USAGE_RETENTION_DAYS
    return row.ai_usage_retention_days


async def purge_expired_ai(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
) -> AiPurgeCounts:
    async with session_factory() as session, session.begin():
        usage_days = await _retention(session)
        usage = await session.execute(
            delete(AiUsageLog).where(
                AiUsageLog.created_at < now - timedelta(days=usage_days)
            )
        )
        return AiPurgeCounts(usage_rows=usage.rowcount)
