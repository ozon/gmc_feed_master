from __future__ import annotations

from typing import Any

import jsonschema
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.client import Client
from ..models.feed_source import FeedSource
from ..models.plugin import Plugin, PluginConfig, PluginData
from ..schemas.plugins import EnabledPut

router = APIRouter()

_DEFAULT_KEY = "default"

_BOTH_SCOPES_ERROR = "pass at most one of client_id, feed_source_id"
_UNDECLARED_SCOPE_ERROR = "scope not declared for this plugin"


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _validation_error(message: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"errors": [message]})


async def _get_plugin_by_name(session: AsyncSession, plugin_id: str) -> Plugin:
    result = await session.execute(
        select(Plugin).where(Plugin.name == plugin_id).order_by(Plugin.id)
    )
    plugin = result.scalars().first()
    if plugin is None:
        raise HTTPException(status_code=404, detail="plugin not found")
    return plugin


def _declared_scopes(manifest: dict[str, Any], scope_kind: str) -> tuple[str, ...]:
    value = (manifest or {}).get(scope_kind)
    if value is None:
        return ("global",)
    if isinstance(value, str):
        return (value,)
    return tuple(str(scope) for scope in value)


async def _resolve_target(
    plugin_id: str,
    client_id: int | None,
    feed_source_id: int | None,
    db_session: AsyncSession,
    scope_kind: str,
) -> tuple[Plugin, str, int | None, int | None] | JSONResponse:
    plugin = await _get_plugin_by_name(db_session, plugin_id)
    if client_id is not None and feed_source_id is not None:
        return _validation_error(_BOTH_SCOPES_ERROR)
    if client_id is not None:
        scope = "client"
    elif feed_source_id is not None:
        scope = "feed_source"
    else:
        scope = "global"
    if scope != "global" and scope not in _declared_scopes(plugin.manifest, scope_kind):
        return _validation_error(_UNDECLARED_SCOPE_ERROR)
    if client_id is not None and await db_session.get(Client, client_id) is None:
        raise HTTPException(status_code=404, detail="client not found")
    if (
        feed_source_id is not None
        and await db_session.get(FeedSource, feed_source_id) is None
    ):
        raise HTTPException(status_code=404, detail="feed source not found")
    return plugin, scope, client_id, feed_source_id


def _owner_filters(
    model: type[PluginConfig] | type[PluginData],
    scope: str,
    client_id: int | None,
    feed_source_id: int | None,
) -> list[Any]:
    if scope == "client":
        return [model.client_id == client_id]
    if scope == "feed_source":
        return [model.feed_source_id == feed_source_id]
    return [model.client_id.is_(None), model.feed_source_id.is_(None)]


@router.get("/plugins")
async def list_plugins(
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[dict[str, Any]]:
    session = _require_db(db_session)
    result = await session.execute(select(Plugin).order_by(Plugin.id))
    return [
        {
            "id": plugin.name,
            "name": (plugin.manifest or {}).get("name", plugin.name),
            "version": plugin.version,
            "enabled": plugin.enabled,
            "manifest": plugin.manifest,
        }
        for plugin in result.scalars()
    ]


@router.put("/plugins/{plugin_id}/enabled")
async def set_plugin_enabled(
    plugin_id: str,
    payload: EnabledPut,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, str]:
    session = _require_db(db_session)
    async with session.begin():
        plugin = await _get_plugin_by_name(session, plugin_id)
        plugin.enabled = payload.enabled
    return {"status": "ok"}


@router.get("/plugins/{plugin_id}/config", response_model=None)
async def get_plugin_config(
    plugin_id: str,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any] | JSONResponse:
    return await _get_payload(
        plugin_id, client_id, feed_source_id, PluginConfig, "config", "config_scope", db_session
    )


@router.put("/plugins/{plugin_id}/config", response_model=None)
async def put_plugin_config(
    plugin_id: str,
    payload: dict[str, Any],
    client_id: int | None = None,
    feed_source_id: int | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, str] | JSONResponse:
    return await _put_payload(
        plugin_id,
        payload,
        client_id,
        feed_source_id,
        PluginConfig,
        "config",
        "config_scope",
        "config_schema",
        db_session,
    )


@router.get("/plugins/{plugin_id}/data", response_model=None)
async def get_plugin_data(
    plugin_id: str,
    client_id: int | None = None,
    feed_source_id: int | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any] | JSONResponse:
    return await _get_payload(
        plugin_id, client_id, feed_source_id, PluginData, "data", "data_scope", db_session
    )


@router.put("/plugins/{plugin_id}/data", response_model=None)
async def put_plugin_data(
    plugin_id: str,
    payload: dict[str, Any],
    client_id: int | None = None,
    feed_source_id: int | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, str] | JSONResponse:
    return await _put_payload(
        plugin_id,
        payload,
        client_id,
        feed_source_id,
        PluginData,
        "data",
        "data_scope",
        "data_schema",
        db_session,
    )


async def _get_payload(
    plugin_id: str,
    client_id: int | None,
    feed_source_id: int | None,
    model: type[PluginConfig] | type[PluginData],
    column_name: str,
    scope_kind: str,
    db_session: AsyncSession | None,
) -> dict[str, Any] | JSONResponse:
    session = _require_db(db_session)
    resolved = await _resolve_target(
        plugin_id, client_id, feed_source_id, session, scope_kind
    )
    if isinstance(resolved, JSONResponse):
        return resolved
    plugin, scope, resolved_client_id, resolved_feed_source_id = resolved
    stmt = select(getattr(model, column_name)).where(
        model.plugin_id == plugin.id,
        model.scope == scope,
        model.key == _DEFAULT_KEY,
        *_owner_filters(model, scope, resolved_client_id, resolved_feed_source_id),
    )
    row = (await session.execute(stmt)).first()
    return row[0] if row else {}


async def _put_payload(
    plugin_id: str,
    payload: dict[str, Any],
    client_id: int | None,
    feed_source_id: int | None,
    model: type[PluginConfig] | type[PluginData],
    column_name: str,
    scope_kind: str,
    schema_key: str,
    db_session: AsyncSession | None,
) -> dict[str, str] | JSONResponse:
    session = _require_db(db_session)
    async with session.begin():
        resolved = await _resolve_target(
            plugin_id, client_id, feed_source_id, session, scope_kind
        )
        if isinstance(resolved, JSONResponse):
            return resolved
        plugin, scope, resolved_client_id, resolved_feed_source_id = resolved
        schema = (plugin.manifest or {}).get(schema_key)
        if isinstance(schema, dict):
            try:
                jsonschema.validate(payload, schema)
            except (jsonschema.ValidationError, jsonschema.SchemaError) as exc:
                return _validation_error(exc.message)
        await session.execute(
            delete(model).where(
                model.plugin_id == plugin.id,
                model.scope == scope,
                model.key == _DEFAULT_KEY,
                *_owner_filters(model, scope, resolved_client_id, resolved_feed_source_id),
            )
        )
        session.add(
            model(
                plugin_id=plugin.id,
                scope=scope,
                client_id=resolved_client_id if scope == "client" else None,
                feed_source_id=resolved_feed_source_id if scope == "feed_source" else None,
                key=_DEFAULT_KEY,
                **{column_name: payload},
            )
        )
    return {"status": "ok"}