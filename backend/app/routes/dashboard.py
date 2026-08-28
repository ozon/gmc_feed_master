from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.client import Client
from ..models.export import ExportRun
from ..models.feed_source import FeedSource
from ..models.ingestion import IngestionRun
from ..models.staging import StagingProduct

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


async def _latest_runs(session, model):
    result = await session.execute(
        select(model)
        .distinct(model.feed_source_id)
        .order_by(model.feed_source_id, model.id.desc())
    )
    return {row.feed_source_id: row for row in result.scalars()}


@router.get("/dashboard/summary")
async def dashboard_summary(
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        clients = list((await session.execute(select(Client).order_by(Client.name))).scalars())
        feeds = list((await session.execute(select(FeedSource).order_by(FeedSource.name))).scalars())
        item_counts = dict(
            (await session.execute(
                select(StagingProduct.feed_source_id, func.count())
                .where(StagingProduct.status == "active", StagingProduct.excluded.is_(False))
                .group_by(StagingProduct.feed_source_id)
            )).all()
        )
        total_active = (await session.execute(
            select(func.count()).select_from(StagingProduct)
            .where(StagingProduct.status == "active", StagingProduct.excluded.is_(False))
        )).scalar_one()
        latest_exports = await _latest_runs(session, ExportRun)
        latest_runs = await _latest_runs(session, IngestionRun)

    feeds_by_client: dict[int, list[dict]] = {}
    failed_last_exports = 0
    for feed in feeds:
        last_export = latest_exports.get(feed.id)
        last_run = latest_runs.get(feed.id)
        if last_export is not None and last_export.status == "failed":
            failed_last_exports += 1
        feeds_by_client.setdefault(feed.client_id, []).append({
            "id": feed.id,
            "client_id": feed.client_id,
            "name": feed.name,
            "source_format": feed.source_format,
            "item_count": item_counts.get(feed.id, 0),
            "last_export_at": last_export.started_at.isoformat() if last_export else None,
            "last_export_status": last_export.status if last_export else None,
            "last_run_at": last_run.started_at.isoformat() if last_run else None,
            "last_run_status": last_run.status if last_run else None,
        })

    return {
        "counts": {
            "clients": len(clients),
            "feed_sources": len(feeds),
            "active_products": total_active,
            "failed_last_exports": failed_last_exports,
        },
        "clients": [
            {"id": c.id, "name": c.name, "status": c.status,
             "feed_sources": feeds_by_client.get(c.id, [])}
            for c in clients
        ],
    }
