from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
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
from .ingest import HttpFetcher
from .session_store import SessionStore
from .persistence.sessions import PostgresSessionStore
from .db.engine import create_engine, create_session_factory, get_db_session
from .persistence.users import change_password, seed_initial_user
from .routes import (
    clients_router,
    export_history_router,
    export_public_router,
    field_mapping_router,
    plugins_router,
    quality_router,
    registry_router,
)
from .routes.dashboard import router as dashboard_router
from .routes.dry_run import router as dry_run_router
from .routes.pipeline import router as pipeline_router
from .routes.products import router as products_router


def _configured_settings() -> Settings | None:
    try:
        return get_settings()
    except ValidationError:
        # Keep `import app.main` safe for M0 environments that do not yet have
        # the persistence credentials configured.
        return None


_EXPORT_PATH_PREFIX = "/export/"
_EXPORT_PATH_REDACTED = "/export/[REDACTED]"


class _ExportTokenRedactor(logging.Filter):
    # The public feed endpoint is fetched by Google at /export/{token}.xml;
    # uvicorn's default access log would otherwise write the token at INFO.
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if (
            isinstance(args, tuple)
            and len(args) == 5
            and isinstance(args[2], str)
            and args[2].startswith(_EXPORT_PATH_PREFIX)
        ):
            record.args = (args[0], args[1], _EXPORT_PATH_REDACTED, args[3], args[4])
        return True


def _install_export_token_log_redaction() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _ExportTokenRedactor) for f in access_logger.filters):
        access_logger.addFilter(_ExportTokenRedactor())

def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    clock: Clock | None = None,
    db_session_factory: async_sessionmaker[AsyncSession] | None = None,
    fetcher: HttpFetcher | None = None,
    plugins_dir: Path | str | None = None,
) -> FastAPI:
    if settings is None and session_store is None and db_session_factory is None:
        settings = _configured_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        _install_export_token_log_redaction()
        if (
            application.state.db_session_factory is not None
            and settings is not None
            and not application.state.session_store_injected
        ):
            async with application.state.db_session_factory() as session:
                await seed_initial_user(
                    session, settings.initial_username, settings.initial_password
                )
            if application.state.plugins_dir is not None:
                from .plugins.discovery import discover_and_mount

                await discover_and_mount(application)
            scheduler_service = getattr(application.state, "scheduler_service", None)
            if scheduler_service is not None:
                await scheduler_service.start()

                from datetime import datetime, timezone

                from .pipeline.scheduler import PURGE_CRON, SYSTEM_PURGE_JOB_ID
                from .staging.purge import purge_expired

                async def run_staging_purge() -> None:
                    counts = await purge_expired(
                        application.state.db_session_factory,
                        datetime.now(timezone.utc),
                    )
                    logging.getLogger(__name__).info(
                        "staging purge: %s removed products, %s history rows",
                        counts.removed_products,
                        counts.history_rows,
                    )

                scheduler_service.register_system_job(
                    SYSTEM_PURGE_JOB_ID, PURGE_CRON, run_staging_purge
                )

                from .pipeline.reconcile import reconcile_interrupted_runs

                reconciled = await reconcile_interrupted_runs(
                    application.state.db_session_factory, application.state.clock
                )
                logging.getLogger(__name__).info(
                    "startup reconciliation: marked %s orphaned runs as interrupted",
                    reconciled,
                )
                async with application.state.db_session_factory() as session:
                    await scheduler_service.register_all(session)
        yield
        scheduler_service = getattr(application.state, "scheduler_service", None)
        if scheduler_service is not None:
            await scheduler_service.shutdown()
        image_http_client = getattr(application.state, "image_http_client", None)
        if image_http_client is not None:
            await image_http_client.aclose()
        if getattr(application.state, "db_engine", None) is not None:
            await application.state.db_engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(clients_router)
    app.include_router(dashboard_router)
    app.include_router(dry_run_router)
    app.include_router(export_history_router)
    app.include_router(export_public_router)
    app.include_router(field_mapping_router)
    app.include_router(pipeline_router)
    app.include_router(plugins_router)
    app.include_router(products_router)
    app.include_router(quality_router)
    app.include_router(registry_router)
    app.state.settings = settings
    app.state.session_store = session_store
    app.state.session_store_injected = session_store is not None
    app.state.db_session_factory = db_session_factory
    app.state.db_engine = None
    app.state.plugins_dir = (
        Path(plugins_dir)
        if plugins_dir is not None
        else (Path(settings.plugins_dir) if settings is not None else None)
    )
    app.state.plugin_registry = {}
    app.state.background_tasks = set()
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

    if app.state.db_session_factory is not None:
        import httpx

        from registry.loader import load_registry

        from .pipeline import LockRegistry, PipelineRunner, SchedulerService, default_steps
        from .qc.image_probe import ImageProbeImpl

        image_http_client = httpx.AsyncClient()
        app.state.image_http_client = image_http_client
        active_fetcher = fetcher if fetcher is not None else HttpFetcher()
        app.state.fetcher = active_fetcher
        image_probe = ImageProbeImpl(app.state.db_session_factory, image_http_client)
        app.state.image_probe = image_probe
        lock_registry = LockRegistry()
        steps = default_steps(
            active_fetcher,
            load_registry(),
            app.state.plugin_registry,
            clock=app.state.clock,
            image_probe=image_probe,
            export_dir=settings.export_dir if settings is not None else None,
            public_base_url=settings.public_base_url if settings is not None else None,
        )
        runner = PipelineRunner(lock_registry, app.state.db_session_factory, list(steps))
        scheduler_service = SchedulerService(runner)
        app.state.lock_registry = lock_registry
        app.state.pipeline_runner = runner
        app.state.scheduler_service = scheduler_service

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
