"""AI enrichment step: engine mapping, budget/isolation, suggestion store."""

from __future__ import annotations

import logging

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.schemas import EnrichedAttributes, OptimizedTitle
from app.ai.service import AiResult
from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.plugin import Plugin, PluginData
from app.pipeline.enrichment import (
    DEFAULT_TASKS,
    TASK_FIELDS,
    EnrichmentOutcome,
    generate_suggestions,
    load_enrichment_data,
    store_suggestions,
)
from app.pipeline.steps import EnrichmentStep, RunState, StepContext


def _result(value, status="ok"):
    return AiResult(
        value=value, status=status, error_code=None if status == "ok" else "x",
        prompt_tokens=1, completion_tokens=1,
    )


class FakeAi:
    def __init__(self, results):
        self._results = list(results)
        self.calls: list[str] = []

    async def run_task(self, task_type, variables, *, client_id=None, feed_source_id=None):
        self.calls.append(task_type)
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _products():
    return [
        {"id": "p1", "title": "Red Socks", "description": "wool"},
        {"id": "p2", "title": "Blue Hat", "description": "felt"},
    ]


def test_task_fields_cover_phase_a_task_types() -> None:
    for task_type in (
        "title_optimization",
        "description_optimization",
        "category_classification",
        "attribute_enrichment",
    ):
        assert task_type in TASK_FIELDS
    assert DEFAULT_TASKS == ("attribute_enrichment",)


