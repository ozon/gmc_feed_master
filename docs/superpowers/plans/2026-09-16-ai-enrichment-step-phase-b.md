# AI Enrichment Pipeline Step — Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `EnrichmentStep` that generates AI attribute suggestions during a feed run and writes them into the existing enrichment `PluginData.suggestions` store, so the Z4 review UI (scan → accept → pin) keeps gating what reaches product output.

**Architecture:** A new `app/pipeline/enrichment.py` holds the engine (`generate_suggestions` iterating `AiService.run_task` per product/task with per-item isolation and a budget) plus the `PluginData` load/store helpers that resolve the `enrichment` plugin row directly (the route helpers `_get_payload`/`_put_payload` are user-scoped and unusable from a pipeline step). `EnrichmentStep` in `app/pipeline/steps.py` is thin: read `configuration.ai_enrichment`, call the engine, persist unless `dry_run`. `run_dry_run` gains the step with `dry_run=True` and surfaces suggestions without persisting.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.0 async, PostgreSQL, pytest (`-n auto` default; mark `@pytest.mark.asyncio` explicitly).

**Status:** Phase B of `docs/superpowers/specs/2026-09-16-litellm-instructor-ai-core-design.md` (Phase A merged at `bef098d`); complete 2026-09-16 on branch `ai-enrichment-step`. Execution notes: the dry-run test needed two test-side patches — `apply_mapping` passthrough (an empty `field_mapping` strips all fields, leaving products with no `id`) and a typed `HttpFetcher` cast for mypy. Gates at close: backend 1299 passed, ruff 490/490 (zero new), mypy exit-0.

## Global Constraints

- Run everything from `backend/`.
- DB URL: export `DATABASE_URL` from the repo `.env` (local Postgres is on host port **5434**):
  ```bash
  export DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')"
  ```
  `uv run pytest` additionally needs `TEST_DATABASE_URL` exported (same server, `postgresql+asyncpg://`, no query params).
