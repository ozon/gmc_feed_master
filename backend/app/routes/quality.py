from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
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

    export_runs = list((await session.execute(
        select(ExportRun)
        .where(ExportRun.feed_source_id == feed_source_id)
        .order_by(ExportRun.id.desc())
        .limit(2)
    )).scalars().all())
    export_run = export_runs[0] if export_runs else None
    previous_run = export_runs[1] if len(export_runs) > 1 else None

    if export_run is None:
        return {
            "ingestion_run_id": None,
            "counts": {"critical": 0, "warning": 0, "info": 0},
            "findings": [],
            "product_count": 0,
            "delta": {"fixed": 0, "new": 0, "remaining": 0},
            "has_previous": False,
            "prev_counts": None,
        }

    findings_result = await session.execute(
        select(QualityFinding)
        .where(QualityFinding.feed_source_id == feed_source_id)
        .order_by(QualityFinding.id)
    )
    rows = list(findings_result.scalars().all())

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
        "product_count": export_run.product_count,
        "delta": {
            "fixed": export_run.fixed_finding_count,
            "new": export_run.new_finding_count,
            "remaining": export_run.remaining_finding_count,
        },
        "has_previous": previous_run is not None,
        "prev_counts": {
            "critical": previous_run.critical_finding_count,
            "warning": previous_run.warning_finding_count,
            "info": previous_run.info_finding_count,
        } if previous_run is not None else None,
    }


@router.get("/feed-sources/{feed_source_id}/quality-history")
async def get_quality_history(
    feed_source_id: int,
    limit: int = Query(default=30, ge=1, le=100),
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
):
    session = _require_db(db_session)
    feed_source = await session.get(FeedSource, feed_source_id)
    if feed_source is None:
        raise HTTPException(status_code=404, detail="feed source not found")
    rows = list((await session.execute(
        select(ExportRun)
        .where(ExportRun.feed_source_id == feed_source_id)
        .order_by(ExportRun.id.desc())
        .limit(limit)
    )).scalars().all())
    return {"rows": [
        {
            "id": row.id,
            "started_at": row.started_at.isoformat(),
            "product_count": row.product_count,
            "critical": row.critical_finding_count,
            "warning": row.warning_finding_count,
            "info": row.info_finding_count,
            "fixed": row.fixed_finding_count,
            "new": row.new_finding_count,
            "remaining": row.remaining_finding_count,
        }
        for row in reversed(rows)
    ]}
