"""Provider-presets and model-catalog endpoints for the AI Provider
Configuration wizard (GFM-12).

Kept as its own router (mirroring the style of `app/routes/ai_admin.py`:
`AdminUser`/`DbSession` deps, `_require_db` guard) rather than appended to
`ai_admin.py` directly, so it can be reviewed/merged independently and
registered with a single `app.include_router(router)` call next to the
existing `ai_admin.router` registration in the app factory.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, require_admin
from ..ai.model_catalog import get_catalog_status, list_catalog_models, refresh_model_catalog
from ..ai.presets import list_presets
from ..db.engine import get_db_session
from ..schemas.model_catalog import (
    ModelCatalogEntryOut,
    ModelCatalogRefreshOut,
    ModelCatalogStatusOut,
    ProviderPresetOut,
)

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    """Local copy of `app.routes.ai_admin._require_db` (kept private there)."""
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


DbSession = Annotated[AsyncSession | None, Depends(get_db_session)]
AdminUser = Annotated[CurrentUser, Depends(require_admin)]


@router.get("/admin/ai/providers/presets", response_model=list[ProviderPresetOut])
async def list_provider_presets(_admin: AdminUser) -> list[ProviderPresetOut]:
    return [
        ProviderPresetOut(
            vendor_key=p.vendor_key,
            label=p.label,
            model_prefix=p.model_prefix,
            default_base_url=p.default_base_url,
            requires_base_url=p.requires_base_url,
            requires_api_version=p.requires_api_version,
            api_key_docs_url=p.api_key_docs_url,
            description=p.description,
            is_custom=p.is_custom,
        )
        for p in list_presets()
    ]


@router.get("/admin/ai/model-catalog", response_model=list[ModelCatalogEntryOut])
async def get_model_catalog(
    _admin: AdminUser,
    db_session: DbSession,
    vendor: str | None = Query(default=None),
) -> list[ModelCatalogEntryOut]:
    session = _require_db(db_session)
    rows = await list_catalog_models(session, vendor=vendor)
    return [ModelCatalogEntryOut.model_validate(row) for row in rows]


@router.get("/admin/ai/model-catalog/status", response_model=ModelCatalogStatusOut)
async def get_model_catalog_status(
    _admin: AdminUser,
    db_session: DbSession,
) -> ModelCatalogStatusOut:
    session = _require_db(db_session)
    status: dict[str, Any] = await get_catalog_status(session)
    return ModelCatalogStatusOut(**status)


@router.post("/admin/ai/model-catalog/refresh", response_model=ModelCatalogRefreshOut)
async def refresh_model_catalog_endpoint(
    _admin: AdminUser,
    db_session: DbSession,
) -> ModelCatalogRefreshOut:
    session = _require_db(db_session)
    result = await refresh_model_catalog(session)
    return ModelCatalogRefreshOut(
        synced_count=result.synced_count,
        skipped_count=result.skipped_count,
        source=result.source,
        synced_at=result.synced_at,
        error=result.error,
    )
