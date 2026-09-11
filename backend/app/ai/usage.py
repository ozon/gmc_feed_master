from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ai import AiUsageLog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageRecord:
    client_id: int | None
    feed_source_id: int | None
    task_type: str
    provider_config_id: int | None
    model: str
    cache_hit: bool
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal | None
    latency_ms: int
    error_code: str | None


class UsageLogWriter:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def write(self, record: UsageRecord) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                session.add(AiUsageLog(
                    client_id=record.client_id,
                    feed_source_id=record.feed_source_id,
                    task_type=record.task_type,
                    provider_config_id=record.provider_config_id,
                    model=record.model,
                    cache_hit=record.cache_hit,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    cost_usd=record.cost_usd,
                    latency_ms=record.latency_ms,
                    error_code=record.error_code,
                ))
        except Exception:
            # Usage logging must never fail the AI call.
            logger.exception("ai usage log write failed for task %s", record.task_type)


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_price_per_mtok: Decimal | None,
    output_price_per_mtok: Decimal | None,
) -> Decimal | None:
    if input_price_per_mtok is None or output_price_per_mtok is None:
        return None
    return (
        Decimal(prompt_tokens) * input_price_per_mtok / Decimal(1_000_000)
        + Decimal(completion_tokens) * output_price_per_mtok / Decimal(1_000_000)
    ).quantize(Decimal("0.000001"))


_GROUP_COLUMNS = {
    "client": AiUsageLog.client_id,
    "feed_source": AiUsageLog.feed_source_id,
    "task_type": AiUsageLog.task_type,
    "day": func.date(AiUsageLog.created_at),
}


async def aggregate_usage(
    session: AsyncSession,
    *,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    task_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    group_by: str = "client",
) -> list[dict[str, Any]]:
    group_column = _GROUP_COLUMNS[group_by]
    statement: Select[tuple[Any, ...]] = (
        select(
            group_column.label("group_key"),
            func.count().label("calls"),
            func.sum(case((AiUsageLog.cache_hit.is_(True), 1), else_=0)).label("cache_hits"),
            func.coalesce(func.sum(AiUsageLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AiUsageLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(AiUsageLog.cost_usd), 0).label("cost_usd"),
        )
        .group_by(group_column)
        .order_by(group_column)
    )
    if client_id is not None:
        statement = statement.where(AiUsageLog.client_id == client_id)
    if feed_source_id is not None:
        statement = statement.where(AiUsageLog.feed_source_id == feed_source_id)
    if task_type is not None:
        statement = statement.where(AiUsageLog.task_type == task_type)
    if from_dt is not None:
        statement = statement.where(AiUsageLog.created_at >= from_dt)
    if to_dt is not None:
        statement = statement.where(AiUsageLog.created_at < to_dt)
    result = await session.execute(statement)
    return [dict(row._mapping) for row in result.all()]
