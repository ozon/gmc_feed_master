from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..ingest.report import SourceField
from ..mapping.document import MappingDocument
from ..mapping.indexed_path import parse_indexed_path
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


def _source_field_descriptor(sf: SourceField) -> dict:
    sub_kind = "repeated_scalar" if sf.kind == "repeated_structured" else "scalar"
    return {
        "name": sf.name,
        "kind": sf.kind,
        "sub_fields": [{"name": sub, "kind": sub_kind} for sub in sf.sub_fields],
        "max_repeats": (
            sf.max_repeats
            if sf.kind in ("repeated_scalar", "repeated_structured")
            else 1
        ),
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
        feed_source = await session.get(FeedSource, feed_source_id)
    assert feed_source is not None  # _require_feed_source raises 404 otherwise
    doc = MappingDocument.from_json(feed_source.field_mapping)
    fields: dict[str, dict] = {
        sf.name: _source_field_descriptor(sf) for sf in doc.source_fields
    }
    for name in _BASELINE_FIELDS:
        if name not in fields:
            fields[name] = {
                "name": name,
                "kind": "scalar",
                "sub_fields": [],
                "max_repeats": 1,
            }
    return {"fields": [fields[name] for name in sorted(fields)]}


class _LookupRequest(BaseModel):
    field: str = "id"
    values: list[str] = Field(min_length=1, max_length=10_000)
    extraFields: list[str] = Field(default_factory=list, max_length=20)


def _product_field_candidates(raw: dict, path: str) -> list[str]:
    """Candidate values of a registry path in raw_data — mirrors the
    custom_labels plugin's resolve_path() semantics (scalar / repeated /
    attr.sub / indexed attr.N[.sub]). Keep in sync with
    plugins/core/custom_labels/plugin.py."""
    try:
        parsed = parse_indexed_path(path)
    except ValueError:
        return []
    value = raw.get(parsed.attr)
    if value is None:
        return []
    if parsed.index is not None:
        if not isinstance(value, list) or len(value) < parsed.index:
            return []
        element = value[parsed.index - 1]
        if parsed.sub is None:
            return [str(element)] if element not in (None, "") else []
        if not isinstance(element, dict):
            return []
        item = element.get(parsed.sub)
        return [str(item)] if item not in (None, "") else []
    if parsed.sub:
        if isinstance(value, dict):
            item = value.get(parsed.sub)
            return [str(item)] if item not in (None, "") else []
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict):
                return []
            item = value[0].get(parsed.sub)
            return [str(item)] if item not in (None, "") else []
        return []
    if isinstance(value, str):
        return [value] if value != "" else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _lookup_sample(row: StagingProduct, extra_fields: list[str]) -> dict:
    raw = row.raw_data or {}
    sample = {
        "product_id": row.product_id,
        "status": row.status,
        "excluded": row.excluded,
        "title": raw.get("title"),
        "brand": raw.get("brand"),
        "availability": raw.get("availability"),
    }
    for field in extra_fields:
        sample[field] = raw.get(field)
    return sample


@router.post("/feed-sources/{feed_source_id}/products/lookup")
async def lookup_products(
    feed_source_id: int,
    payload: _LookupRequest,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
        rows = (await session.execute(
            select(StagingProduct.product_id, StagingProduct.status,
                   StagingProduct.excluded, StagingProduct.raw_data)
            .where(StagingProduct.feed_source_id == feed_source_id)
        )).all()
        matches: dict[str, dict] = {
            value: {"count": 0, "sample_id": None}
            for value in dict.fromkeys(payload.values)
        }
        for product_id, _status, _excluded, raw in rows:
            for candidate in set(_product_field_candidates(raw or {}, payload.field)):
                entry = matches.get(candidate)
                if entry is None:
                    continue
                entry["count"] += 1
                if entry["sample_id"] is None or product_id < entry["sample_id"]:
                    entry["sample_id"] = product_id
        sample_ids = sorted(
            {entry["sample_id"] for entry in matches.values() if entry["sample_id"] is not None}
        )
        sample_rows: dict[str, StagingProduct] = {}
        if sample_ids:
            sample_rows = {
                row.product_id: row
                for row in (await session.execute(
                    select(StagingProduct).where(
                        StagingProduct.feed_source_id == feed_source_id,
                        StagingProduct.product_id.in_(sample_ids),
                    )
                )).scalars()
            }
    return {
        "matches": {
            value: {
                "count": entry["count"],
                "sample": (
                    _lookup_sample(sample_rows[entry["sample_id"]], payload.extraFields)
                    if entry["sample_id"] is not None else None
                ),
            }
            for value, entry in matches.items()
        }
    }
