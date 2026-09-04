from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource
from ..models.staging import StagingProduct

router = APIRouter()

_BASELINE_FIELDS = ("title", "description", "link", "image_link",
                    "availability", "price", "condition")
_SORTS = {
    "product_id": StagingProduct.product_id,
    "title": StagingProduct.raw_data["title"].astext,
    "status": StagingProduct.status,
    "last_seen_at": StagingProduct.last_seen_at,
}
_SORTS_PROCESSED = {
    "product_id": StagingProduct.product_id,
    "title": StagingProduct.processed_data["title"].astext,
    "status": StagingProduct.status,
    "last_seen_at": StagingProduct.last_seen_at,
}


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _list_item(row: StagingProduct, stage: str = "raw") -> dict:
    raw = row.raw_data or {}
    if stage == "processed":
        processed = row.processed_data
        resolved = processed or raw
        item = {
            "product_id": row.product_id,
            "id": resolved.get("id", row.product_id),
            "status": row.status,
            "last_seen_at": row.last_seen_at.isoformat(),
            "processed": processed is not None,
            "excluded": row.excluded,
            "raw_data": raw,
            "processed_data": processed,
        }
        for field in _BASELINE_FIELDS:
            item[field] = resolved.get(field)
        return item
    item = {
        "product_id": row.product_id,
        "id": raw.get("id", row.product_id),
        "status": row.status,
        "last_seen_at": row.last_seen_at.isoformat(),
        "raw_data": raw,
    }
    for field in _BASELINE_FIELDS:
        item[field] = raw.get(field)
    return item


def _fields_union(rows: list[StagingProduct], stage: str = "raw") -> list[str]:
    fields: set[str] = set()
    for row in rows:
        source = row.raw_data or {}
        if stage == "processed":
            fields.update((row.processed_data or source).keys())
        else:
            fields.update(source.keys())
    return sorted(fields)


async def _require_feed_source(session: AsyncSession, feed_source_id: int) -> None:
    if await session.get(FeedSource, feed_source_id) is None:
        raise HTTPException(status_code=404, detail="feed source not found")


@router.get("/feed-sources/{feed_source_id}/products")
async def list_products(
    feed_source_id: int,
    stage: str = Query(default="raw"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None),
    status: str = Query(default="all"),
    sort: str = Query(default="product_id"),
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    if stage not in ("raw", "processed"):
        raise HTTPException(status_code=422, detail=f"unknown stage {stage!r}")
    if status not in ("active", "removed", "all"):
        raise HTTPException(status_code=422, detail=f"unknown status {status!r}")
    descending = sort.startswith("-")
    sort_field = sort[1:] if descending else sort
    sorts = _SORTS_PROCESSED if stage == "processed" else _SORTS
    if sort_field not in sorts:
        raise HTTPException(status_code=422, detail=f"unknown sort field {sort_field!r}")

    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
        filters = [StagingProduct.feed_source_id == feed_source_id]
        if status != "all":
            filters.append(StagingProduct.status == status)
        if q:
            pattern = f"%{q}%"
            title_field = (
                StagingProduct.processed_data["title"].astext
                if stage == "processed"
                else StagingProduct.raw_data["title"].astext
            )
            filters.append(or_(
                StagingProduct.product_id.ilike(pattern),
                title_field.ilike(pattern),
            ))
        total = (await session.execute(
            select(func.count()).select_from(StagingProduct).where(*filters)
        )).scalar_one()
        order = sorts[sort_field].desc() if descending else sorts[sort_field].asc()
        rows = list((await session.execute(
            select(StagingProduct).where(*filters).order_by(order)
            .offset((page - 1) * page_size).limit(page_size)
        )).scalars())
    return {
        "items": [_list_item(row, stage) for row in rows],
        "fields": _fields_union(rows, stage),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/feed-sources/{feed_source_id}/products/{product_id}")
async def product_detail(
    feed_source_id: int,
    product_id: str,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
        row = (await session.execute(
            select(StagingProduct).where(
                StagingProduct.feed_source_id == feed_source_id,
                StagingProduct.product_id == product_id,
            )
        )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="product not found")
    return {
        "product_id": row.product_id,
        "status": row.status,
        "content_hash": row.content_hash,
        "config_hash": row.config_hash,
        "last_seen_at": row.last_seen_at.isoformat(),
        "removed_at": row.removed_at.isoformat() if row.removed_at else None,
        "raw_data": row.raw_data,
        "processed_data": row.processed_data,
        "excluded": row.excluded,
    }


@router.get("/feed-sources/{feed_source_id}/fields")
async def feed_source_fields(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
        rows = (await session.execute(
            text(
                "SELECT DISTINCT jsonb_object_keys(raw_data)"
                " FROM staging_products WHERE feed_source_id = :fid"
            ),
            {"fid": feed_source_id},
        )).scalars().all()
    all_fields = sorted(set(rows) | set(_BASELINE_FIELDS))
    return {"fields": all_fields}
