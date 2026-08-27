from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource

router = APIRouter()


@router.get("/export/{token}.xml")
async def public_export(
    token: str,
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    result = await db_session.execute(
        select(FeedSource).where(FeedSource.export_token == token)
    )
    feed_source = result.scalar_one_or_none()
    if feed_source is None:
        raise HTTPException(status_code=404, detail="not found")
    path = Path(settings.export_dir) / "published" / f"{feed_source.id}.xml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="application/xml")
