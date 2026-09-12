from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.export import ExportRun
from ..models.feed_source import FeedSource
from ..models.ingestion import IngestionRun
from ..models.staging import StagingProduct

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


# (stage key in statistics JSONB, dropped-value extractor)
def _dropped_from(statistics: dict, stage: str) -> int:
    if stage == "ingest":
        errors = statistics.get("ingest", {}).get("row_errors")
        return len(errors) if isinstance(errors, list) else 0
    if stage == "mapping":
        return int(statistics.get("mapping", {}).get("dropped_unmapped_fields", 0))
    if stage == "staging":
        return int(statistics.get("staging", {}).get("failed", 0))
    if stage == "run_plugins":
        return int(statistics.get("plugins", {}).get("dropped", 0))
    return 0  # quality_check / export do not drop products


STAGES = ["ingest", "mapping", "staging", "run_plugins", "quality_check", "export"]


@router.get("/feed-sources/{feed_source_id}/dashboard")
async def feed_dashboard(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    feed_source = await session.get(FeedSource, feed_source_id)
    if feed_source is None:
        raise HTTPException(status_code=404, detail="feed source not found")

    valid_and_excluded = (await session.execute(
        select(StagingProduct.excluded, func.count())
        .where(
            StagingProduct.feed_source_id == feed_source_id,
            StagingProduct.status == "active",
        )
        .group_by(StagingProduct.excluded)
    )).all()
    valid_items = sum(count for excluded, count in valid_and_excluded if not excluded)
    excluded_items = sum(count for excluded, count in valid_and_excluded if excluded)

    runs = list((await session.execute(
        select(IngestionRun)
        .where(IngestionRun.feed_source_id == feed_source_id)
        .order_by(IngestionRun.id.desc())
        .limit(10)
    )).scalars())
    latest_run = runs[0] if runs else None

    export_runs = list((await session.execute(
        select(ExportRun)
        .where(ExportRun.feed_source_id == feed_source_id)
        .order_by(ExportRun.id.desc())
        .limit(30)
    )).scalars())
    latest_export = export_runs[0] if export_runs else None

    readiness = 1.0
    if latest_export is not None and latest_export.product_count > 0:
        readiness = 1 - latest_export.critical_finding_count / latest_export.product_count

    # Stage funnel from latest run's statistics JSONB, cumulative passed.
    stage_funnel: list[dict] = []
    if latest_run is not None and latest_run.statistics:
        passed = latest_run.processed_count
        for stage in STAGES:
            if stage == "export":
                passed_out = (
                    latest_export.product_count
                    if latest_export is not None
                    else passed
                )
                stage_funnel.append({"stage": stage, "passed": passed_out, "dropped": 0})
                continue
            dropped = _dropped_from(latest_run.statistics, stage)
            stage_funnel.append({"stage": stage, "passed": passed, "dropped": dropped})
            passed = max(0, passed - dropped)

    # Volume trend: per-day raw (ingestion processed) vs exportable (export count).
    since = datetime.now(timezone.utc) - timedelta(days=30)
    trend_runs = (await session.execute(
        select(
            func.date(IngestionRun.started_at).label("day"),
            func.max(IngestionRun.processed_count),
        )
        .where(
            IngestionRun.feed_source_id == feed_source_id,
            IngestionRun.started_at >= since,
        )
        .group_by("day")
        .order_by("day")
    )).all()
    export_by_day: dict[str, int] = {}
    for row in export_runs:
        if row.started_at >= since:
            key = str(row.started_at.date())
            export_by_day[key] = max(export_by_day.get(key, 0), row.product_count)
    volume_trend = [
        {
            "date": str(day),
            "raw": int(raw or 0),
            "exportable": export_by_day.pop(str(day), 0),
        }
        for day, raw in trend_runs
    ]
    for key in sorted(export_by_day):
        volume_trend.append({"date": key, "raw": 0, "exportable": export_by_day[key]})

    def _duration(run: IngestionRun) -> float | None:
        if run.completed_at is None:
            return None
        return (run.completed_at - run.started_at).total_seconds()

    last_duration = _duration(latest_run) if latest_run is not None else None

    return {
        "kpi": {
            "raw_items": latest_run.processed_count if latest_run is not None else 0,
            "valid_items": valid_items,
            "excluded_items": excluded_items,
            "last_duration_s": last_duration,
            "readiness_rate": readiness,
        },
        "volume_trend": volume_trend,
        "stage_funnel": stage_funnel,
        "quality": {
            "critical": latest_export.critical_finding_count if latest_export else 0,
            "warning": latest_export.warning_finding_count if latest_export else 0,
            "info": latest_export.info_finding_count if latest_export else 0,
            "readiness_rate": readiness,
        },
        "recent_runs": [
            {
                "id": run.id,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "duration_s": _duration(run),
                "failed_count": run.failed_count,
            }
            for run in reversed(runs)
        ],
    }
