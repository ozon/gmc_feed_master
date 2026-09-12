from __future__ import annotations

from typing import Any

DEFAULT_TARGET_FIELDS = ["color", "material", "size", "gtin"]


def validate_config(config: Any) -> None:
    if not isinstance(config, dict):
        raise TypeError("config must be an object")
    fields = config.get("targetFields", DEFAULT_TARGET_FIELDS)
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(f, str) and f for f in fields)
    ):
        raise ValueError("targetFields must be a non-empty list of non-empty strings")


class EnrichmentPlugin:
    """Pipeline module applying accepted AI enrichment values (pins) by product id."""

    def validate_config(self, config: Any) -> None:
        validate_config(config)

    def prepare_run(self, config: Any, data: Any, ctx: Any) -> dict[str, Any]:
        return {"pinned": (data or {}).get("pinned") or {}}

    def process(
        self,
        product: dict[str, Any],
        config: Any,
        data: Any,
        ctx: Any,
        state: Any = None,
    ) -> dict[str, Any]:
        pinned = (state or {}).get("pinned") or {}
        values = pinned.get(str(product.get("id", "")))
        if not values:
            return product
        result = dict(product)
        for field, value in values.items():
            result[field] = value  # pinned wins over feed values (spec: explicit user decision)
        return result

    def register_routes(self, router: Any) -> None:
        import asyncio

        from fastapi import Depends, HTTPException, Request
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel, Field
        from sqlalchemy import or_, select

        from app.access import CurrentUser, ensure_feed_source_access, get_current_user
        from app.db.engine import get_db_session
        from app.models.feed_source import FeedSource
        from app.models.plugin import PluginConfig, PluginData
        from app.models.staging import StagingProduct
        from app.routes.plugins import _get_payload, _put_payload

        class ScanRequest(BaseModel):
            feed_source_id: int
            limit: int = Field(default=20, ge=1, le=50)

        async def scan(payload: ScanRequest, request: Request,
                       user: CurrentUser = Depends(get_current_user),  # noqa: B008 — plugin-route convention (see category plugin)
                       db_session: Any = Depends(get_db_session)) -> dict[str, Any] | JSONResponse:  # noqa: B008
            service = getattr(request.app.state, "ai_service", None)
            if service is None:
                raise HTTPException(status_code=503, detail="ai service unavailable")
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, payload.feed_source_id)

            # -- read phase (own transaction via helpers/short block) ------------
            config, _version = await _get_payload(
                "enrichment", None, payload.feed_source_id,
                PluginConfig, "config", "config_scope", db_session, user,
            )
            if isinstance(config, JSONResponse):
                return config
            target_fields = list((config or {}).get("targetFields") or DEFAULT_TARGET_FIELDS)
            data, version = await _get_payload(
                "enrichment", None, payload.feed_source_id,
                PluginData, "data", "data_scope", db_session, user,
            )
            if isinstance(data, JSONResponse):
                return data
            # _get_payload's selects autobegin a read transaction; close it so
            # the staging query below can open its own.
            await db_session.rollback()
            async with db_session.begin():
                feed_source = await db_session.get(FeedSource, payload.feed_source_id)
                if feed_source is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                conditions = []
                for field_name in target_fields:
                    col = StagingProduct.raw_data[field_name].astext
                    conditions.append(col.is_(None))
                    conditions.append(col == "")
                rows = (await db_session.execute(
                    select(StagingProduct.product_id, StagingProduct.raw_data)
                    .where(
                        StagingProduct.feed_source_id == payload.feed_source_id,
                        StagingProduct.status == "active",
                        StagingProduct.excluded.is_(False),
                        or_(*conditions),
                    )
                    .order_by(StagingProduct.id)
                    .limit(payload.limit)
                )).all()

            # -- AI phase (no session held) ---------------------------------------
            candidates: list[tuple[str, dict[str, Any]]] = []
            for product_id, raw in rows:
                raw_dict = dict(raw) if raw else {}
                pinned_values = ((data or {}).get("pinned") or {}).get(product_id) or {}
                missing = [f for f in target_fields if not str(raw_dict.get(f) or "")]
                if missing and all(f in pinned_values for f in missing):
                    continue
                candidates.append((product_id, raw_dict))

            results = await asyncio.gather(*[
                service.run_task(
                    "attribute_enrichment",
                    {"title": raw.get("title"), "description": raw.get("description")},
                    client_id=feed_source.client_id,
                    feed_source_id=payload.feed_source_id,
                )
                for _pid, raw in candidates
            ])

            suggestions = dict((data or {}).get("suggestions") or {})
            failed = 0
            with_suggestions = 0
            for (product_id, _raw), result in zip(candidates, results):
                if result.status == "fallback" or not isinstance(result.value, dict):
                    failed += 1
                    continue
                values = {k: str(v) for k, v in result.value.items() if v not in (None, "")}
                if values:
                    suggestions[product_id] = values
                    with_suggestions += 1

            # -- write phase (helper manages its own transaction) ------------------
            new_data = {"suggestions": suggestions, "pinned": (data or {}).get("pinned") or {}}
            outcome = await _put_payload(
                "enrichment", new_data, None, payload.feed_source_id,
                PluginData, "data", "data_scope", "data_schema",
                str(version) if version is not None else None,
                db_session, user,
            )
            if isinstance(outcome, JSONResponse):
                return outcome
            return {
                "scanned": len(candidates),
                "with_suggestions": with_suggestions,
                "failed": failed,
            }

        scan.__annotations__.update({
            "payload": ScanRequest, "request": Request, "user": CurrentUser,
            "db_session": Any, "return": dict[str, Any] | JSONResponse,
        })
        router.post("/scan", response_model=None)(scan)
