from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..clock import Clock
from ..models.ai import AiModelCatalog, AiModelCatalogSync

logger = logging.getLogger(__name__)

LITELLM_CATALOG_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "litellm/model_prices_and_context_window.json"
)
MIN_CATALOG_ENTRIES = 50

SUPPORTED_VENDORS: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "openrouter": "openrouter",
    "mistral": "mistral",
    "groq": "groq",
}

RECOMMENDED_MODELS: dict[str, set[str]] = {
    "openai": {"openai/gpt-4o", "openai/gpt-4o-mini"},
    "anthropic": {"anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5"},
    "google": {"gemini/gemini-2.5-flash", "gemini/gemini-2.0-flash"},
    "openrouter": {"openrouter/anthropic/claude-sonnet-4"},
    "mistral": {"mistral/mistral-large-latest"},
    "groq": {"groq/llama-3.3-70b-versatile"},
}


@dataclass(frozen=True)
class CatalogEntry:
    vendor: str
    model_id: str
    display_name: str
    mode: str
    context_window: int | None
    max_output_tokens: int | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    supports_vision: bool
    supports_function_calling: bool


def _per_mtok(cost: Any) -> Decimal | None:
    if cost is None:
        return None
    return (Decimal(str(cost)) * Decimal(1_000_000)).quantize(Decimal("0.000001"))


def parse_catalog(raw: dict[str, Any]) -> list[CatalogEntry]:
    entries: dict[str, CatalogEntry] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        provider = value.get("litellm_provider")
        if not isinstance(provider, str):
            continue
        vendor = SUPPORTED_VENDORS.get(provider)
        if vendor is None:
            continue
        mode = value.get("mode") or "chat"
        if mode not in ("chat", "completion"):
            continue
        if value.get("deprecated"):
            continue
        model_id = key if "/" in key else f"{provider}/{key}"
        if model_id in entries:
            continue
        max_tokens = value.get("max_tokens")
        entries[model_id] = CatalogEntry(
            vendor=vendor,
            model_id=model_id,
            display_name=model_id.rsplit("/", 1)[-1],
            mode="chat",
            context_window=value.get("max_input_tokens") or max_tokens,
            max_output_tokens=value.get("max_output_tokens") or max_tokens,
            input_price_per_mtok=_per_mtok(value.get("input_cost_per_token")),
            output_price_per_mtok=_per_mtok(value.get("output_cost_per_token")),
            supports_vision=bool(value.get("supports_vision")),
            supports_function_calling=bool(value.get("supports_function_calling")),
        )
    return list(entries.values())


def load_bundled() -> list[CatalogEntry]:
    import litellm

    return parse_catalog(litellm.model_cost)


def is_recommended(vendor: str, model_id: str) -> bool:
    return model_id in RECOMMENDED_MODELS.get(vendor, set())


MODEL_CATALOG_REFRESH_JOB_ID = "system-ai-model-catalog-refresh"
MODEL_CATALOG_REFRESH_CRON = "0 4 * * *"


@dataclass(frozen=True)
class CatalogSyncState:
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    source: str | None


async def replace_catalog_entries(session: AsyncSession, entries: list[CatalogEntry]) -> None:
    await session.execute(delete(AiModelCatalog))
    session.add_all(
        [
            AiModelCatalog(
                vendor=entry.vendor,
                model_id=entry.model_id,
                display_name=entry.display_name,
                mode=entry.mode,
                context_window=entry.context_window,
                max_output_tokens=entry.max_output_tokens,
                input_price_per_mtok=entry.input_price_per_mtok,
                output_price_per_mtok=entry.output_price_per_mtok,
                supports_vision=entry.supports_vision,
                supports_function_calling=entry.supports_function_calling,
            )
            for entry in entries
        ]
    )


async def ensure_seeded(
    session_factory: Callable[[], AsyncSession],
) -> None:
    async with session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(AiModelCatalog))
        ).scalar_one()
        if count:
            return
    entries = load_bundled()
    async with session_factory() as session, session.begin():
        sync = await session.get(AiModelCatalogSync, 1)
        if sync is None:
            sync = AiModelCatalogSync(id=1)
            session.add(sync)
        await replace_catalog_entries(session, entries)
        sync.last_success_at = datetime.now(timezone.utc)
        sync.last_error = None
        sync.source = "bundled"


async def get_entries(
    session: AsyncSession, vendor: str | None, mode: str
) -> list[AiModelCatalog]:
    statement = select(AiModelCatalog).where(AiModelCatalog.mode == mode)
    if vendor is not None:
        statement = statement.where(AiModelCatalog.vendor == vendor)
    statement = statement.order_by(AiModelCatalog.vendor, AiModelCatalog.model_id)
    return list((await session.execute(statement)).scalars())


async def get_sync_state(session: AsyncSession) -> CatalogSyncState | None:
    row = await session.get(AiModelCatalogSync, 1)
    if row is None:
        return None
    return CatalogSyncState(
        last_attempt_at=row.last_attempt_at,
        last_success_at=row.last_success_at,
        last_error=row.last_error,
        source=row.source,
    )


async def refresh(
    session_factory: Callable[[], AsyncSession],
    http_client: httpx.AsyncClient,
    now: datetime,
) -> CatalogSyncState:
    entries: list[CatalogEntry] = []
    error: str | None = None
    try:
        response = await http_client.get(LITELLM_CATALOG_URL)
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise TypeError("catalog payload is not an object")
        entries = parse_catalog(raw)
        if len(entries) < MIN_CATALOG_ENTRIES:
            raise ValueError(
                f"catalog payload yielded only {len(entries)} supported entries"
            )
    except Exception as exc:  # noqa: BLE001 -- fail-open: refresh must never raise
        error = f"{type(exc).__name__}: {exc}"
        logger.error("ai model catalog refresh failed: %s", error)
    async with session_factory() as session, session.begin():
        sync = await session.get(AiModelCatalogSync, 1)
        if sync is None:
            sync = AiModelCatalogSync(id=1)
            session.add(sync)
        sync.last_attempt_at = now
        if error is None:
            await replace_catalog_entries(session, entries)
            sync.last_success_at = now
            sync.last_error = None
            sync.source = "github"
        else:
            sync.last_error = error
        await session.flush()
        return CatalogSyncState(
            last_attempt_at=sync.last_attempt_at,
            last_success_at=sync.last_success_at,
            last_error=sync.last_error,
            source=sync.source,
        )


def make_refresh_job(
    session_factory: Callable[[], AsyncSession],
    http_client: httpx.AsyncClient,
    clock: Clock,
) -> Callable[[], Awaitable[None]]:
    async def job() -> None:
        state = await refresh(session_factory, http_client, clock.now())
        if state.last_error:
            logger.warning("ai model catalog refresh failed: %s", state.last_error)
        else:
            logger.info("ai model catalog refreshed: source=%s", state.source)

    return job
