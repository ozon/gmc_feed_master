from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .access import CurrentUser, enforce_scope_access, get_current_user
from .auth import (
    SESSION_COOKIE_NAME,
    Credentials,
    PasswordChange,
    _store,
    authenticate,
    clear_session_cookie,
    require_user,
    require_user_for_interaction,
    set_session_cookie,
)
from .clock import Clock, SystemClock
from .config import API_PREFIX, Settings, get_settings
from .db.engine import create_engine, create_session_factory, get_db_session
from .event_log import audit
from .ingest import HttpFetcher
from .logging_setup import configure_logging
from .middleware import RequestContextMiddleware
from .persistence.sessions import PostgresSessionStore
from .persistence.users import change_password, seed_initial_user
from .routes import (
    admin_router,
    ai_admin_router,
    chat_router,
    clients_router,
    export_history_router,
    export_public_router,
    field_mapping_router,
    logs_router,
    plugins_router,
    quality_router,
    registry_router,
)
from .routes.dashboard import router as dashboard_router
from .routes.dry_run import router as dry_run_router
from .routes.feed_dashboard import router as feed_dashboard_router
from .routes.pipeline import router as pipeline_router
from .routes.products import router as products_router
from .session_store import SessionStore


def _configured_settings() -> Settings | None:
    try:
        return get_settings()
    except ValidationError:
        # Keep `import app.main` safe for M0 environments that do not yet have
        # the persistence credentials configured.
        return None


_EXPORT_PATH_PREFIX = "/export/"
_EXPORT_PATH_REDACTED = "/export/[REDACTED]"