- Gates each task: `uv run ruff check .` (must stay at the current HEAD count of **490** — zero new errors, do not edit `ruff-baseline.txt`), `uv run mypy .` (exit 0), `uv run pytest`.
- `uv run pytest` must be run with `DATABASE_URL` unset to avoid the conftest warning: `env -u DATABASE_URL TEST_DATABASE_URL=... uv run pytest`.
- Suggestion values in `PluginData` are **strings** (the plugin manifest's `data_schema` allows only string values).
- The step must never abort a run: `AiService` already degrades to `AiResult(status="fallback")`; per-item exceptions are caught and counted.
- No DB session may be held across an AI call.
- Do not modify `backend/app/plugins/{contract,manifest,discovery,loader,runtime}.py`.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/pipeline/enrichment.py` | new — task→field map, `generate_suggestions`, `load_enrichment_data`, `store_suggestions` |
| `app/pipeline/steps.py` | edit — `RunState.ai_suggestions`, `StepContext.dry_run`, `EnrichmentStep`, `default_steps` wiring |
| `app/pipeline/dry_run.py` | edit — `ai_service` param, run `EnrichmentStep`, `DryRunResult.ai_suggestions` |
| `app/routes/dry_run.py` | edit — pass `ai_service`, return `ai_suggestions` |
| `tests/test_enrichment_step.py` | new — engine + store + step tests |
| `backend/docs/architecture.md`, `backend/docs/api.md`, `TODO.md` | edit — document the step |

---

### Task 1: Enrichment engine and store

**Files:**
- Create: `app/pipeline/enrichment.py`
- Test: `tests/test_enrichment_step.py`

**Interfaces:**
- Consumes: `AiService.run_task(task_type, variables, *, client_id, feed_source_id) -> AiResult`; `AiResult(value, status, error_code, prompt_tokens, completion_tokens)` with `status in {"ok","cache_hit","fallback"}`; `app.ai.tasks.CANONICAL_VARIABLES`.
- Produces:
  - `TASK_FIELDS: dict[str, tuple[str, ...]]`
  - `DEFAULT_TASKS: tuple[str, ...]`
  - `@dataclass(frozen=True) EnrichmentOutcome(suggestions: dict[str, dict[str, str]], generated: int, failed: int, spent: int)`
  - `async def generate_suggestions(*, ai_service, products, tasks, limit, budget, client_id, feed_source_id) -> EnrichmentOutcome`
  - `async def load_enrichment_data(session_factory, feed_source_id) -> tuple[int | None, dict[str, Any]]`
  - `async def store_suggestions(session_factory, feed_source_id, suggestions) -> bool`

- [ ] **Step 1: Write the failing tests (engine, no DB)**

```python
# backend/tests/test_enrichment_step.py
from __future__ import annotations

import logging

import pytest
import pytest_asyncio
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
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
env -u DATABASE_URL TEST_DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" \
  uv run pytest tests/test_enrichment_step.py -q
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.enrichment'`.

- [ ] **Step 3: Implement `app/pipeline/enrichment.py`**

```python
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.tasks import CANONICAL_VARIABLES
from ..models.plugin import Plugin, PluginData

logger = logging.getLogger(__name__)

PLUGIN_NAME = "enrichment"
DEFAULT_KEY = "default"

# Which response-model fields (see app/ai/schemas.py) become suggestion fields.
TASK_FIELDS: dict[str, tuple[str, ...]] = {
    "title_optimization": ("title",),
    "description_optimization": ("description",),
    "category_classification": ("google_product_category",),
    "attribute_enrichment": (
        "color", "size", "material", "gtin", "gender", "age_group",
        "custom_label_0", "custom_label_1", "custom_label_2",
        "custom_label_3", "custom_label_4",
    ),
}

DEFAULT_TASKS: tuple[str, ...] = ("attribute_enrichment",)


@dataclass(frozen=True)
class EnrichmentOutcome:
    suggestions: dict[str, dict[str, str]]
    generated: int
    failed: int
    spent: int


async def generate_suggestions(
    *,
    ai_service: Any,
    products: Sequence[dict[str, Any]],
    tasks: Iterable[str],
    limit: int,
    budget: int,
    client_id: int | None,
    feed_source_id: int | None,
) -> EnrichmentOutcome:
    if ai_service is None:
        return EnrichmentOutcome({}, 0, 0, 0)

    task_list = tuple(tasks)
    suggestions: dict[str, dict[str, str]] = {}
    generated = failed = spent = 0

    for product in list(products)[:limit]:
        if spent >= budget:
            break
        product_id = str(product.get("id", ""))
        if not product_id:
            continue
        collected: dict[str, str] = {}
        for task_type in task_list:
            if spent >= budget:
                break
            variables = {
                name: product.get(name)
                for name in CANONICAL_VARIABLES.get(task_type, [])
            }
            try:
                result = await ai_service.run_task(
                    task_type, variables,
                    client_id=client_id, feed_source_id=feed_source_id,
                )
            except Exception:  # noqa: BLE001 — one product must not abort the batch
                logger.warning(
                    "enrichment: task %s failed for product %s", task_type, product_id,
                    exc_info=True,
                )
                failed += 1
                continue
            if result.status == "fallback":
                failed += 1
                continue
            if result.status == "ok":
                spent += 1
            value = result.value
            if value is None:
                continue
            dumped = value.model_dump() if hasattr(value, "model_dump") else {}
            for field in TASK_FIELDS.get(task_type, ()):
                raw = dumped.get(field)
                if raw not in (None, ""):
                    collected[field] = str(raw)
        if collected:
            suggestions[product_id] = collected
            generated += 1

    return EnrichmentOutcome(
        suggestions=suggestions, generated=generated, failed=failed, spent=spent
    )


async def _enrichment_plugin(session: AsyncSession) -> Plugin | None:
    result = await session.execute(
        select(Plugin).where(Plugin.name == PLUGIN_NAME).order_by(Plugin.id)
    )
    return result.scalars().first()


async def load_enrichment_data(
    session_factory: Callable[[], AsyncSession], feed_source_id: int
) -> tuple[int | None, dict[str, Any]]:
    async with session_factory() as session:
        plugin = await _enrichment_plugin(session)
        if plugin is None:
            return None, {}
        row = (await session.execute(
            select(PluginData).where(
                PluginData.plugin_id == plugin.id,
                PluginData.scope == "feed_source",
                PluginData.feed_source_id == feed_source_id,
                PluginData.key == DEFAULT_KEY,
            )
        )).scalar_one_or_none()
        return plugin.id, (dict(row.data) if row is not None else {})


async def store_suggestions(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    suggestions: dict[str, dict[str, str]],
) -> bool:
    async with session_factory() as session, session.begin():
        plugin = await _enrichment_plugin(session)
        if plugin is None:
            logger.warning("enrichment: plugin row missing; suggestions not stored")
            return False
        row = (await session.execute(
            select(PluginData).where(
                PluginData.plugin_id == plugin.id,
                PluginData.scope == "feed_source",
                PluginData.feed_source_id == feed_source_id,
                PluginData.key == DEFAULT_KEY,
            )
        )).scalar_one_or_none()
        existing = dict(row.data) if row is not None else {}
        merged: dict[str, dict[str, str]] = {
            str(pid): dict(fields)
            for pid, fields in (existing.get("suggestions") or {}).items()
        }
        for product_id, fields in suggestions.items():
            bucket = merged.setdefault(product_id, {})
            bucket.update(fields)
        data = {"suggestions": merged, "pinned": existing.get("pinned") or {}}
        if row is None:
            session.add(PluginData(
                plugin_id=plugin.id, scope="feed_source",
                feed_source_id=feed_source_id, key=DEFAULT_KEY, data=data,
            ))
        else:
            row.data = data
        return True
```

- [ ] **Step 4: Run to verify it passes**

Run:
```bash
env -u DATABASE_URL TEST_DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" \
  uv run pytest tests/test_enrichment_step.py -q
```
Expected: PASS (the engine tests).

- [ ] **Step 5: Lint the new module**

Run: `uv run ruff check app/pipeline/enrichment.py tests/test_enrichment_step.py`
Expected: `All checks passed!` (if `RUF100` reports an unused `# noqa`, remove the directive — ruff does not flag `except ... as exc`-style binds here).

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/enrichment.py backend/tests/test_enrichment_step.py
git commit -m "feat(pipeline): AI enrichment engine and suggestion store"
```

---

### Task 2: `EnrichmentStep` and pipeline wiring

**Files:**
- Modify: `app/pipeline/steps.py`
- Test: `tests/test_enrichment_step.py` (append)

**Interfaces:**
- Consumes: `generate_suggestions`, `store_suggestions`, `TASK_FIELDS`, `DEFAULT_TASKS` (Task 1).
- Produces: `RunState.ai_suggestions: dict[str, dict[str, str]]`; `StepContext.dry_run: bool = False`; `EnrichmentStep.name == "ai_enrichment"`; `default_steps` returns the extra step.

- [ ] **Step 1: Append the failing tests**

```python
# append to backend/tests/test_enrichment_step.py

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


def _ctx(factory, ids, *, dry_run=False):
    state = RunState(products=_products(), client_id=ids["client_id"])
    return StepContext(
        feed_source_id=ids["feed_id"], session_factory=factory,
        logger=logging.getLogger("test"), run_state=state, dry_run=dry_run,
    )


async def _set_config(factory, feed_id, config):
    async with factory() as session, session.begin():
        feed = await session.get(FeedSource, feed_id)
        feed.configuration = {"ai_enrichment": config}


@pytest.mark.asyncio
async def test_store_then_load_preserves_pinned(db) -> None:
    factory, ids = db
    assert await store_suggestions(factory, ids["feed_id"], {"p1": {"color": "Blue"}})
    async with factory() as session, session.begin():
        session.add(PluginData(
            plugin_id=ids["plugin_id"], scope="feed_source",
            feed_source_id=ids["feed_id"], key="default",
            data={"suggestions": {}, "pinned": {"p2": {"size": "L"}}},
        ))
    await store_suggestions(factory, ids["feed_id"], {"p1": {"gender": "unisex"}})
    plugin_id, data = await load_enrichment_data(factory, ids["feed_id"])
    assert plugin_id == ids["plugin_id"]
    assert data["suggestions"] == {"p1": {"color": "Blue", "gender": "unisex"}}
    assert data["pinned"] == {"p2": {"size": "L"}}


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_enrichment_step.py -q`
Expected: FAIL — `ImportError: cannot import name 'EnrichmentStep'` (and `StepContext` has no `dry_run`).

- [ ] **Step 3: Implement in `app/pipeline/steps.py`**

Add to `RunState` (after `dropped`):
```python
    ai_suggestions: dict[str, dict[str, str]] = field(default_factory=dict)
```

Add to `StepContext` (after `trigger`):
```python
    dry_run: bool = False
```

Add the step class immediately before `QualityCheckStep`:
```python
class EnrichmentStep:
    name = "ai_enrichment"

    def __init__(self, ai_service: Any = None) -> None:
        self._ai_service = ai_service

    async def execute(self, ctx: StepContext) -> StepResult:
        from .enrichment import DEFAULT_TASKS, TASK_FIELDS, generate_suggestions, store_suggestions

        async with ctx.session_factory() as session, session.begin():
            feed_source = await session.get(FeedSource, ctx.feed_source_id)
        if feed_source is None:
            raise LookupError(f"feed source {ctx.feed_source_id} not found")

        cfg = (feed_source.configuration or {}).get("ai_enrichment") or {}
        if not cfg.get("enabled") or self._ai_service is None:
            return StepResult(statistics={"ai_enrichment": {"enabled": False}})

        tasks = tuple(t for t in (cfg.get("tasks") or list(DEFAULT_TASKS)) if t in TASK_FIELDS)
        limit = max(1, int(cfg.get("limit", 50)))
        budget = max(1, int(cfg.get("budget", 50)))

        outcome = await generate_suggestions(
            ai_service=self._ai_service,
            products=ctx.run_state.products,
            tasks=tasks or DEFAULT_TASKS,
            limit=limit,
            budget=budget,
            client_id=ctx.run_state.client_id,
            feed_source_id=ctx.feed_source_id,
        )
        ctx.run_state.ai_suggestions = outcome.suggestions
        if not ctx.dry_run and outcome.suggestions:
            await store_suggestions(
                ctx.session_factory, ctx.feed_source_id, outcome.suggestions
            )
        return StepResult(
            processed_count=outcome.generated,
            failed_count=outcome.failed,
            statistics={
                "ai_enrichment": {
                    "enabled": True,
                    "generated": outcome.generated,
                    "failed": outcome.failed,
                    "spent": outcome.spent,
                }
            },
        )
```

Wire it into `default_steps` between `PluginStep` and `QualityCheckStep`:
```python
        PluginStep(plugin_registry),
        EnrichmentStep(ai_service),
        QualityCheckStep(registry, clock, image_probe, ai_service),
```

- [ ] **Step 4: Run to verify it passes**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_enrichment_step.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Verify the pipeline contract still holds**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_pipeline_steps.py tests/test_example_feed_chain.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/steps.py backend/tests/test_enrichment_step.py
git commit -m "feat(pipeline): opt-in EnrichmentStep writing review suggestions"
```

---

### Task 3: Dry-run integration

**Files:**
- Modify: `app/pipeline/dry_run.py`, `app/routes/dry_run.py`
- Test: `tests/test_dry_run_api.py` (extend) or `tests/test_enrichment_step.py` (append)

**Interfaces:**
- Consumes: `EnrichmentStep` (Task 2).
- Produces: `run_dry_run(..., ai_service=None)`; `DryRunResult.ai_suggestions: dict[str, dict[str, str]]`; dry-run response gains `"ai_suggestions"`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_enrichment_step.py`:

```python
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

    class FakeIngest:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, ctx):
            ctx.run_state.products = _products()
            ctx.run_state.client_id = ids["client_id"]
            from app.pipeline.steps import StepResult

            return StepResult(processed_count=2)

    monkeypatch.setattr(dry_run_module, "IngestStep", FakeIngest)

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
```

Add these helpers at the top of the test module (after imports):
```python
def _registry_stub():
    from types import SimpleNamespace

    return SimpleNamespace(attributes={})


