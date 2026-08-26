### Task 6: StagingStep + runner wiring

**Files:**
- Create: `backend/app/staging/persistence.py`
- Modify: `backend/app/pipeline/steps.py` (extend `StepContext`, add `StagingStep`, wire `default_steps`)
- Modify: `backend/app/pipeline/runner.py` (pass `ingestion_run_id`)
- Modify: `backend/app/pipeline/__init__.py` (export `StagingStep`)
- Test: `backend/tests/test_staging_step.py`

**Interfaces:**
- Consumes: Tasks 1–4 outputs; models `StagingProduct`/`StagingHistory`; `RunState`.
- Produces:
  - `StepContext` gains keyword field `ingestion_run_id: int = 0` (existing constructions unaffected).
  - `load_stored_rows(session_factory, feed_source_id: int) -> dict[str, StoredRow]`
  - `apply_staging_delta(session_factory, feed_source_id: int, ingestion_run_id: int, delta: StagingDelta, config_hash: str, *, chunk_size: int = 1000) -> dict[str, int]` returning `product_id -> staging_products.pk` for every enqueued product.
  - `StagingStep(chunk_size: int = 1000)` with `name = "staging"`, placed between `MappingStep` and `PluginStep` in `default_steps()`.
  - Statistics key `"staging"` = `{"new", "changed", "unchanged", "reactivated", "removed", "failed"}`; `processed_count = len(enqueue)`; `failed_count = counts.failed`.

Persistence actions per delta list (each chunk wrapped in its own transaction):
- upserts `insert=True` → INSERT `{feed_source_id, ingestion_run_id, product_id, content_hash, config_hash, status="active", last_seen_at=now, removed_at=None, raw_data=product}`, flush chunk for pks.
- upserts `insert=False` → UPDATE by `(feed_source_id, product_id)`: `raw_data`, hashes, `status="active"`, `removed_at=None`, `ingestion_run_id`, `last_seen_at=now`.
- `reactivations` pks → UPDATE `status="active"`, `removed_at=None`, `last_seen_at=now`, `ingestion_run_id`.
- `removals` pks → UPDATE `status="removed"`, `removed_at=now`, `ingestion_run_id`.
- `touches` pks → UPDATE `last_seen_at=now` ONLY (spec §4).
- History: INSERT `StagingHistory(staging_product_id=pk_map[product_id], snapshot=product)` for each upsert with `write_history=True`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staging_step.py`:

```python
import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.staging import StagingHistory, StagingProduct
from app.pipeline import RunState, StepContext
from app.pipeline.steps import StagingStep
from app.staging.delta import StoredRow
from app.staging.hashing import content_hash
from app.staging.persistence import load_stored_rows

pytestmark = pytest.mark.asyncio


class FactoryAdapter:
    def __init__(self, factory):
        self._factory = factory

    def __call__(self):
        return self._factory()


async def _seed(session):
    client = Client(name="Acme")
    session.add(client)
    await session.flush()
    feed_source = FeedSource(client_id=client.id, name="US", source_format="tsv")
    session.add(feed_source)
    await session.flush()
    return feed_source


def _ctx(factory, feed_source_id, products, run_id=1):
    state = RunState(products=list(products))
    return StepContext(
        feed_source_id=feed_source_id,
        session_factory=FactoryAdapter(factory),
        logger=logging.getLogger("test"),
        run_state=state,
        ingestion_run_id=run_id,
    )


async def _staged_rows(factory):
    async with factory() as session:
        result = await session.execute(select(StagingProduct))
        return {row.product_id: row for row in result.scalars()}


async def test_first_run_stages_all_products(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products))

    assert result.statistics["staging"]["new"] == 2
    assert result.processed_count == 2
    rows = await _staged_rows(factory)
    assert set(rows) == {"1", "2"}
    assert all(r.status == "active" for r in rows.values())
    assert rows["1"].raw_data == products[0]
    await engine.dispose()


async def test_identical_rerun_touches_only(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=2))

    assert result.statistics["staging"]["unchanged"] == 1
    assert result.processed_count == 0
    async with factory() as session:
        row = (await session.execute(select(StagingProduct))).scalar_one()
        assert row.ingestion_run_id == 1
    await engine.dispose()


async def test_run_state_replaced_with_enqueue_set(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    first = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, first, run_id=1))

    second = [{"id": "1", "title": "CHANGED"}, {"id": "2", "title": "B"}]
    ctx = _ctx(factory, feed_source.id, second, run_id=2)
    await StagingStep().execute(ctx)

    assert [p["id"] for p in ctx.run_state.products] == ["1"]
    async with factory() as session:
        histories = (await session.execute(select(StagingHistory))).scalars().all()
    assert len(histories) == 3
    await engine.dispose()


