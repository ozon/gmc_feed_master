from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai import model_catalog
from app.ai.model_catalog import (
    CatalogEntry,
    ensure_seeded,
    get_entries,
    get_sync_state,
    is_recommended,
    load_bundled,
    make_refresh_job,
    parse_catalog,
    refresh,
)
from app.clock import TestClock
from app.models.ai import AiModelCatalog

RAW = {
    "gpt-4o": {
        "litellm_provider": "openai",
        "mode": "chat",
        "input_cost_per_token": 2.5e-06,
        "output_cost_per_token": 1e-05,
        "max_input_tokens": 128000,
        "max_output_tokens": 16384,
        "supports_vision": True,
        "supports_function_calling": True,
    },
    "gpt-4o-no-prices": {
        "litellm_provider": "openai",
        "mode": "chat",
    },
    "text-embedding-3-small": {
        "litellm_provider": "openai",
        "mode": "embedding",
        "input_cost_per_token": 2e-08,
    },
    "gpt-4o-deprecated": {
        "litellm_provider": "openai",
        "mode": "chat",
        "deprecated": True,
    },
    "mistral/mistral-large-latest": {
        "litellm_provider": "mistral",
        "mode": "chat",
        "input_cost_per_token": 5e-07,
        "output_cost_per_token": 1.5e-06,
        "max_input_tokens": 262144,
    },
    "some-random-model": {
        "litellm_provider": "fireworks_ai",
        "mode": "chat",
    },
    "not-a-dict": 42,
}


def test_parse_catalog_keeps_supported_chat_models() -> None:
    entries = {entry.model_id: entry for entry in parse_catalog(RAW)}
    assert set(entries) == {
        "openai/gpt-4o",
        "openai/gpt-4o-no-prices",
        "mistral/mistral-large-latest",
    }


def test_parse_catalog_canonicalizes_bare_and_prefixed_keys() -> None:
    entries = {entry.model_id: entry for entry in parse_catalog(RAW)}
    assert entries["openai/gpt-4o"].vendor == "openai"
    assert entries["openai/gpt-4o"].display_name == "gpt-4o"
    assert entries["mistral/mistral-large-latest"].vendor == "mistral"


def test_parse_catalog_converts_costs_to_per_mtok() -> None:
    entry = {e.model_id: e for e in parse_catalog(RAW)}["openai/gpt-4o"]
    assert entry.input_price_per_mtok == Decimal("2.500000")
    assert entry.output_price_per_mtok == Decimal("10.000000")
    assert entry.context_window == 128000
    assert entry.max_output_tokens == 16384
    assert entry.supports_vision is True
    assert entry.supports_function_calling is True
    assert entry.mode == "chat"


def test_parse_catalog_allows_missing_prices() -> None:
    entry = {e.model_id: e for e in parse_catalog(RAW)}["openai/gpt-4o-no-prices"]
    assert entry.input_price_per_mtok is None
    assert entry.output_price_per_mtok is None


def test_parse_catalog_dedupes_model_ids() -> None:
    duped = dict(RAW)
    duped["openai/gpt-4o"] = duped["gpt-4o"]
    ids = [e.model_id for e in parse_catalog(duped)]
    assert ids.count("openai/gpt-4o") == 1


def test_load_bundled_returns_supported_entries() -> None:
    entries = load_bundled()
    assert len(entries) > 50
    assert all(entry.vendor in {"openai", "anthropic", "google", "openrouter", "mistral", "groq"} for entry in entries)
    assert any(entry.model_id == "openai/gpt-4o" for entry in entries)


def test_is_recommended() -> None:
    assert is_recommended("openai", "openai/gpt-4o") is True
    assert is_recommended("openai", "openai/never-heard-of-it") is False
    assert is_recommended("custom", "openai/anything") is False


@pytest_asyncio.fixture
async def db_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _entry(model_id: str, vendor: str = "openai") -> CatalogEntry:
    return CatalogEntry(
        vendor=vendor, model_id=model_id, display_name=model_id.rsplit("/", 1)[-1],
        mode="chat", context_window=128000, max_output_tokens=4096,
        input_price_per_mtok=Decimal("1.000000"),
        output_price_per_mtok=Decimal("2.000000"),
        supports_vision=False, supports_function_calling=True,
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_ensure_seeded_inserts_bundled_once(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(model_catalog, "load_bundled", lambda: [_entry("openai/gpt-4o")])
    await ensure_seeded(db_factory)
    await ensure_seeded(db_factory)
    async with db_factory() as session:
        rows = list((await session.execute(select(AiModelCatalog))).scalars())
        assert [r.model_id for r in rows] == ["openai/gpt-4o"]
        state = await get_sync_state(session)
        assert state is not None
        assert state.source == "bundled"


@pytest.mark.asyncio
async def test_get_entries_filters_by_vendor_and_mode(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(AiModelCatalog(vendor="openai", model_id="openai/gpt-4o", display_name="gpt-4o", mode="chat"))
        session.add(AiModelCatalog(vendor="anthropic", model_id="anthropic/claude", display_name="claude", mode="chat"))
        session.add(AiModelCatalog(vendor="openai", model_id="openai/embed", display_name="embed", mode="embedding"))
    async with db_factory() as session:
        rows = await get_entries(session, vendor="openai", mode="chat")
        assert [r.model_id for r in rows] == ["openai/gpt-4o"]
        assert {r.model_id for r in await get_entries(session, vendor=None, mode="chat")} == {
            "openai/gpt-4o", "anthropic/claude",
        }


@pytest.mark.asyncio
async def test_refresh_success_replaces_rows(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(model_catalog, "MIN_CATALOG_ENTRIES", 1)
    async with db_factory() as session, session.begin():
        session.add(AiModelCatalog(vendor="openai", model_id="openai/old", display_name="old", mode="chat"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "gpt-4o": {"litellm_provider": "openai", "mode": "chat", "max_input_tokens": 128000},
        })

    client = _client(handler)
    now = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    state = await refresh(db_factory, client, now)
    await client.aclose()
    assert state.last_error is None
    assert state.source == "github"
    assert state.last_success_at == now
    async with db_factory() as session:
        rows = list((await session.execute(select(AiModelCatalog))).scalars())
        assert [r.model_id for r in rows] == ["openai/gpt-4o"]


@pytest.mark.asyncio
async def test_refresh_failure_keeps_existing_rows(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(AiModelCatalog(vendor="openai", model_id="openai/keep", display_name="keep", mode="chat"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client(handler)
    now = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    state = await refresh(db_factory, client, now)
    await client.aclose()
    assert state.last_error is not None
    assert state.last_attempt_at == now
    async with db_factory() as session:
        rows = list((await session.execute(select(AiModelCatalog))).scalars())
        assert [r.model_id for r in rows] == ["openai/keep"]


@pytest.mark.asyncio
async def test_refresh_rejects_too_few_entries(db_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "gpt-4o": {"litellm_provider": "openai", "mode": "chat"},
        })

    client = _client(handler)
    state = await refresh(db_factory, client, datetime(2026, 9, 17, tzinfo=timezone.utc))
    await client.aclose()
    assert state.last_error is not None
    assert "supported entries" in state.last_error


@pytest.mark.asyncio
async def test_refresh_job_runs(db_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "gpt-4o": {"litellm_provider": "openai", "mode": "chat"},
        })

    client = _client(handler)
    clock = TestClock(datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc))
    job = make_refresh_job(db_factory, client, clock)
    await job()
    await client.aclose()
    async with db_factory() as session:
        state = await get_sync_state(session)
        assert state is not None
        assert state.last_attempt_at == clock.now()
