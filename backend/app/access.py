from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_user
from .db.engine import get_db_session
from .models.user import User
from .models.user_client import UserClient


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: str
    is_active: bool
    # None means unrestricted (admins, or non-DB fallback mode).
    client_ids: frozenset[int] | None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="admin role required",
    )


async def _load_user(session: AsyncSession | None, username: str) -> CurrentUser:
    if session is None:
        # No PostgreSQL boundary configured: single-user mode stays fully
        # functional and is treated as unrestricted/admin.
        return CurrentUser(username=username, role="admin", is_active=True, client_ids=None)
    result = await session.execute(
        select(User, UserClient.client_id)
        .outerjoin(UserClient, UserClient.user_id == User.id)
        .where(User.username == username)
    )
    rows = result.all()
    if not rows:
        raise _unauthorized()
    user = rows[0][0]
    if not user.is_active:
        raise _unauthorized()
    if user.role == "admin":
        return CurrentUser(username=user.username, role="admin", is_active=True, client_ids=None)
    return CurrentUser(
        username=user.username,
        role=user.role,
        is_active=True,
        client_ids=frozenset(row[1] for row in rows if row[1] is not None),
    )


async def get_current_user(
    request_user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> CurrentUser:
    return await _load_user(db_session, request_user)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise _forbidden()
    return user
