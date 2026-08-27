from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from registry.loader import load_registry

from ..auth import require_user
from ..config import Settings, get_settings
from ..db.engine import get_db_session
from ..export.service import ExportService
from ..export.store import ExportFileStore
from ..models.feed_source import FeedSource
from ..schemas.export import DiffOut, ExportVersionOut

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _service(request: Request, settings: Settings) -> ExportService:
    return ExportService(
        request.app.state.db_session_factory,
        ExportFileStore(Path(settings.export_dir)),
        request.app.state.clock,
        settings.public_base_url,
    )


async def _require_feed_source(session: AsyncSession, feed_source_id: int) -> None:
    if await session.get(FeedSource, feed_source_id) is None:
        raise HTTPException(status_code=404, detail="feed source not found")


@router.get(
    "/feed-sources/{feed_source_id}/export-history",
    response_model=list[ExportVersionOut],
)
async def export_history(
    feed_source_id: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
    return await _service(request, settings).list_versions(feed_source_id)


@router.get(
    "/feed-sources/{feed_source_id}/export-history/{version_number}/diff",
    response_model=DiffOut,
)
async def export_diff(
    feed_source_id: int,
    version_number: int,
    request: Request,
    against: int | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
    try:
        return await _service(request, settings).diff(
            feed_source_id, version_number, against, load_registry()
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/feed-sources/{feed_source_id}/export-history/{version_number}/rollback",
    response_model=ExportVersionOut,
    status_code=201,
)
async def export_rollback(
    feed_source_id: int,
    version_number: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
    try:
        return await _service(request, settings).rollback(
            feed_source_id, version_number, load_registry()
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
