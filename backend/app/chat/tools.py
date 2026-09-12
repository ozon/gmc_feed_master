from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser
from ..models.export import ExportRun
from ..models.feed_source import FeedSource
from ..models.quality import QualityFinding
from ..models.staging import StagingProduct

logger = logging.getLogger(__name__)

_MAX_TEXT = 500


class _StagingProductsArgs(BaseModel):
    feed_source_id: int | None = None
    search: str | None = None
    status: str = "active"
    limit: int = Field(default=20, ge=1, le=50)


class _FindingsArgs(BaseModel):
    feed_source_id: int | None = None
    severity: str | None = None
    limit: int = Field(default=20, ge=1, le=50)


class _ExportRunsArgs(BaseModel):
    feed_source_id: int | None = None
    limit: int = Field(default=20, ge=1, le=50)


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + "…"
    return value


def _feed_scope(user: CurrentUser):
    if user.client_ids is None:
        return None
    return FeedSource.client_id.in_(user.client_ids)


async def _visible_feed_source(
    session: AsyncSession, user: CurrentUser, feed_source_id: int
) -> FeedSource | None:
    feed_source = await session.get(FeedSource, feed_source_id)
    if feed_source is None:
        return None
    if user.client_ids is not None and feed_source.client_id not in user.client_ids:
        return None
    return feed_source


async def _list_feed_sources(session: AsyncSession, user: CurrentUser) -> dict[str, Any]:
    stmt = select(FeedSource.id, FeedSource.name, FeedSource.client_id, FeedSource.source_format)
    scope = _feed_scope(user)
    if scope is not None:
        stmt = stmt.where(scope)
    rows = (await session.execute(stmt.order_by(FeedSource.id).limit(50))).all()
    return {"feed_sources": [
        {"id": r.id, "name": _truncate(r.name), "client_id": r.client_id,
         "source_format": r.source_format}
        for r in rows
    ]}


async def _query_staging_products(
    session: AsyncSession, user: CurrentUser, args: _StagingProductsArgs
) -> dict[str, Any]:
    stmt = select(
        StagingProduct.feed_source_id, StagingProduct.product_id,
        StagingProduct.raw_data["title"].astext, StagingProduct.status,
    ).where(StagingProduct.status == args.status if args.status != "all" else true())
    if args.feed_source_id is not None:
        feed_source = await _visible_feed_source(session, user, args.feed_source_id)
        if feed_source is None:
            return {"error": "feed source not found"}
        stmt = stmt.where(StagingProduct.feed_source_id == args.feed_source_id)
    else:
        scope = _feed_scope(user)
        if scope is not None:
            stmt = stmt.join(FeedSource, StagingProduct.feed_source_id == FeedSource.id).where(scope)
    if args.search:
        stmt = stmt.where(StagingProduct.raw_data["title"].astext.ilike(f"%{args.search}%"))
    rows = (await session.execute(stmt.order_by(StagingProduct.id).limit(args.limit))).all()
    return {"products": [
        {"feed_source_id": r.feed_source_id, "product_id": r.product_id,
         "title": _truncate(r[2]), "status": r.status}
        for r in rows
    ]}


async def _query_qc_findings(
    session: AsyncSession, user: CurrentUser, args: _FindingsArgs
) -> dict[str, Any]:
    stmt = select(QualityFinding)
    if args.feed_source_id is not None:
        feed_source = await _visible_feed_source(session, user, args.feed_source_id)
        if feed_source is None:
            return {"error": "feed source not found"}
        stmt = stmt.where(QualityFinding.feed_source_id == args.feed_source_id)
    else:
        scope = _feed_scope(user)
        if scope is not None:
            stmt = stmt.join(FeedSource, QualityFinding.feed_source_id == FeedSource.id).where(scope)
    if args.severity:
        stmt = stmt.where(QualityFinding.severity == args.severity)
    rows = (await session.execute(stmt.order_by(QualityFinding.id.desc()).limit(args.limit))).scalars()
    return {"findings": [
        {"feed_source_id": f.feed_source_id, "product_id": f.product_id,
         "severity": f.severity, "code": f.code, "field": f.field,
         "message": _truncate(f.message)}
        for f in rows
    ]}


async def _query_export_runs(
    session: AsyncSession, user: CurrentUser, args: _ExportRunsArgs
) -> dict[str, Any]:
    stmt = select(ExportRun)
    if args.feed_source_id is not None:
        feed_source = await _visible_feed_source(session, user, args.feed_source_id)
        if feed_source is None:
            return {"error": "feed source not found"}
        stmt = stmt.where(ExportRun.feed_source_id == args.feed_source_id)
    else:
        scope = _feed_scope(user)
        if scope is not None:
            stmt = stmt.join(FeedSource, ExportRun.feed_source_id == FeedSource.id).where(scope)
    rows = (await session.execute(stmt.order_by(ExportRun.id.desc()).limit(args.limit))).scalars()
    return {"export_runs": [
        {"id": r.id, "feed_source_id": r.feed_source_id, "status": r.status,
         "product_count": r.product_count,
         "critical": r.critical_finding_count, "warning": r.warning_finding_count,
         "info": r.info_finding_count,
         "started_at": r.started_at.isoformat()}
        for r in rows
    ]}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "list_feed_sources",
        "description": "List the feed sources visible to the current user.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "query_staging_products",
        "description": "Search staging products by title text, optionally filtered by feed source and status.",
        "parameters": {"type": "object", "properties": {
            "feed_source_id": {"type": "integer"},
            "search": {"type": "string"},
            "status": {"type": "string", "enum": ["active", "removed", "all"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        }},
    }},
    {"type": "function", "function": {
        "name": "query_qc_findings",
        "description": "Query current quality-check findings, optionally filtered by feed source and severity.",
        "parameters": {"type": "object", "properties": {
            "feed_source_id": {"type": "integer"},
            "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        }},
    }},
    {"type": "function", "function": {
        "name": "query_export_runs",
        "description": "Query export run history with finding counts per run.",
        "parameters": {"type": "object", "properties": {
            "feed_source_id": {"type": "integer"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        }},
    }},
]


async def execute_tool(
    session: AsyncSession, user: CurrentUser, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    try:
        if name == "list_feed_sources":
            return await _list_feed_sources(session, user)
        if name == "query_staging_products":
            return await _query_staging_products(session, user, _StagingProductsArgs(**arguments))
        if name == "query_qc_findings":
            return await _query_qc_findings(session, user, _FindingsArgs(**arguments))
        if name == "query_export_runs":
            return await _query_export_runs(session, user, _ExportRunsArgs(**arguments))
        return {"error": f"unknown tool {name!r}"}
    except ValidationError as exc:
        return {"error": f"invalid arguments: {exc.errors()[0]['msg']}"}
    except Exception:
        logger.exception("chat tool %s failed", name)
        return {"error": "tool execution failed"}