def _clock_stub():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    return SimpleNamespace(now=lambda: datetime.now(timezone.utc))
```

Also add `MappingDocument` handling: `run_dry_run` applies `feed_source.field_mapping`; an empty mapping document is fine (`field_mapping={}`).

- [ ] **Step 2: Run to verify it fails**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_enrichment_step.py -q`
Expected: FAIL — `run_dry_run() got an unexpected keyword argument 'ai_service'`.

- [ ] **Step 3: Implement**

In `app/pipeline/dry_run.py`:
- Import the step and the AI type:
```python
from .steps import EnrichmentStep, IngestStep, PluginStep, RunState, StepContext
```
- Add the field to `DryRunResult`:
```python
    ai_suggestions: dict[str, Any] = field(default_factory=dict)
```
- Add the parameter and run the step. The context becomes:
```python
async def run_dry_run(
    *,
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any],
    clock: Clock,
    image_probe: Any,
    limit: int | None = None,
    ai_service: Any = None,
) -> DryRunResult:
    logger = logging.getLogger("dry_run")
    run_state = RunState()
    ctx = StepContext(feed_source_id, session_factory, logger, run_state, 0, dry_run=True)
```
- After `await PluginStep(plugin_registry).execute(ctx)` and `processed = list(run_state.products)`, insert:
```python
    await EnrichmentStep(ai_service).execute(ctx)
    ai_suggestions = dict(run_state.ai_suggestions)
```
- Add `ai_suggestions=ai_suggestions` to the returned `DryRunResult(...)`.

