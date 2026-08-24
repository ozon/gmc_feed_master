from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import ValidationError

from .auth import (
    Credentials,
    PasswordChange,
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
from .db.engine import create_engine, create_session_factory, get_db_session
from .persistence.users import change_password, seed_initial_user


def _configured_settings() -> Settings | None:
    try:
        return get_settings()
    except ValidationError:
        # Keep `import app.main` safe for M0 environments that do not yet have
        # the persistence credentials configured.
        return None

def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    clock: Clock | None = None,
    db_session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    if settings is None and session_store is None and db_session_factory is None:
        settings = _configured_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if (
            application.state.db_session_factory is not None
            and settings is not None
            and not application.state.session_store_injected
        ):
            async with application.state.db_session_factory() as session:
                await seed_initial_user(
                    session, settings.initial_username, settings.initial_password
                )
        yield
        if getattr(application.state, "db_engine", None) is not None:
            await application.state.db_engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.state.session_store = session_store
    app.state.session_store_injected = session_store is not None
    app.state.db_session_factory = db_session_factory
    app.state.db_engine = None
    app.state.clock = clock if clock is not None else SystemClock()
    if settings is not None:
        app.dependency_overrides.setdefault(get_settings, lambda: settings)
        if app.state.db_session_factory is None and session_store is None:
            app.state.db_engine = create_engine(settings)
            app.state.db_session_factory = create_session_factory(app.state.db_engine)
        if session_store is None and app.state.db_session_factory is not None:
            app.state.session_store = PostgresSessionStore(
                app.state.db_session_factory,
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
        request: Request,
        response: Response,
        settings: Settings = Depends(get_settings),
        store: SessionStore = Depends(_store),
        db_session: AsyncSession | None = Depends(get_db_session),
    ) -> dict[str, str]:
        user_id = await authenticate(
            credentials,
            settings,
            None if request.app.state.session_store_injected else db_session,
        )
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

    @app.post("/auth/password")
    async def password(
        payload: PasswordChange,
        request: Request,
        response: Response,
        request_user: str = Depends(require_user),
        db_session: AsyncSession | None = Depends(get_db_session),
    ) -> dict[str, str]:
        if request.app.state.session_store_injected:
            raise HTTPException(
                status_code=501,
                detail="Password changes require the configured PostgreSQL persistence boundary",
            )
        token = request.cookies[SESSION_COOKIE_NAME]
        if db_session is None or not await change_password(
            db_session, request_user, payload.current_password, payload.new_password
        ):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        await invalidate_session(request.app.state.session_store, token)
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