@pytest.mark.asyncio
async def test_generate_suggestions_maps_fields_to_strings() -> None:
    ai = FakeAi([_result(EnrichedAttributes(color="Red", gender="unisex", size=None))])
    outcome = await generate_suggestions(
        ai_service=ai, products=_products()[:1], tasks=("attribute_enrichment",),
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert outcome == EnrichmentOutcome(
        suggestions={"p1": {"color": "Red", "gender": "unisex"}},
        generated=1, failed=0, spent=1,
    )


@pytest.mark.asyncio
async def test_generate_suggestions_budget_stops_before_next_call() -> None:
    ai = FakeAi([
        _result(EnrichedAttributes(color="Red")),
        _result(EnrichedAttributes(color="Blue")),
    ])
    outcome = await generate_suggestions(
        ai_service=ai, products=_products(), tasks=("attribute_enrichment",),
        limit=50, budget=1, client_id=1, feed_source_id=7,
    )
    assert ai.calls == ["attribute_enrichment"]
    assert outcome.spent == 1
    assert outcome.generated == 1


@pytest.mark.asyncio
async def test_generate_suggestions_isolates_item_failure() -> None:
    ai = FakeAi([RuntimeError("boom"), _result(EnrichedAttributes(color="Blue"))])
    outcome = await generate_suggestions(
        ai_service=ai, products=_products(), tasks=("attribute_enrichment",),
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert outcome.failed == 1
    assert outcome.generated == 1
    assert outcome.suggestions == {"p2": {"color": "Blue"}}


@pytest.mark.asyncio
async def test_generate_suggestions_cache_hit_is_free_and_included() -> None:
    ai = FakeAi([
        _result(EnrichedAttributes(color="Red"), status="cache_hit"),
        _result(EnrichedAttributes(color="Blue"), status="cache_hit"),
    ])
    outcome = await generate_suggestions(
        ai_service=ai, products=_products(), tasks=("attribute_enrichment",),
        limit=50, budget=1, client_id=1, feed_source_id=7,
    )
    assert outcome.spent == 0
    assert outcome.generated == 2


@pytest.mark.asyncio
async def test_generate_suggestions_multi_task_merges_fields() -> None:
    ai = FakeAi([
        _result(OptimizedTitle(title="Red Wool Socks")),
        _result(EnrichedAttributes(color="Red")),
    ])
    outcome = await generate_suggestions(
        ai_service=ai, products=_products()[:1],
        tasks=("title_optimization", "attribute_enrichment"),
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert outcome.suggestions == {
        "p1": {"title": "Red Wool Socks", "color": "Red"},
    }
    assert outcome.spent == 2


@pytest.mark.asyncio
async def test_generate_suggestions_without_service_is_empty() -> None:
    outcome = await generate_suggestions(
        ai_service=None, products=_products(), tasks=DEFAULT_TASKS,
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert outcome == EnrichmentOutcome(suggestions={}, generated=0, failed=0, spent=0)


@pytest_asyncio.fixture
async def db(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        client = Client(name="c1")
        session.add(client)
        await session.flush()
        plugin = Plugin(name="enrichment", version="1.0.0", manifest={})
        session.add(plugin)
        await session.flush()
        feed = FeedSource(
            client_id=client.id, name="f1", source_format="csv", configuration={}
        )
        session.add(feed)
        await session.flush()
        ids = {"client_id": client.id, "plugin_id": plugin.id, "feed_id": feed.id}
    yield factory, ids
    await engine.dispose()


async def _set_config(factory, feed_id, config):
    async with factory() as session, session.begin():
        feed = await session.get(FeedSource, feed_id)
        feed.configuration = {"ai_enrichment": config}


@pytest.mark.asyncio
async def test_store_then_load_preserves_pinned(db) -> None:
    factory, ids = db
    assert await store_suggestions(factory, ids["feed_id"], {"p1": {"color": "Blue"}})
    async with factory() as session, session.begin():
        row = (await session.execute(select(PluginData).where(
            PluginData.plugin_id == ids["plugin_id"],
            PluginData.scope == "feed_source",
            PluginData.feed_source_id == ids["feed_id"],
            PluginData.key == "default",
        ))).scalar_one()
        data = dict(row.data)
        data["pinned"] = {"p2": {"size": "L"}}
        row.data = data
    await store_suggestions(factory, ids["feed_id"], {"p1": {"gender": "unisex"}})
    plugin_id, data = await load_enrichment_data(factory, ids["feed_id"])
    assert plugin_id == ids["plugin_id"]
    assert data["suggestions"] == {"p1": {"color": "Blue", "gender": "unisex"}}
    assert data["pinned"] == {"p2": {"size": "L"}}


def _ctx(factory, ids, *, dry_run=False):
    state = RunState(products=_products(), client_id=ids["client_id"])
    return StepContext(
        feed_source_id=ids["feed_id"], session_factory=factory,
        logger=logging.getLogger("test"), run_state=state, dry_run=dry_run,
    )


@pytest.mark.asyncio
async def test_step_disabled_writes_nothing(db) -> None:
    factory, ids = db
    ai = FakeAi([_result(EnrichedAttributes(color="Red"))])
    ctx = _ctx(factory, ids)
    result = await EnrichmentStep(ai).execute(ctx)
    assert result.statistics["ai_enrichment"]["enabled"] is False
    assert ctx.run_state.ai_suggestions == {}
    _pid, data = await load_enrichment_data(factory, ids["feed_id"])
    assert data == {}


@pytest.mark.asyncio
async def test_step_enabled_persists_suggestions(db) -> None:
    factory, ids = db
    await _set_config(factory, ids["feed_id"], {"enabled": True, "tasks": ["attribute_enrichment"]})
    ai = FakeAi([
        _result(EnrichedAttributes(color="Red")),
        _result(EnrichedAttributes(color="Blue")),
    ])
    ctx = _ctx(factory, ids)
    result = await EnrichmentStep(ai).execute(ctx)
    assert result.statistics["ai_enrichment"]["generated"] == 2
    assert ctx.run_state.ai_suggestions["p1"] == {"color": "Red"}
    _pid, data = await load_enrichment_data(factory, ids["feed_id"])
    assert data["suggestions"]["p1"] == {"color": "Red"}
    assert data["suggestions"]["p2"] == {"color": "Blue"}


@pytest.mark.asyncio
async def test_step_dry_run_does_not_persist(db) -> None:
    factory, ids = db
    await _set_config(factory, ids["feed_id"], {"enabled": True})
    ai = FakeAi([_result(EnrichedAttributes(color="Red"))])
    ctx = _ctx(factory, ids, dry_run=True)
    await EnrichmentStep(ai).execute(ctx)
    assert ctx.run_state.ai_suggestions["p1"] == {"color": "Red"}
    _pid, data = await load_enrichment_data(factory, ids["feed_id"])
    assert data == {}


def _registry_stub():
    from types import SimpleNamespace

    return SimpleNamespace(attributes={})


def _clock_stub():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    return SimpleNamespace(now=lambda: datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_run_dry_run_surfaces_suggestions_without_persisting(db, monkeypatch) -> None:
    factory, ids = db
    await _set_config(factory, ids["feed_id"], {"enabled": True})
    ai = FakeAi([_result(EnrichedAttributes(color="Red"))])

    async with factory() as session, session.begin():
        feed = await session.get(FeedSource, ids["feed_id"])
        feed.source_url = "http://example.test/feed.csv"
        feed.source_format = "csv"

    from app.pipeline import dry_run as dry_run_module
    from app.pipeline.steps import StepResult

    class FakeIngest:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, ctx):
            ctx.run_state.products = _products()
            ctx.run_state.client_id = ids["client_id"]
            return StepResult(processed_count=2)

    monkeypatch.setattr(dry_run_module, "IngestStep", FakeIngest)

    from types import SimpleNamespace

    def _passthrough(product, mappings, registry):
        return product, SimpleNamespace(dropped_unmapped=0, shape_mismatches=0)

    monkeypatch.setattr(dry_run_module, "apply_mapping", _passthrough)

    result = await dry_run_module.run_dry_run(
        session_factory=factory,
        feed_source_id=ids["feed_id"],
        fetcher=object(),
        registry=_registry_stub(),
        plugin_registry={},
        clock=_clock_stub(),
        image_probe=None,
        ai_service=ai,
    )
    assert result.ai_suggestions.get("p1") == {"color": "Red"}
    _pid, data = await load_enrichment_data(factory, ids["feed_id"])
    assert data == {}