In `app/routes/dry_run.py`, pass the service and return the field:
```python
            image_probe=image_probe,
            limit=payload.limit if payload else None,
            ai_service=getattr(state, "ai_service", None),
        )
```
and in the response dict add:
```python
        "ai_suggestions": result.ai_suggestions,
```

- [ ] **Step 4: Run to verify it passes**

Run: `env -u DATABASE_URL TEST_DATABASE_URL="..." uv run pytest tests/test_enrichment_step.py tests/test_dry_run_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/dry_run.py backend/app/routes/dry_run.py backend/tests/test_enrichment_step.py
git commit -m "feat(pipeline): dry-run surfaces AI enrichment suggestions without persisting"
```

---

### Task 4: Docs and final gates

**Files:**
- Modify: `backend/docs/architecture.md`, `backend/docs/api.md`, `TODO.md`

**Interfaces:**
- Consumes: everything above.
- Produces: documentation reflecting the step.

- [ ] **Step 1: Update `backend/docs/architecture.md`**

In the pipeline stages description, add an enrichment bullet after the plugin step and before QC, e.g.:

> **Enrichment (`ai_enrichment`, opt-in)** — when a feed source sets `configuration.ai_enrichment = {enabled, tasks, limit, budget}`, `EnrichmentStep` runs after the plugin step and calls `AiService.run_task` per product for each configured task (`title_optimization`, `description_optimization`, `category_classification`, `attribute_enrichment`). Results are written to the `enrichment` plugin's feed-source `PluginData.suggestions` (pinned values preserved); nothing changes product output until a human accepts fields in the Enrichment UI (Z4). `ok` calls spend one budget unit, `cache_hit` is free, `fallback` counts as a failure; one product's failure never aborts the batch. Dry-run runs the step with `dry_run=True` and returns `ai_suggestions` without persisting.

