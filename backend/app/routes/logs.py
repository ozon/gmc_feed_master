from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, require_admin
from ..auth import require_user
from ..db.engine import get_db_session
from ..event_log import record_client_error
from ..logging_setup import redact_mapping
from ..models.event_log import EventLog
from ..schemas.logs import ClientLogBatch, EventLogOut, EventLogPage

router = APIRouter()

_MAX_LIMIT = 500
_MAX_BODY_BYTES = 32000
_CLIENT_LOG_WINDOW_S = 60
_CLIENT_LOG_MAX_PER_WINDOW = 60
_client_log_hits: dict[str, tuple[float, int]] = {}


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _allow_client_log(username: str, now: float) -> bool:
    # ponytail: in-memory fixed window, single worker — move to Redis if workers scale.
    window_start, count = _client_log_hits.get(username, (now, 0))
    if now - window_start >= _CLIENT_LOG_WINDOW_S:
        _client_log_hits[username] = (now, 1)
        return True
    if count >= _CLIENT_LOG_MAX_PER_WINDOW:
        return False
    _client_log_hits[username] = (window_start, count + 1)
    return True


@router.get("/logs/entries", response_model=EventLogPage)
async def list_events(
    category: str | None = None,
    level: str | None = None,
    source: str | None = None,
    logger: str | None = None,
    actor: str | None = None,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    request_id: str | None = None,
    run_id: int | None = None,
    q: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = 100,
    cursor: int | None = None,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> EventLogPage:
    session = _require_db(db_session)
    stmt = select(EventLog).order_by(EventLog.id.desc())
    if category:
        stmt = stmt.where(EventLog.category == category)
    if level:
        stmt = stmt.where(EventLog.level == level)
    if source:
        stmt = stmt.where(EventLog.source == source)
    if logger:
        stmt = stmt.where(EventLog.logger == logger)
    if actor:
        stmt = stmt.where(EventLog.actor == actor)
    if client_id is not None:
        stmt = stmt.where(EventLog.client_id == client_id)
    if feed_source_id is not None:
        stmt = stmt.where(EventLog.feed_source_id == feed_source_id)
    if request_id:
        stmt = stmt.where(EventLog.request_id == request_id)
    if run_id is not None:
        stmt = stmt.where(EventLog.run_id == run_id)
    if q:
        stmt = stmt.where(EventLog.message.ilike(f"%{q}%"))
    if from_ is not None:
        stmt = stmt.where(EventLog.created_at >= from_)
    if to is not None:
        stmt = stmt.where(EventLog.created_at <= to)
    if cursor is not None:
        stmt = stmt.where(EventLog.id < cursor)
    limit = max(1, min(limit, _MAX_LIMIT))

    async with session.begin():
        rows = (await session.execute(stmt.limit(limit + 1))).scalars().all()
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return EventLogPage(
        items=[EventLogOut.model_validate(row) for row in rows[:limit]],
        next_cursor=next_cursor,
    )


@router.post("/logs/client", status_code=204)
async def ingest_client_logs(
    request: Request,
    payload: ClientLogBatch,
    username: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    session = _require_db(db_session)
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="log payload too large")
    if not _allow_client_log(username, time.monotonic()):
        raise HTTPException(status_code=429, detail="log rate limit exceeded")
    async with session.begin():
        for entry in payload.entries:
            context = redact_mapping(dict(entry.context))
            if entry.stack:
                context["stack"] = entry.stack
            if entry.url:
                context["url"] = entry.url.split("?")[0]
            await record_client_error(
                session,
                message=entry.message,
                level=entry.level,
                context=context,
                request_id=entry.request_id,
                route=entry.route,
                actor=username,
            )
