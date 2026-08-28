from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from registry.loader import load_registry

from ..auth import require_user
from ..db.engine import get_db_session
from ..ingest.fetch import FetchError
from ..models.feed_source import FeedSource
from ..pipeline.dry_run import run_dry_run

router = APIRouter()

_FINDING_SAMPLE_CAP = 5


class DryRunRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1)


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _group_findings(findings) -> dict:
    grouped: dict[str, dict[str, dict]] = {"critical": {}, "warning": {}, "info": {}}
    for finding in findings:
        bucket = grouped[finding.severity].setdefault(
            finding.rule_id, {"rule": finding.rule_id, "count": 0, "sample": []})
        bucket["count"] += 1
        if len(bucket["sample"]) < _FINDING_SAMPLE_CAP:
            bucket["sample"].append({"product_id": finding.product_id,
                                     "field": finding.field,
                                     "message": finding.message})
    return {severity: list(rules.values()) for severity, rules in grouped.items()}


@router.post("/feed-sources/{feed_source_id}/dry-run", response_model=None)
async def dry_run(
    feed_source_id: int,
    request: Request,
    payload: DryRunRequest | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict | JSONResponse:
    session = _require_db(db_session)
    async with session.begin():
        if await session.get(FeedSource, feed_source_id) is None:
            raise HTTPException(status_code=404, detail="feed source not found")

    state = request.app.state
    fetcher = getattr(state, "fetcher", None)
    image_probe = getattr(state, "image_probe", None)
    if fetcher is None or image_probe is None:
        raise HTTPException(status_code=503, detail="pipeline unavailable")

    try:
        result = await run_dry_run(
            session_factory=state.db_session_factory,
            feed_source_id=feed_source_id,
            fetcher=fetcher,
            registry=load_registry(),
            plugin_registry=getattr(state, "plugin_registry", {}),
            clock=state.clock,
            image_probe=image_probe,
            limit=payload.limit if payload else None,
        )
    except (FetchError, ValueError) as exc:
        return JSONResponse(status_code=422, content={"errors": [str(exc)]})

    return {
        "total": result.total,
        "processed": result.processed,
        "parse_errors": result.parse_errors,
        "dropped": [
            {"product_id": d["product_id"], "plugin_id": d["plugin_id"],
             "reason": f"{d['plugin_id']} dropped the product"}
            for d in result.dropped
        ],
        "findings": _group_findings(result.findings),
        "sample": result.sample,
    }