async def test_config_only_change_no_new_history(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    async with factory() as session:
        async with session.begin():
            row = (await session.execute(select(StagingProduct))).scalar_one()
            row.config_hash = "different"

    ctx = _ctx(factory, feed_source.id, products, run_id=2)
    result = await StagingStep().execute(ctx)

    assert result.statistics["staging"]["changed"] == 1
    async with factory() as session:
        histories = (await session.execute(select(StagingHistory))).scalars().all()
    assert len(histories) == 1
    await engine.dispose()


async def test_removal_then_reactivation_round_trip(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    await StagingStep().execute(_ctx(factory, feed_source.id, products[:1], run_id=2))
    rows = await _staged_rows(factory)
    assert rows["2"].status == "removed"
    assert rows["2"].removed_at is not None

    ctx = _ctx(factory, feed_source.id, products, run_id=3)
    result = await StagingStep().execute(ctx)

    assert result.statistics["staging"]["reactivated"] == 1
    assert [p["id"] for p in ctx.run_state.products] == ["2"]
    rows = await _staged_rows(factory)
    assert rows["2"].status == "active"
    assert rows["2"].removed_at is None
    await engine.dispose()


async def test_invalid_and_duplicate_ids_counted_failed(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [
        {"title": "no id"},
        {"id": "1", "title": "first"},
        {"id": "1", "title": "dup"},
    ]

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products))

    assert result.failed_count == 2
    assert result.statistics["staging"]["failed"] == 2
    rows = await _staged_rows(factory)
    assert set(rows) == {"1"}
    assert rows["1"].raw_data["title"] == "first"
    await engine.dispose()


async def test_load_stored_rows_maps_snapshots(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    await StagingStep().execute(
        _ctx(factory, feed_source.id, [{"id": "1", "title": "A"}], run_id=1)
    )

    stored = await load_stored_rows(FactoryAdapter(factory), feed_source.id)

    assert set(stored) == {"1"}
    row = stored["1"]
    assert isinstance(row, StoredRow)
    assert row.snapshot == {"id": "1", "title": "A"}
    assert row.content_hash == content_hash({"id": "1", "title": "A"})
    await engine.dispose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staging_step.py -v`
Expected: FAIL with `ImportError: cannot import name 'StagingStep'`

- [ ] **Step 3: Write the persistence helper**

Create `backend/app/staging/persistence.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.staging import StagingHistory, StagingProduct
from .delta import StagingDelta, StoredRow


async def load_stored_rows(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
) -> dict[str, StoredRow]:
    async with session_factory() as session:
        result = await session.execute(
            select(StagingProduct).where(
                StagingProduct.feed_source_id == feed_source_id
            )
        )
        return {
            row.product_id: StoredRow(
                pk=row.id,
                product_id=row.product_id,
                content_hash=row.content_hash,
                config_hash=row.config_hash,
                status=row.status,
                snapshot=row.raw_data or {},
            )
            for row in result.scalars()
        }


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def apply_staging_delta(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    ingestion_run_id: int,
    delta: StagingDelta,
    config_hash: str,
    *,
    chunk_size: int = 1000,
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    pk_map: dict[str, int] = {}

    inserts = [u for u in delta.upserts if u.insert]
    updates = [u for u in delta.upserts if not u.insert]

    for group in _chunks(inserts, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                rows = [
                    StagingProduct(
                        feed_source_id=feed_source_id,
                        ingestion_run_id=ingestion_run_id,
                        product_id=u.product_id,
                        content_hash=u.content_hash,
                        config_hash=config_hash,
                        status="active",
                        last_seen_at=now,
                        removed_at=None,
                        raw_data=u.product,
                    )
                    for u in group
                ]
                session.add_all(rows)
                await session.flush()
                for u, row in zip(group, rows):
                    pk_map[u.product_id] = row.id

    for group in _chunks(updates, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for u in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(
                            StagingProduct.feed_source_id == feed_source_id,
                            StagingProduct.product_id == u.product_id,
                        )
                        .values(
                            raw_data=u.product,
                            content_hash=u.content_hash,
                            config_hash=config_hash,
                            status="active",
                            removed_at=None,
                            ingestion_run_id=ingestion_run_id,
                            last_seen_at=now,
                        )
                    )
                    pk_map[u.product_id] = (
                        await session.execute(
                            select(StagingProduct.id).where(
                                StagingProduct.feed_source_id == feed_source_id,
                                StagingProduct.product_id == u.product_id,
                            )
                        )
                    ).scalar_one()

    for group in _chunks(delta.reactivations, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for pk in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(StagingProduct.id == pk)
                        .values(
                            status="active",
                            removed_at=None,
                            ingestion_run_id=ingestion_run_id,
                            last_seen_at=now,
                        )
                    )

    for group in _chunks(delta.removals, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for pk in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(StagingProduct.id == pk)
                        .values(
                            status="removed",
                            removed_at=now,
                            ingestion_run_id=ingestion_run_id,
                        )
                    )

    for group in _chunks(delta.touches, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(StagingProduct)
                    .where(StagingProduct.id.in_(group))
                    .values(last_seen_at=now)
                )

    history_rows = [
        (pk_map[u.product_id], u.product) for u in delta.upserts if u.write_history
    ]
    for group in _chunks(history_rows, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                session.add_all([
                    StagingHistory(staging_product_id=pk, snapshot=snapshot)
                    for pk, snapshot in group
                ])

    return pk_map
```

- [ ] **Step 4: Add StagingStep and wire the pipeline**

In `backend/app/pipeline/steps.py`:

1. Extend the top-level imports:

```python
from dataclasses import asdict, dataclass, field
```

and add below the existing model imports:

```python
from ..staging.config_resolver import resolve_config_bundle
from ..staging.delta import classify
from ..staging.hashing import content_hash
from ..staging.persistence import apply_staging_delta, load_stored_rows
```

2. Change `StepContext` to add the field:

```python
@dataclass(frozen=True)
class StepContext:
    feed_source_id: int
    session_factory: Callable[[], AsyncSession]
    logger: logging.Logger
    run_state: RunState
    ingestion_run_id: int = 0
```

3. Insert this class directly after `MappingStep` ends (before `PluginStep`):

```python
class StagingStep:
    name = "staging"

    def __init__(self, chunk_size: int = 1000) -> None:
        self._chunk_size = chunk_size

    async def execute(self, ctx: StepContext) -> StepResult:
        async with ctx.session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, ctx.feed_source_id)
        if feed_source is None:
            raise LookupError(f"feed source {ctx.feed_source_id} not found")

        async with ctx.session_factory() as session:
            bundle = await resolve_config_bundle(session, feed_source)
        config_hash_value = content_hash(bundle)

        stored = await load_stored_rows(ctx.session_factory, ctx.feed_source_id)
        delta = classify(ctx.run_state.products, stored, config_hash_value)
        if delta.counts.failed:
            ctx.logger.warning(
                "staging: %d unusable products (missing/duplicate id)",
                delta.counts.failed,
            )

        await apply_staging_delta(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            delta,
            config_hash_value,
            chunk_size=self._chunk_size,
        )

        ctx.run_state.products = list(delta.enqueue)
        return StepResult(
            processed_count=len(delta.enqueue),
            failed_count=delta.counts.failed,
            statistics={"staging": asdict(delta.counts)},
        )
```

4. Update `default_steps` at the end of the file:

```python
def default_steps(
    fetcher: HttpFetcher, registry: RegistryDocument
) -> tuple[PipelineStep, ...]:
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(),
        QualityCheckStep(),
        ExportStep(),
    )
```

5. In `backend/app/pipeline/runner.py`, pass the run id into the context inside the step loop:

```python
ctx = StepContext(
    feed_source_id=feed_source_id,
    session_factory=self._session_factory,
    logger=logger,
    run_state=run_state,
    ingestion_run_id=run_id,
)
```

6. In `backend/app/pipeline/__init__.py`, add `StagingStep` to the steps import/export list following how `MappingStep` appears there.

- [ ] **Step 5: Run new tests plus affected suites**

Run: `uv run pytest tests/test_staging_step.py tests/test_mapping_step.py tests/test_ingest_step.py tests/test_pipeline_steps.py tests/test_pipeline_runner.py -v`
Expected: PASS. If an existing test asserts the exact tuple length of `default_steps()`, update that one assertion to 6 and mention it in the commit message.

- [ ] **Step 6: Commit**

```bash
git add app/pipeline/steps.py app/pipeline/runner.py app/pipeline/__init__.py app/staging/persistence.py tests/test_staging_step.py
git commit -m "feat: StagingStep persists staged state and reduces run to delta set"
```

---

