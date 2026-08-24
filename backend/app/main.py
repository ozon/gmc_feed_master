from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi import Depends, FastAPI, Request, Response

from .auth import (
    Credentials,
    SESSION_COOKIE_NAME,
    authenticate,
    clear_session_cookie,
    create_session,
    require_user,
    require_user_for_interaction,
    set_session_cookie,
    _store,
    invalidate_session,
)
from .clock import Clock, SystemClock
from .config import Settings, get_settings
from .session_store import SessionStore
from .persistence.sessions import PostgresSessionStore

def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    clock: Clock | None = None,
    db_session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.state.session_store = session_store
    app.state.db_session_factory = db_session_factory
    app.state.clock = clock if clock is not None else SystemClock()
    if settings is not None:
        app.dependency_overrides.setdefault(get_settings, lambda: settings)
        if session_store is None and db_session_factory is not None:
            app.state.session_store = PostgresSessionStore(
                db_session_factory,
                idle=timedelta(minutes=settings.session_idle_minutes),
                absolute=timedelta(hours=settings.session_absolute_hours),
                secret=settings.session_secret,
            )

    @app.get("/health")
    def health(_settings: Settings = Depends(get_settings)) -> dict[str, str]:
        app.state.settings = _settings
        return {"status": "ok"}

    @app.post("/auth/login")
    async def login(
        credentials: Credentials,
        response: Response,
        settings: Settings = Depends(get_settings),
        store: SessionStore = Depends(_store),
    ) -> dict[str, str]:
        user_id = authenticate(credentials, settings)
        token = await create_session(store, app.state.clock, user_id)
        set_session_cookie(response, token, settings.session_absolute_hours * 60 * 60)
        return {"username": user_id}

    @app.post("/auth/logout")
    async def logout(
        request: Request,
        response: Response,
        request_user: str = Depends(require_user),
        store: SessionStore = Depends(_store),
    ) -> dict[str, str]:
        # Dependencies validate the token before it is invalidated.
        del request_user
        token = request.cookies[SESSION_COOKIE_NAME]
        await invalidate_session(store, token)
        clear_session_cookie(response)
        return {"status": "ok"}

    @app.get("/auth/me")
    def me(username: str = Depends(require_user)) -> dict[str, str]:
        return {"username": username}

    @app.post("/auth/interaction")
    def interaction(username: str = Depends(require_user_for_interaction)) -> dict[str, str]:
        return {"username": username}

    return app


app = create_app()
