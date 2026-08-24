from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from .clock import Clock
from .config import Settings, get_settings
from .session_store import InMemorySessionStore, SessionStore


SESSION_COOKIE_NAME = "gmc_session"
_INVALID_CREDENTIALS = "Invalid credentials"


class Credentials(BaseModel):
    username: str
    password: str


def _settings(request: Request, settings: Settings = Depends(get_settings)) -> Settings:
    request.app.state.settings = settings
    return settings


def _clock(request: Request) -> Clock:
    return request.app.state.clock


def _store(request: Request, settings: Settings = Depends(_settings)) -> SessionStore:
    store = request.app.state.session_store
    if store is None:
        factory = request.app.state.db_session_factory
        if factory is not None:
            from .persistence.sessions import PostgresSessionStore

            store = PostgresSessionStore(
                factory,
                idle=timedelta(minutes=settings.session_idle_minutes),
                absolute=timedelta(hours=settings.session_absolute_hours),
                secret=settings.session_secret,
            )
        else:
            store = InMemorySessionStore(
                idle=timedelta(minutes=settings.session_idle_minutes),
                absolute=timedelta(hours=settings.session_absolute_hours),
                secret=settings.session_secret,
            )
        request.app.state.session_store = store
    return store


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_INVALID_CREDENTIALS,
    )


async def require_user(
    request: Request,
    store: SessionStore = Depends(_store),
    clock: Clock = Depends(_clock),
) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        raise _unauthorized()
    user_id = await store.validate(token, clock.now(), renew_idle=False)
    if user_id is None:
        raise _unauthorized()
    return user_id


async def require_user_for_interaction(
    request: Request,
    store: SessionStore = Depends(_store),
    clock: Clock = Depends(_clock),
) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        raise _unauthorized()
    user_id = await store.validate(token, clock.now(), renew_idle=True)
    if user_id is None:
        raise _unauthorized()
    return user_id


def authenticate(credentials: Credentials, settings: Settings) -> str:
    if credentials.username != settings.initial_username or credentials.password != settings.initial_password:
        raise _unauthorized()
    return credentials.username


async def create_session(store: SessionStore, clock: Clock, user_id: str) -> str:
    return await store.create(user_id, clock.now())


async def invalidate_session(store: SessionStore, token: str) -> None:
    await store.invalidate(token)


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        secure=True,
        samesite="lax",
    )