- [ ] **Step 2: Update `backend/docs/api.md`**

In the dry-run endpoint documentation, add `ai_suggestions` to the response shape: `{total, processed, parse_errors, dropped, findings, sample, ai_suggestions}`.

- [ ] **Step 3: Append a `TODO.md` cycle-log entry**

Add under `## Cycle log` (matching existing format) an entry dated 2026-09-16 for phase B: the `EnrichmentStep` engine in `app/pipeline/enrichment.py`, opt-in `configuration.ai_enrichment`, budget/isolation semantics, dry-run `ai_suggestions`, suggestions written to the Z4 store with human review still gating output, tests, and final gate numbers.

- [ ] **Step 4: Run the full gate suite**

From `backend/`:
```bash
uv run ruff check .          # must print "Found 490 errors"
uv run mypy .                # must end "Success: no issues found"
env -u DATABASE_URL TEST_DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2- | sed 's#^postgresql://#postgresql+asyncpg://#')" \
  uv run pytest -q           # all tests pass
```
Expected: ruff 490 (zero new), mypy exit 0, pytest all green.

- [ ] **Step 5: Commit**

```bash
git add backend/docs/architecture.md backend/docs/api.md TODO.md
git commit -m "docs(pipeline): AI enrichment step architecture, dry-run surface, cycle log"
```

---

## Self-Review

**Spec coverage (phase B):**
- Opt-in pipeline step generating suggestions into the Z4 review store → Tasks 1, 2.
- Per-feed config `configuration.ai_enrichment = {enabled, tasks, limit, budget}` → Task 2.
- Per-item isolation (PluginStep pattern, never `reconcile.py`) → Task 1 (`generate_suggestions` try/except + `fallback` counting).
- Budget semantics mirroring `qc/ai_rules.py` (ok spends, cache_hit free, fallback fails) → Task 1.
- Dry-run preview without persisting → Task 3.
- Human review still gates output → enforced by design: the step writes only `suggestions`; the plugin applies only `pinned`.
- No new concurrency mechanism → `generate_suggestions` calls `AiService.run_task` sequentially; the existing per-provider semaphore throttles (documented in the spec).
- Tests: engine (field mapping, budget, isolation, cache-hit, multi-task, no-service), store round-trip preserving pinned, step gating/persist/dry-run, dry-run integration → Tasks 1–3.

**Placeholder scan:** all code steps contain complete code; no TBD/TODO.

**Type consistency:** `EnrichmentOutcome(suggestions, generated, failed, spent)` is used identically in Tasks 1–3; `StepContext(..., dry_run=)` matches the field added in Task 2; `generate_suggestions` keyword signature is identical between Tasks 1 and 2; `store_suggestions`/`load_enrichment_data` signatures match between Task 1 and the Task 2/3 tests; `TASK_FIELDS`/`DEFAULT_TASKS` names are consistent.

**Known deferrals (not in this plan):** the admin-editable settings/telemetry endpoints and `AiSettingsPage` (phase C); automatic application of suggestions and the physical DB cleanup (phase D).
