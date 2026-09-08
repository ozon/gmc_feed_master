from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, require_admin
from ..db.engine import get_db_session
from ..models.global_setting import GlobalSetting
from ..models.user_client import UserClient
from ..persistence import users as user_repo
from ..schemas.admin import (
    AdminUserCreate,
    AdminUserOut,
    AdminUserUpdate,
    GlobalSettingsOut,
    GlobalSettingsUpdate,
    PasswordSet,
)

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _user_out(user, client_ids: list[int]) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        client_ids=client_ids,
    )


async def _user_client_ids(session: AsyncSession, user_id: int) -> list[int]:
    result = await session.execute(
        select(UserClient.client_id).where(UserClient.user_id == user_id)
    )
    return sorted(result.scalars().all())


@router.get("/admin/users", response_model=list[AdminUserOut])
async def list_users(
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[AdminUserOut]:
    session = _require_db(db_session)
    rows = await user_repo.list_users(session)
    return [_user_out(user, client_ids) for user, client_ids in rows]


@router.post("/admin/users", status_code=201, response_model=AdminUserOut)
async def create_user(
    payload: AdminUserCreate,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> AdminUserOut:
    session = _require_db(db_session)
    try:
        user = await user_repo.create_user(
            session,
            payload.username,
            payload.password,
            payload.role,
            payload.client_ids,
            payload.is_active,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="username already exists") from exc
    return _user_out(user, payload.client_ids)


@router.patch("/admin/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> AdminUserOut:
    session = _require_db(db_session)
    user = await user_repo.update_user(
        session,
        user_id,
        role=payload.role,
        is_active=payload.is_active,
        client_ids=payload.client_ids,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _user_out(user, await _user_client_ids(session, user.id))


@router.post("/admin/users/{user_id}/password", status_code=204)
async def set_password(
    user_id: int,
    payload: PasswordSet,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    session = _require_db(db_session)
    if not await user_repo.set_user_password(session, user_id, payload.new_password):
        raise HTTPException(status_code=404, detail="user not found")


@router.get("/admin/settings", response_model=GlobalSettingsOut)
async def get_settings_row(
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> GlobalSetting:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(GlobalSetting, 1)
        if row is None:
            row = GlobalSetting(
                id=1,
                staging_removal_retention_days=90,
                staging_history_retention_days=90,
                ingestion_run_retention_days=90,
            )
            session.add(row)
    return row


@router.put("/admin/settings", response_model=GlobalSettingsOut)
async def put_settings_row(
    payload: GlobalSettingsUpdate,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> GlobalSetting:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(GlobalSetting, 1)
        if row is None:
            row = GlobalSetting(
                id=1,
                staging_removal_retention_days=90,
                staging_history_retention_days=90,
                ingestion_run_retention_days=90,
            )
            session.add(row)
        row.staging_removal_retention_days = payload.staging_removal_retention_days
        row.staging_history_retention_days = payload.staging_history_retention_days
        row.ingestion_run_retention_days = payload.ingestion_run_retention_days
    return row


@router.get("/admin/scheduler")
async def scheduler_jobs(
    request: Request,
    _admin: CurrentUser = Depends(require_admin),
) -> list[dict[str, str]]:
    scheduler = getattr(request.app.state, "scheduler_service", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler unavailable")
    return scheduler.list_jobs()
