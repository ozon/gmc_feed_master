from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from registry.loader import load_registry

from ..auth import require_user
from ..db.engine import get_db_session
from ..mapping.document import MappingDocument, MappingDocumentError, MappingEntry
from ..mapping.matcher import _COMPATIBLE_KINDS, auto_match
from ..models.feed_source import FeedSource
from ..schemas.field_mapping import FieldMappingOut, FieldMappingPut

router = APIRouter()

_STRUCTURED_KINDS = frozenset({"structured", "repeated_structured"})


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _load_document(feed_source: FeedSource) -> MappingDocument:
    try:
        return MappingDocument.from_json(feed_source.field_mapping)
    except MappingDocumentError as exc:
        raise HTTPException(status_code=500, detail="field mapping document corrupt") from exc


def _validate_mappings(
    mappings: dict[str, str],
    document: MappingDocument,
) -> list[str]:
    registry = load_registry()
    known_kinds = {field.name: field.kind for field in document.source_fields}
    errors: list[str] = []
    claimed: dict[str, str] = {}
    for source, target in mappings.items():
        parts = target.split(".")
        if len(parts) > 2 or not all(parts):
            errors.append(f"{source}: invalid target path {target!r}")
            continue
        attribute = registry.attributes.get(parts[0])
        if attribute is None:
            errors.append(f"{source}: unknown attribute {parts[0]!r}")
            continue
        if len(parts) == 2:
            if attribute.kind.value not in _STRUCTURED_KINDS:
                errors.append(f"{source}: {parts[0]!r} has no sub-fields")
                continue
            if parts[1] not in {sub.name for sub in attribute.fields}:
                errors.append(f"{source}: unknown sub-field {parts[1]!r} on {parts[0]!r}")
                continue
        source_kind = known_kinds.get(source)
        if (
            len(parts) == 1
            and source_kind is not None
            and attribute.kind.value not in _COMPATIBLE_KINDS.get(source_kind, frozenset())
        ):
            errors.append(
                f"{source}: kind {source_kind!r} incompatible with "
                f"{attribute.kind.value!r} target {target!r}"
            )
        if target in claimed:
            errors.append(f"{source}: target {target!r} already claimed by {claimed[target]!r}")
            continue
        claimed[target] = source
    return errors


def _validation_error(errors: list[str]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"errors": errors})


@router.get("/feed-sources/{feed_source_id}/field-mapping", response_model=FieldMappingOut)
async def get_field_mapping(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> MappingDocument:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        return _load_document(feed_source)


@router.put("/feed-sources/{feed_source_id}/field-mapping", response_model=FieldMappingOut)
async def update_field_mapping(
    feed_source_id: int,
    payload: FieldMappingPut,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> MappingDocument | JSONResponse:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        document = _load_document(feed_source)
        errors = _validate_mappings(
            {source: entry.target for source, entry in payload.mappings.items()},
            document,
        )
        if errors:
            return _validation_error(errors)
        document.mappings = {
            source: MappingEntry(target=entry.target, origin="manual")
            for source, entry in payload.mappings.items()
        }
        feed_source.field_mapping = document.to_json()
        return document


@router.post("/feed-sources/{feed_source_id}/field-mapping/auto", response_model=FieldMappingOut)
async def auto_map_fields(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> MappingDocument | JSONResponse:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        document = _load_document(feed_source)
        if not document.source_fields:
            return _validation_error(["no source fields observed yet"])
        document.mappings = auto_match(
            document.source_fields,
            load_registry(),
            existing={
                source: entry
                for source, entry in document.mappings.items()
                if entry.origin == "manual"
            },
        )
        document.auto_mapped = True
        feed_source.field_mapping = document.to_json()
        return document