_SHUTDOWN_DRAIN_TIMEOUT = 10.0


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
    configure_logging(settings)

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

                from .pipeline.scheduler import (
                    INGESTION_PURGE_JOB_ID,
                    PURGE_CRON,
                    SYSTEM_PURGE_JOB_ID,
                )
                from .staging.purge import purge_expired, purge_expired_ingestion_runs

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

                async def run_ingestion_run_purge() -> None:
                    counts = await purge_expired_ingestion_runs(
                        application.state.db_session_factory,
                        datetime.now(timezone.utc),
                    )
                    logging.getLogger(__name__).info(
                        "ingestion run purge: %s runs purged, "
                        "%s export runs detached, %s findings deleted",
                        counts.runs_purged,
                        counts.export_runs_detached,
                        counts.findings_deleted,
                    )

                scheduler_service.register_system_job(
                    INGESTION_PURGE_JOB_ID, PURGE_CRON, run_ingestion_run_purge
                )

                from .ai.purge import AI_PURGE_JOB_ID, purge_expired_ai

                async def run_ai_purge() -> None:
                    counts = await purge_expired_ai(
                        application.state.db_session_factory,
                        datetime.now(timezone.utc),
                    )
                    logging.getLogger(__name__).info(
                        "ai purge: %s usage rows",
                        counts.usage_rows,
                    )

                scheduler_service.register_system_job(
                    AI_PURGE_JOB_ID, PURGE_CRON, run_ai_purge
                )

                from .event_log import (
                    DEFAULT_EVENT_LOG_RETENTION_DAYS,
                    EVENT_LOG_PURGE_JOB_ID,
                    purge_expired_events,
                )

                async def run_event_log_purge() -> None:
                    counts = await purge_expired_events(
                        application.state.db_session_factory,
                        datetime.now(timezone.utc),
                        default_days=(
                            settings.event_log_retention_days
                            if settings is not None
                            else DEFAULT_EVENT_LOG_RETENTION_DAYS
                        ),
                    )
                    logging.getLogger(__name__).info(
                        "event log purge: %s rows", counts.rows
                    )

                scheduler_service.register_system_job(
                    EVENT_LOG_PURGE_JOB_ID, PURGE_CRON, run_event_log_purge
                )

                from .ai.model_catalog import (
                    MODEL_CATALOG_REFRESH_CRON,
                    MODEL_CATALOG_REFRESH_JOB_ID,
                    make_refresh_job,
                )

                catalog_job = make_refresh_job(
                    application.state.db_session_factory,
                    application.state.catalog_http_client,
                    application.state.clock,
                )
                scheduler_service.register_system_job(
                    MODEL_CATALOG_REFRESH_JOB_ID, MODEL_CATALOG_REFRESH_CRON, catalog_job
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
        background_tasks = getattr(application.state, "background_tasks", None)
        if background_tasks:
            _done, pending = await asyncio.wait(
                set(background_tasks), timeout=_SHUTDOWN_DRAIN_TIMEOUT
            )
            if pending:
                logging.getLogger(__name__).warning(
                    "shutdown drain: %d background task(s) still pending; "
                    "they will be reconciled on next startup",
                    len(pending),
                )
        scheduler_service = getattr(application.state, "scheduler_service", None)
        if scheduler_service is not None:
            await scheduler_service.shutdown()
        image_http_client = getattr(application.state, "image_http_client", None)
        if image_http_client is not None:
            await image_http_client.aclose()
        catalog_http_client = getattr(application.state, "catalog_http_client", None)
        if catalog_http_client is not None:
            await catalog_http_client.aclose()
        if getattr(application.state, "db_engine", None) is not None:
            await application.state.db_engine.dispose()

    app = FastAPI(
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=f"{API_PREFIX}/redoc",
    )
    api = APIRouter(prefix=API_PREFIX)
    app.add_middleware(RequestContextMiddleware)
    api.include_router(clients_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(dashboard_router)
    api.include_router(dry_run_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(export_history_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(export_public_router)
    api.include_router(feed_dashboard_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(field_mapping_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(pipeline_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(plugins_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(products_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(quality_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(registry_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(admin_router)
    api.include_router(ai_admin_router)
    api.include_router(chat_router)
    api.include_router(logs_router)
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

        from .pipeline import (
            LockRegistry,
            PipelineRunner,
            SchedulerService,
            default_steps,
        )
        from .qc.image_probe import ImageProbeImpl

        image_http_client = httpx.AsyncClient()
        app.state.image_http_client = image_http_client
        app.state.catalog_http_client = httpx.AsyncClient()
        active_fetcher = fetcher if fetcher is not None else HttpFetcher()
        app.state.fetcher = active_fetcher
        image_probe = ImageProbeImpl(app.state.db_session_factory, image_http_client)
        app.state.image_probe = image_probe
        lock_registry = LockRegistry()
        from .ai import AiService

        ai_service = AiService(
            app.state.db_session_factory, clock=app.state.clock, settings=settings
        )
        steps = default_steps(
            active_fetcher,
            load_registry(),
            app.state.plugin_registry,
            clock=app.state.clock,
            image_probe=image_probe,
            export_dir=settings.export_dir if settings is not None else None,
            public_base_url=settings.public_base_url if settings is not None else None,
            ai_service=ai_service,
        )
        runner = PipelineRunner(lock_registry, app.state.db_session_factory, list(steps))
        scheduler_service = SchedulerService(runner)
        app.state.lock_registry = lock_registry
        app.state.pipeline_runner = runner
        app.state.scheduler_service = scheduler_service
        app.state.ai_service = ai_service

    @app.get("/health")
    def health(_settings: Settings = Depends(get_settings)) -> dict[str, str]:
        app.state.settings = _settings
        return {"status": "ok"}

    @api.post("/auth/login")
    async def login(
        credentials: Credentials,
        request: Request,
        response: Response,
        settings: Settings = Depends(get_settings),
        store: SessionStore = Depends(_store),
        db_session: AsyncSession | None = Depends(get_db_session),
    ) -> dict[str, str]:
        try:
            user_id = await authenticate(
                credentials,
                settings,
                None if request.app.state.session_store_injected else db_session,
            )
        except HTTPException:
            if db_session is not None:
                try:
                    # authenticate leaves an implicit read transaction open; close
                    # it so the audit row can commit.
                    await db_session.rollback()
                    async with db_session.begin():
                        await audit(
                            db_session,
                            "auth.login.failure",
                            target_type="user",
                            target_id=credentials.username,
                        )
                except Exception:
                    logging.getLogger(__name__).warning(
                        "login failure audit write failed", exc_info=True
                    )
            raise
        token = await store.create(user_id, app.state.clock.now())
        set_session_cookie(response, token, settings.session_absolute_hours * 60 * 60)
        if db_session is not None:
            try:
                await db_session.rollback()
                async with db_session.begin():
                    await audit(
                        db_session,
                        "auth.login.success",
                        target_type="user",
                        target_id=user_id,
                    )
            except Exception:
                logging.getLogger(__name__).warning(
                    "login success audit write failed", exc_info=True
                )
        return {"username": user_id}

    @api.post("/auth/logout")
    async def logout(
        request: Request,
        response: Response,
        request_user: str = Depends(require_user),
        store: SessionStore = Depends(_store),
        db_session: AsyncSession | None = Depends(get_db_session),
    ) -> dict[str, str]:
        # Dependencies validate the token before it is invalidated.
        token = request.cookies[SESSION_COOKIE_NAME]
        await store.invalidate(token)
        clear_session_cookie(response)
        if db_session is not None:
            try:
                async with db_session.begin():
                    await audit(
                        db_session,
                        "auth.logout",
                        target_type="user",
                        target_id=request_user,
                    )
            except Exception:
                logging.getLogger(__name__).warning(
                    "logout audit write failed", exc_info=True
                )
        return {"status": "ok"}

    @api.post("/auth/password")
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
        if db_session is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        async with db_session.begin():
            if not await change_password(
                db_session, request_user, payload.current_password, payload.new_password
            ):
                raise HTTPException(status_code=401, detail="Invalid credentials")
            await audit(
                db_session,
                "auth.password.change",
                target_type="user",
                target_id=request_user,
            )
        await request.app.state.session_store.invalidate(token)
        clear_session_cookie(response)
        return {"status": "ok"}

    @api.get("/auth/me")
    def me(user: CurrentUser = Depends(get_current_user)) -> dict:
        return {
            "username": user.username,
            "role": user.role,
            "client_ids": sorted(user.client_ids) if user.client_ids is not None else None,
        }

    @api.post("/auth/interaction")
    def interaction(username: str = Depends(require_user_for_interaction)) -> dict[str, str]:
        return {"username": username}

    app.include_router(api)

    return app


app = create_app()
