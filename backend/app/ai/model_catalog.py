"""Model catalog service: syncs a browsable, priced model list from LiteLLM's
community-maintained pricing/context-window registry and exposes it to the
AI Provider Configuration wizard.

Source of truth: https://raw.githubusercontent.com/BerriAI/litellm/main/litellm/model_prices_and_context_window.json
This file is refreshed via `refresh_model_catalog()`, either from the
scheduled job (see `backend/app/ai/purge.py` for the equivalent job pattern)
or from `POST /admin/ai/model-catalog/refresh`.

Design notes (GFM-12):
- Fail-open: a failed refresh never clears the existing catalog. The caller
  gets the last successfully synced rows plus `last_synced_at` /
  `last_error` so the admin UI can show a staleness badge.
- Rows are keyed by `model_id` in LiteLLM's `vendor/model` format, matching
  what `AiProviderConfig.model` already stores (see `app/ai/router.py`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.presets import PROVIDER_PRESETS
from app.models.ai_model_catalog import AiModelCatalog

logger = logging.getLogger(__name__)

CATALOG_SOURCE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "litellm/model_prices_and_context_window.json"
)
_HTTP_TIMEOUT_S = 15.0
_SUPPORTED_LITELLM_PROVIDERS = {p.litellm_provider for p in PROVIDER_PRESETS if not p.is_custom}

# A short allow-list of well-known "safe default" models per vendor, used to
# flag `is_recommended` for the wizard's preselection. Kept intentionally
# small; anything else is still listed, just not preselected.
_RECOMMENDED_MODEL_IDS = {
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "anthropic/claude-3-5-sonnet-20241022",
    "gemini/gemini-1.5-flash",
    "mistral/mistral-large-latest",
    "groq/llama-3.1-70b-versatile",
}


@dataclass(slots=True)
class CatalogRefreshResult:
    synced_count: int
    skipped_count: int
    source: str
    synced_at: datetime
    error: str | None = None


def _to_per_mtok(cost_per_token: float | None) -> float | None:
    if cost_per_token is None:
        return None
    return round(cost_per_token * 1_000_000, 6)


def _parse_entry(raw_model_key: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    litellm_provider = entry.get("litellm_provider")
    if litellm_provider not in _SUPPORTED_LITELLM_PROVIDERS:
        return None
    if entry.get("mode") not in {"chat", "completion", None}:
        return None

    # LiteLLM's registry keys are already `vendor/model` for most providers,
    # but a handful are bare model names; normalize defensively.
    model_id = raw_model_key if "/" in raw_model_key else f"{litellm_provider}/{raw_model_key}"

    return {
        "model_id": model_id,
        "vendor": litellm_provider,
        "display_name": raw_model_key.split("/")[-1],
        "context_window": entry.get("max_input_tokens") or entry.get("max_tokens"),
        "max_output_tokens": entry.get("max_output_tokens"),
        "input_price_per_mtok": _to_per_mtok(entry.get("input_cost_per_token")),
        "output_price_per_mtok": _to_per_mtok(entry.get("output_cost_per_token")),
        "supports_vision": bool(entry.get("supports_vision", False)),
        "supports_function_calling": bool(entry.get("supports_function_calling", False)),
        "is_recommended": model_id in _RECOMMENDED_MODEL_IDS,
        "source": CATALOG_SOURCE_URL,
    }


async def fetch_catalog_payload(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S)
    try:
        resp = await client.get(CATALOG_SOURCE_URL)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns_client:
            await client.aclose()


async def refresh_model_catalog(session: AsyncSession) -> CatalogRefreshResult:
    """Fetch the upstream catalog and upsert it into `ai_model_catalog`.

    Never raises on network/parsing failure: the previous catalog rows are
    left untouched and the error is returned for the caller to log/surface.
    """
    now = datetime.now(timezone.utc)
    try:
        payload = await fetch_catalog_payload()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("model_catalog.refresh_failed", exc_info=exc)
        return CatalogRefreshResult(
            synced_count=0, skipped_count=0, source=CATALOG_SOURCE_URL,
            synced_at=now, error=str(exc),
        )

    rows: list[dict[str, Any]] = []
    skipped = 0
    for raw_key, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        parsed = _parse_entry(raw_key, entry)
        if parsed is None:
            skipped += 1
            continue
        parsed["last_synced_at"] = now
        rows.append(parsed)

    if not rows:
        return CatalogRefreshResult(
            synced_count=0, skipped_count=skipped, source=CATALOG_SOURCE_URL,
            synced_at=now, error="upstream payload contained no supported models",
        )

    stmt = pg_insert(AiModelCatalog).values(rows)
    update_cols = {
        c.name: getattr(stmt.excluded, c.name)
        for c in AiModelCatalog.__table__.columns
        if c.name not in {"id", "model_id"}
    }
    stmt = stmt.on_conflict_do_update(index_elements=["model_id"], set_=update_cols)
    await session.execute(stmt)
    await session.commit()

    logger.info("model_catalog.refreshed", extra={"synced": len(rows), "skipped": skipped})
    return CatalogRefreshResult(
        synced_count=len(rows), skipped_count=skipped, source=CATALOG_SOURCE_URL, synced_at=now,
    )


async def list_catalog_models(
    session: AsyncSession, *, vendor: str | None = None,
) -> list[AiModelCatalog]:
    stmt = select(AiModelCatalog).order_by(
        AiModelCatalog.is_recommended.desc(), AiModelCatalog.display_name,
    )
    if vendor:
        stmt = stmt.where(AiModelCatalog.vendor == vendor)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_catalog_status(session: AsyncSession) -> dict[str, Any]:
    stmt = select(AiModelCatalog.last_synced_at).order_by(
        AiModelCatalog.last_synced_at.desc(),
    ).limit(1)
    result = await session.execute(stmt)
    last_synced_at = result.scalar_one_or_none()
    return {"source": CATALOG_SOURCE_URL, "last_synced_at": last_synced_at}
