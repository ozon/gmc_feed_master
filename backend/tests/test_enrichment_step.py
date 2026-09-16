"""AI enrichment step: engine mapping, budget/isolation, suggestion store."""

from __future__ import annotations

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
