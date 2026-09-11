from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, require_admin
from ..ai.usage import aggregate_usage
from ..db.engine import get_db_session
from ..models.ai import AiProviderConfig
from ..schemas.ai_admin import AiProviderCreate, AiProviderOut, AiProviderUpdate

router = APIRouter()

DbSession = Annotated[AsyncSession | None, Depends(get_db_session)]
AdminUser = Annotated[CurrentUser, Depends(require_admin)]
UsageGroupBy = Annotated[str, Query(pattern="^(client|feed_source|task_type|day)$")]
UsageFrom = Annotated[datetime | None, Query(alias="from")]
UsageTo = Annotated[datetime | None, Query(alias="to")]


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _ai_service(request: Request):
    service = getattr(request.app.state, "ai_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="ai service unavailable")
    return service


async def _clear_other_defaults(session: AsyncSession, keep_id: int) -> None:
    await session.execute(
        update(AiProviderConfig)
        .where(AiProviderConfig.id != keep_id)
        .values(is_default=False)
    )


@router.get("/admin/ai/providers", response_model=list[AiProviderOut])
async def list_providers(
    _admin: AdminUser,
    db_session: DbSession,
) -> list[AiProviderOut]:
    session = _require_db(db_session)
    result = await session.execute(select(AiProviderConfig).order_by(AiProviderConfig.id))
    return [AiProviderOut.model_validate(row) for row in result.scalars()]


@router.post("/admin/ai/providers", status_code=201, response_model=AiProviderOut)
async def create_provider(
    payload: AiProviderCreate,
    _admin: AdminUser,
    db_session: DbSession,
) -> AiProviderOut:
    session = _require_db(db_session)
    async with session.begin():
        row = AiProviderConfig(**payload.model_dump())
        session.add(row)
        await session.flush()
        if row.is_default:
            await _clear_other_defaults(session, row.id)
    return AiProviderOut.model_validate(row)


@router.patch("/admin/ai/providers/{provider_id}", response_model=AiProviderOut)
async def update_provider(
    provider_id: int,
    payload: AiProviderUpdate,
    _admin: AdminUser,
    db_session: DbSession,
) -> AiProviderOut:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(AiProviderConfig, provider_id)
        if row is None:
            raise HTTPException(status_code=404, detail="provider not found")
        updates = payload.model_dump(exclude_unset=True)
        if "api_key" in updates:
            row.api_key = updates.pop("api_key")
        for key, value in updates.items():
            setattr(row, key, value)
        await session.flush()
        if row.is_default:
            await _clear_other_defaults(session, row.id)
    await session.refresh(row)
    return AiProviderOut.model_validate(row)


@router.delete("/admin/ai/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: int,
    _admin: AdminUser,
    db_session: DbSession,
) -> None:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(AiProviderConfig, provider_id)
        if row is None:
            raise HTTPException(status_code=404, detail="provider not found")
        await session.delete(row)


@router.post("/admin/ai/providers/{provider_id}/test")
async def test_provider(
    provider_id: int,
    request: Request,
    _admin: AdminUser,
    db_session: DbSession,
) -> dict[str, Any]:
    _require_db(db_session)  # service resolves config through its own session
    service = _ai_service(request)
    return await service.test_provider(provider_id)


@router.get("/admin/ai/usage")
async def get_usage(
    _admin: AdminUser,
    db_session: DbSession,
    group_by: UsageGroupBy = "client",
    client_id: int | None = None,
    feed_source_id: int | None = None,
    task_type: str | None = None,
    from_dt: UsageFrom = None,
    to_dt: UsageTo = None,
) -> dict[str, Any]:
    session = _require_db(db_session)
    rows = await aggregate_usage(
        session,
        client_id=client_id, feed_source_id=feed_source_id,
        task_type=task_type, from_dt=from_dt, to_dt=to_dt,
        group_by=group_by,
    )
    return {"rows": rows}
