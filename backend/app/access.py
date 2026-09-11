from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
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
    user = await _load_user(db_session, request_user)
    if db_session is not None:
        # Close the implicitly-begun read transaction so handlers can start
        # their own `session.begin()` without InvalidRequestError.
        await db_session.rollback()
    return user


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise _forbidden()
    return user


async def enforce_scope_access(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    if user.client_ids is None:
        return
    client_id = request.path_params.get("client_id") or request.query_params.get("client_id")
    feed_source_id = (
        request.path_params.get("feed_source_id")
        or request.query_params.get("feed_source_id")
    )
    if client_id is not None:
        try:
            client_id_int = int(client_id)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="client_id must be an integer",
            )
        if client_id_int not in user.client_ids:
            raise HTTPException(status_code=404, detail="client not found")
        return
    if feed_source_id is not None:
        if db_session is None:
            return  # handler will raise 503 (database unavailable)
        from .models.feed_source import FeedSource

        try:
            feed_source_id_int = int(feed_source_id)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="feed_source_id must be an integer",
            )
        feed_source = await db_session.get(FeedSource, feed_source_id_int)
        feed_client_id = feed_source.client_id if feed_source is not None else None
        # Close the implicitly-begun read transaction so handlers can start
        # their own `session.begin()` without InvalidRequestError.
        await db_session.rollback()
        if feed_client_id is None or feed_client_id not in user.client_ids:
            raise HTTPException(status_code=404, detail="feed source not found")


async def ensure_feed_source_access(
    db_session: AsyncSession | None,
    user: CurrentUser,
    feed_source_id: int,
) -> None:
    """Scope check for routes that carry feed_source_id in the request body
    (plugin preview routes) — router-level path/query enforcement cannot see
    body params. Raises 404 for unknown or unassigned feed sources. Call
    BEFORE beginning a transaction on db_session (performs its own rollback).
    """
    if user.client_ids is None:
        return
    if db_session is None:
        return  # handler will raise 503 (database unavailable)
    from .models.feed_source import FeedSource

    feed_source = await db_session.get(FeedSource, feed_source_id)
    feed_client_id = feed_source.client_id if feed_source is not None else None
    await db_session.rollback()
    if feed_client_id is None or feed_client_id not in user.client_ids:
        raise HTTPException(status_code=404, detail="feed source not found")


async def require_feed_source(
    db_session: AsyncSession, feed_source_id: int
) -> None:
    """Existence check shared by feed-source-scoped routes: raises 404 when
    the feed source does not exist. Callers run it inside their own
    transaction (async with session.begin()); no implicit rollback here."""
    from .models.feed_source import FeedSource

    if await db_session.get(FeedSource, feed_source_id) is None:
        raise HTTPException(status_code=404, detail="feed source not found")
