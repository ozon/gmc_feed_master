from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..config import Settings, get_settings
from ..db.engine import get_db_session
from ..export.service import generate_export_token
from ..export.store import ExportFileStore
from ..models.client import Client
from ..models.feed_source import FeedSource
from ..models.ingestion import IngestionRun
from ..pipeline import validate_cron
from ..schemas.clients import (
    ClientCreate,
    ClientOut,
    ClientUpdate,
    FeedSourceCreate,
    FeedSourceOut,
    FeedSourceUpdate,
    IngestionRunOut,
)

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _resolve_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = get_settings()
    return settings


def _scheduler(request: Request):
    return getattr(request.app.state, "scheduler_service", None)


def _locks(request: Request):
    return getattr(request.app.state, "lock_registry", None)


def _export_url(settings: Settings, token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/export/{token}.xml"


def _feed_source_out(feed_source: FeedSource, settings: Settings) -> dict:
    data = FeedSourceOut.model_validate(feed_source).model_dump()
    data["export_url"] = _export_url(settings, feed_source.export_token)
    return data


@router.post("/clients", status_code=201, response_model=ClientOut)
async def create_client(
    payload: ClientCreate,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> Client:
    session = _require_db(db_session)
    client = Client(
        name=payload.name,
        contact_details=payload.contact_details,
        status=payload.status,
    )
    try:
        async with session.begin():
            session.add(client)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="client name already exists") from exc
    return client


@router.get("/clients", response_model=list[ClientOut])
async def list_clients(
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[Client]:
    session = _require_db(db_session)
    result = await session.execute(select(Client).order_by(Client.name))
    return list(result.scalars())


@router.put("/clients/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: int,
    payload: ClientUpdate,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> Client:
    session = _require_db(db_session)
    updates = payload.model_dump(exclude_unset=True)
    try:
        async with session.begin():
            client = await session.get(Client, client_id)
            if client is None:
                raise HTTPException(status_code=404, detail="client not found")
            for key, value in updates.items():
                setattr(client, key, value)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="client name already exists") from exc
    await session.refresh(client)
    return client


@router.post("/clients/{client_id}/feed-sources", status_code=201, response_model=FeedSourceOut)
async def create_feed_source(
    client_id: int,
    payload: FeedSourceCreate,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    session = _require_db(db_session)
    if payload.cron_expression is not None:
        try:
            validate_cron(payload.cron_expression)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    feed_source = FeedSource(
        client_id=client_id, export_token=generate_export_token(), **payload.model_dump()
    )
    async with session.begin():
        if await session.get(Client, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        session.add(feed_source)
    scheduler = _scheduler(request)
    if scheduler is not None and feed_source.cron_expression:
        scheduler.register(feed_source)
    return _feed_source_out(feed_source, settings)


@router.get("/clients/{client_id}/feed-sources", response_model=list[FeedSourceOut])
async def list_feed_sources(
    client_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    session = _require_db(db_session)
    async with session.begin():
        if await session.get(Client, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
    result = await session.execute(
        select(FeedSource).where(FeedSource.client_id == client_id).order_by(FeedSource.name)
    )
    return [_feed_source_out(fs, settings) for fs in result.scalars()]


@router.put("/feed-sources/{feed_source_id}", response_model=FeedSourceOut)
async def update_feed_source(
    feed_source_id: int,
    payload: FeedSourceUpdate,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    session = _require_db(db_session)
    updates = payload.model_dump(exclude_unset=True)
    if "cron_expression" in updates and updates["cron_expression"] is not None:
        try:
            validate_cron(updates["cron_expression"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        for key, value in updates.items():
            setattr(feed_source, key, value)
    await session.refresh(feed_source)
    scheduler = _scheduler(request)
    if scheduler is not None and "cron_expression" in updates:
        if feed_source.cron_expression:
            scheduler.reschedule(feed_source)
        else:
            scheduler.unregister(feed_source_id)
    return _feed_source_out(feed_source, settings)


@router.delete("/feed-sources/{feed_source_id}", status_code=204)
async def delete_feed_source(
    feed_source_id: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        try:
            await session.delete(feed_source)
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="feed source has ingestion runs") from exc
    scheduler = _scheduler(request)
    if scheduler is not None:
        scheduler.unregister(feed_source_id)
    locks = _locks(request)
    if locks is not None:
        locks.discard(feed_source_id)
    settings = _resolve_settings(request)
    store = ExportFileStore(settings.export_dir)
    store.published_path(feed_source_id).unlink(missing_ok=True)
    versions_dir = Path(settings.export_dir) / "versions" / str(feed_source_id)
    if versions_dir.is_dir():
        import shutil

        shutil.rmtree(versions_dir, ignore_errors=True)


@router.post("/feed-sources/{feed_source_id}/export-token/rotate")
async def rotate_export_token(
    feed_source_id: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, str]:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        feed_source.export_token = generate_export_token()
        await session.flush()
        token = feed_source.export_token
    settings = _resolve_settings(request)
    return {"export_token": token, "export_url": _export_url(settings, token)}


@router.post("/feed-sources/{feed_source_id}/run", status_code=202)
async def trigger_run(
    feed_source_id: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, int]:
    session = _require_db(db_session)
    runner = getattr(request.app.state, "pipeline_runner", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="pipeline runner unavailable")
    async with session.begin():
        if await session.get(FeedSource, feed_source_id) is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        run = IngestionRun(feed_source_id=feed_source_id, status="pending")
        session.add(run)
    run_id = run.id
    task = asyncio.create_task(runner.execute(feed_source_id, run_id=run_id))
    background_tasks = getattr(request.app.state, "background_tasks", None)
    if background_tasks is not None:
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    return {"run_id": run_id}


@router.get("/feed-sources/{feed_source_id}/ingestion-runs", response_model=list[IngestionRunOut])
async def list_ingestion_runs(
    feed_source_id: int,
    limit: int = 50,
    offset: int = 0,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[IngestionRun]:
    session = _require_db(db_session)
    async with session.begin():
        if await session.get(FeedSource, feed_source_id) is None:
            raise HTTPException(status_code=404, detail="feed source not found")
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    result = await session.execute(
        select(IngestionRun)
        .where(IngestionRun.feed_source_id == feed_source_id)
        .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars())
