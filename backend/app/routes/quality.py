from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource
from ..models.quality import QualityFinding
from ..models.export import ExportRun

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


@router.get("/feed-sources/{feed_source_id}/quality-findings")
async def get_quality_findings(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
):
    session = _require_db(db_session)

    feed_source = await session.get(FeedSource, feed_source_id)
    if feed_source is None:
        raise HTTPException(status_code=404, detail="feed source not found")

    result = await session.execute(
        select(ExportRun)
        .where(ExportRun.feed_source_id == feed_source_id)
        .order_by(desc(ExportRun.id))
        .limit(1)
    )
    export_run = result.scalar_one_or_none()

    if export_run is None:
        return {
            "ingestion_run_id": None,
            "counts": {"critical": 0, "warning": 0, "info": 0},
            "findings": [],
        }

    result = await session.execute(
        select(QualityFinding)
        .where(QualityFinding.feed_source_id == feed_source_id)
        .order_by(QualityFinding.id)
    )
    rows = list(result.scalars().all())

    findings = [
        {
            "severity": row.severity,
            "code": row.code,
            "field": row.field,
            "message": row.message,
            "product_id": row.product_id,
            "details": row.details,
        }
        for row in rows
    ]

    return {
        "ingestion_run_id": export_run.ingestion_run_id,
        "counts": {
            "critical": export_run.critical_finding_count,
            "warning": export_run.warning_finding_count,
            "info": export_run.info_finding_count,
        },
        "findings": findings,
    }
