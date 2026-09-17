"""RuleAiStep: AI rule action engine, budget/limit, fallback isolation, persistence."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.schemas import EnrichedAttributes, OptimizedTitle, RuleValueResult
from app.ai.service import AiResult
from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.ingestion import IngestionRun
from app.models.staging import StagingProduct
from app.pipeline.rule_ai import RuleAiOutcome, apply_rule_ai_actions
from app.pipeline.steps import RuleAiStep, RunState, StagingStep, StepContext


def _result(value, status="ok"):
    return AiResult(value=value, status=status, error_code=None if status == "ok" else "x",
                    prompt_tokens=1, completion_tokens=1)


class FakeAi:
    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    async def run_task(self, task_type, variables, *, client_id=None, feed_source_id=None,
                       template_id=None, lenient=False):
        self.calls.append({
            "task": task_type, "template_id": template_id,
            "vars": dict(variables), "lenient": lenient,
        })
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def run_inline_task(self, system, user, variables, *, client_id=None,
                              feed_source_id=None, lenient=False):
        self.calls.append({"inline": system, "vars": dict(variables), "lenient": lenient})
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_TEMPLATE_ENTRY = {
    "product_id": "p1", "field": "", "taskType": "title_optimization",
    "promptSource": "template", "templateId": 5, "system": None, "user": None,
    "variables": [],
}
_CUSTOM_ENTRY = {
    "product_id": "p1", "field": "custom_label_0", "taskType": "rule_value",
    "promptSource": "custom", "templateId": None, "system": "sys",
    "user": "Brand {{title}}", "variables": ["title"],
}


def _products():
    return [{"id": "p1", "title": "Red Socks"}, {"id": "p2", "title": "Blue Hat"}]


@pytest.mark.asyncio
async def test_template_entry_maps_task_fields() -> None:
    ai = FakeAi([_result(OptimizedTitle(title="Red Wool Socks"))])
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=[dict(_TEMPLATE_ENTRY)],
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert changed["p1"]["title"] == "Red Wool Socks"
    assert outcome == RuleAiOutcome(products=1, applied=1, failed=0, spent=1)
    assert ai.calls[0]["template_id"] == 5
    assert ai.calls[0]["lenient"] is True


@pytest.mark.asyncio
async def test_custom_entry_writes_target_field() -> None:
    ai = FakeAi([_result(RuleValueResult(value="Acme"))])
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=[dict(_CUSTOM_ENTRY)],
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert changed["p1"]["custom_label_0"] == "Acme"
    assert ai.calls[0]["vars"] == {"title": "Red Socks"}
    assert outcome.spent == 1


@pytest.mark.asyncio
async def test_budget_stops_between_products() -> None:
    ai = FakeAi([_result(OptimizedTitle(title="A")), _result(OptimizedTitle(title="B"))])
    pending = [dict(_TEMPLATE_ENTRY), {**_TEMPLATE_ENTRY, "product_id": "p2"}]
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=pending,
        limit=50, budget=1, client_id=1, feed_source_id=7,
    )
    assert set(changed) == {"p1"}
    assert outcome.spent == 1
    assert outcome.products == 1


@pytest.mark.asyncio
async def test_cache_hit_is_free() -> None:
    ai = FakeAi([_result(OptimizedTitle(title="A"), status="cache_hit")])
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=[dict(_TEMPLATE_ENTRY)],
        limit=50, budget=1, client_id=1, feed_source_id=7,
    )
    assert outcome.spent == 0
    assert changed["p1"]["title"] == "A"


@pytest.mark.asyncio
async def test_failure_is_isolated() -> None:
    ai = FakeAi([RuntimeError("boom"), _result(OptimizedTitle(title="B"))])
    pending = [dict(_TEMPLATE_ENTRY), {**_TEMPLATE_ENTRY, "product_id": "p2"}]
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=pending,
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert outcome.failed == 1
    assert changed["p2"]["title"] == "B"


@pytest.mark.asyncio
async def test_attribute_enrichment_merges_multiple_fields() -> None:
    ai = FakeAi([_result(EnrichedAttributes(color="Red", gender="unisex", size=None))])
    entry = {**_TEMPLATE_ENTRY, "taskType": "attribute_enrichment", "templateId": None}
    changed, _outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=[entry],
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert changed["p1"]["color"] == "Red"
    assert changed["p1"]["gender"] == "unisex"
    assert "size" not in changed["p1"]


@pytest.mark.asyncio
async def test_no_service_is_empty() -> None:
    changed, outcome = await apply_rule_ai_actions(
        ai_service=None, products=_products(), pending=[dict(_CUSTOM_ENTRY)],
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert changed == {}
    assert outcome == RuleAiOutcome(products=0, applied=0, failed=0, spent=0)


def test_ai_output_fields_mirror_task_fields() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/rules"))
    import plugin

    from app.pipeline.enrichment import TASK_FIELDS

    assert plugin._AI_OUTPUT_FIELDS == {k: tuple(v) for k, v in TASK_FIELDS.items()}


@pytest_asyncio.fixture
async def db(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        client = Client(name="c1")
        session.add(client)
        await session.flush()
        feed = FeedSource(client_id=client.id, name="f1", source_format="csv",
                          configuration={"ai_rules": {"enabled": True}})
        session.add(feed)
        await session.flush()
        run = IngestionRun(feed_source_id=feed.id, status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        rows = []
        for pid in ("p1", "p2"):
            row = StagingProduct(
                feed_source_id=feed.id, ingestion_run_id=run.id, product_id=pid,
                content_hash="x", config_hash="x", status="active", excluded=False,
                raw_data={"id": pid, "title": pid}, processed_data={"id": pid, "title": pid},
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        ids = {"client_id": client.id, "feed_id": feed.id, "run_id": run.id,
               "pks": {r.product_id: r.id for r in rows}}
    yield factory, ids
    await engine.dispose()


def _ctx(factory, ids, *, dry_run=False):
    state = RunState(products=_products(), client_id=ids["client_id"],
                     product_pks=ids["pks"], rule_ai_pending=[dict(_TEMPLATE_ENTRY)])
    return StepContext(feed_source_id=ids["feed_id"], session_factory=factory,
                       logger=logging.getLogger("test"), run_state=state,
                       ingestion_run_id=ids["run_id"], dry_run=dry_run)


@pytest.mark.asyncio
async def test_step_persists_processed_data(db) -> None:
    factory, ids = db
    ai = FakeAi([_result(OptimizedTitle(title="New"))])
    ctx = _ctx(factory, ids)
    result = await RuleAiStep(ai).execute(ctx)
    assert result.statistics["ai_rules"]["applied"] == 1
    assert ctx.run_state.products[0]["title"] == "New"
    async with factory() as session:
        row = await session.get(StagingProduct, ids["pks"]["p1"])
        assert row.processed_data["title"] == "New"


@pytest.mark.asyncio
async def test_step_disabled_is_noop(db) -> None:
    factory, ids = db
    async with factory() as session, session.begin():
        feed = await session.get(FeedSource, ids["feed_id"])
        feed.configuration = {"ai_rules": {"enabled": False}}
    ai = FakeAi([_result(OptimizedTitle(title="New"))])
    ctx = _ctx(factory, ids)
    result = await RuleAiStep(ai).execute(ctx)
    assert result.statistics["ai_rules"]["enabled"] is False
    assert ctx.run_state.products[0]["title"] == "Red Socks"


@pytest.mark.asyncio
async def test_step_dry_run_does_not_persist(db) -> None:
    factory, ids = db
    ai = FakeAi([_result(OptimizedTitle(title="New"))])
    ctx = _ctx(factory, ids, dry_run=True)
    await RuleAiStep(ai).execute(ctx)
    assert ctx.run_state.products[0]["title"] == "New"
    async with factory() as session:
        row = await session.get(StagingProduct, ids["pks"]["p1"])
        assert row.processed_data["title"] == "p1"


@pytest.mark.asyncio
async def test_staging_hashes_ai_rules_so_flip_reenqueues_unchanged(db) -> None:
    factory, ids = db
    step = StagingStep()

    async def run_once():
        state = RunState(products=_products())
        ctx = StepContext(
            feed_source_id=ids["feed_id"], session_factory=factory,
            logger=logging.getLogger("test"), run_state=state,
            ingestion_run_id=ids["run_id"],
        )
        return await step.execute(ctx)

    assert (await run_once()).processed_count == 2
    assert (await run_once()).processed_count == 0

    async with factory() as session, session.begin():
        feed = await session.get(FeedSource, ids["feed_id"])
        feed.configuration = {"ai_rules": {"enabled": True, "limit": 10}}

    assert (await run_once()).processed_count == 2
