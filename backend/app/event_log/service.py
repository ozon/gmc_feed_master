from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.event_log import EventLog
from ..models.global_setting import GlobalSetting

DEFAULT_EVENT_LOG_RETENTION_DAYS = 180
EVENT_LOG_PURGE_JOB_ID = "system-event-log-purge"
_MAX_MESSAGE = 4000


def _bound(name: str) -> Any:
    return structlog.contextvars.get_contextvars().get(name)


async def record_event(
    session: AsyncSession,
    *,
    category: str,
    level: str,
    source: str,
    message: str,
    context: dict[str, Any] | None = None,
    logger: str | None = None,
    actor: str | None = None,
    actor_role: str | None = None,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    request_id: str | None = None,
    run_id: int | None = None,
) -> None:
    session.add(
        EventLog(
            category=category,
            level=level,
            source=source,
            message=message[:_MAX_MESSAGE],
            context=context or {},
            logger=logger,
            actor=actor,
            actor_role=actor_role,
            client_id=client_id,
            feed_source_id=feed_source_id,
            request_id=request_id,
            run_id=run_id,
        )
    )


async def audit(
    session: AsyncSession,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    context: dict[str, Any] = dict(detail or {})
    if target_type is not None:
        context["target_type"] = target_type
    if target_id is not None:
        context["target_id"] = str(target_id)
    await record_event(
        session,
        category="audit",
        level=level,
        source="backend",
        message=action,
        context=context,
        actor=_bound("actor"),
        actor_role=_bound("actor_role"),
        client_id=_bound("client_id"),
        feed_source_id=_bound("feed_source_id"),
        request_id=_bound("request_id"),
        run_id=_bound("run_id"),
    )


async def record_client_error(
    session: AsyncSession,
    *,
    message: str,
    level: str = "error",
    context: dict[str, Any] | None = None,
    request_id: str | None = None,
    route: str | None = None,
    actor: str | None = None,
) -> None:
    ctx: dict[str, Any] = dict(context or {})
    if route:
        ctx.setdefault("route", route)
    await record_event(
        session,
        category="client_error",
        level=level,
        source="frontend",
        message=message,
        context=ctx,
        actor=actor or _bound("actor"),
        actor_role=_bound("actor_role"),
        request_id=request_id or _bound("request_id"),
    )


async def record_server_error(
    session: AsyncSession,
    *,
    message: str,
    context: dict[str, Any] | None = None,
    request_id: str | None = None,
    logger: str | None = None,
) -> None:
    await record_event(
        session,
        category="server_error",
        level="error",
        source="backend",
        message=message,
        context=context or {},
        actor=_bound("actor"),
        actor_role=_bound("actor_role"),
        client_id=_bound("client_id"),
        feed_source_id=_bound("feed_source_id"),
        request_id=request_id or _bound("request_id"),
        run_id=_bound("run_id"),
        logger=logger,
    )


@dataclass(frozen=True)
class EventLogPurgeCounts:
    rows: int


async def _retention_days(session: AsyncSession, default_days: int) -> int:
    row = await session.get(GlobalSetting, 1)
    if row is None:
        return default_days
    return row.event_log_retention_days


async def purge_expired_events(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
    default_days: int = DEFAULT_EVENT_LOG_RETENTION_DAYS,
) -> EventLogPurgeCounts:
    async with session_factory() as session, session.begin():
        days = await _retention_days(session, default_days)
        result = await session.execute(
            delete(EventLog).where(EventLog.created_at < now - timedelta(days=days))
        )
        return EventLogPurgeCounts(rows=result.rowcount)
