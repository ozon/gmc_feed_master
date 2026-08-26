### Task 7: Purge job + scheduler system-job namespace

**Files:**
- Create: `backend/app/staging/purge.py`
- Modify: `backend/app/pipeline/scheduler.py` (system-job support)
- Modify: `backend/app/main.py` (lifespan registration)
- Test: `backend/tests/test_staging_purge.py`
- Modify: `backend/tests/test_scheduler_service.py` (append system-job tests)

**Interfaces:**
- Consumes: models `StagingProduct`/`StagingHistory`; `validate_cron` (exists in scheduler.py).
- Produces:
  - `REMOVAL_RETENTION_DAYS = 90`, `HISTORY_RETENTION_DAYS = 90`, `PurgeCounts(removed_products: int, history_rows: int)`, `async def purge_expired(session_factory, now: datetime) -> PurgeCounts` in `app.staging.purge`.
  - `SYSTEM_PURGE_JOB_ID = "system-staging-purge"`, `PURGE_CRON = "0 3 * * *"` in `app.pipeline.scheduler`.
  - `SchedulerService.register_system_job(job_id: str, cron_expression: str, func, *args) -> None` — same `add_job` parameters as feed-source jobs (`misfire_grace_time=None`, `replace_existing=True`) but keyed by the caller-supplied id.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staging_purge.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.staging import StagingHistory, StagingProduct
from app.staging.purge import purge_expired

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


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


async def _product(factory, feed_source, pid, status, removed_at, recorded_at=NOW):
    async with factory() as session:
        async with session.begin():
            row = StagingProduct(
                feed_source_id=feed_source.id,
                ingestion_run_id=1,
                product_id=pid,
                content_hash="h",
                config_hash="c",
                status=status,
                raw_data={},
            )
            session.add(row)
            await session.flush()
            history = StagingHistory(staging_product_id=row.id, snapshot={})
            session.add(history)
            await session.flush()
            pk, history_pk = row.id, history.id
        if status == "removed":
            await session.execute(
                text(
                    "UPDATE staging_products SET removed_at = :ra WHERE id = :pk"
                ),
                {"ra": removed_at, "pk": pk},
            )
        await session.execute(
            text("UPDATE staging_history SET recorded_at = :t WHERE id = :pk"),
            {"t": recorded_at, "pk": history_pk},
        )
    return pk, history_pk


async def test_purge_removes_expired_rows_only(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)

    expired_pk, expired_hist = await _product(
        factory, feed_source, "old", "removed", NOW - timedelta(days=91)
    )
    fresh_pk, fresh_hist = await _product(
        factory, feed_source, "recent", "removed", NOW - timedelta(days=10)
    )
    active_pk, aged_hist = await _product(
        factory, feed_source, "active", "active", None,
        recorded_at=NOW - timedelta(days=91),
    )

    counts = await purge_expired(FactoryAdapter(factory), NOW)

    assert counts.removed_products == 1
    assert counts.history_rows == 2
    async with factory() as session:
        remaining_products = {
            row.product_id
            for row in (await session.execute(select(StagingProduct))).scalars()
        }
        remaining_history = {
            row.id for row in (await session.execute(select(StagingHistory))).scalars()
        }
    assert remaining_products == {"recent", "active"}
    assert remaining_history == {fresh_hist}
    await engine.dispose()


async def test_purge_on_empty_tables_is_zero(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    counts = await purge_expired(FactoryAdapter(factory), NOW)

    assert counts == (0, 0) or counts.removed_products == 0 and counts.history_rows == 0
    await engine.dispose()
```

Append to `backend/tests/test_scheduler_service.py`:

```python
class TestSystemJobs:
    def test_register_system_job_uses_given_id(self):
        from app.pipeline.scheduler import SYSTEM_PURGE_JOB_ID, SchedulerService

        service = SchedulerService(runner=_runner_stub())
        service.register_system_job(SYSTEM_PURGE_JOB_ID, "0 3 * * *", lambda: None)
        jobs = service._scheduler.get_jobs()
        assert [job.id for job in jobs] == [SYSTEM_PURGE_JOB_ID]

    def test_feed_source_lifecycle_never_touches_system_job(self):
        from types import SimpleNamespace

        from app.pipeline.scheduler import SYSTEM_PURGE_JOB_ID, SchedulerService

        service = SchedulerService(runner=_runner_stub())
        service.register_system_job(SYSTEM_PURGE_JOB_ID, "0 3 * * *", lambda: None)
        service.register(SimpleNamespace(id=1, cron_expression="0 * * * *"))
        service.unregister(1)

        assert service._scheduler.get_job(SYSTEM_PURGE_JOB_ID) is not None
```

Adapt `_runner_stub()` to whatever helper the existing tests in that file use to build the runner (mirror them exactly; if they construct `PipelineRunner(...)` inline, do the same). The key point: neither new call touches the runner.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staging_purge.py tests/test_scheduler_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'purge_expired'`; `AttributeError: 'SchedulerService' object has no attribute 'register_system_job'`

- [ ] **Step 3: Implement the purge module**

Create `backend/app/staging/purge.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.staging import StagingHistory, StagingProduct

REMOVAL_RETENTION_DAYS = 90
HISTORY_RETENTION_DAYS = 90


@dataclass(frozen=True)
class PurgeCounts:
    removed_products: int
    history_rows: int


async def purge_expired(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
) -> PurgeCounts:
    removal_cutoff = now - timedelta(days=REMOVAL_RETENTION_DAYS)
    history_cutoff = now - timedelta(days=HISTORY_RETENTION_DAYS)

    async with session_factory() as session:
        async with session.begin():
            removed = await session.execute(
                delete(StagingProduct)
                .where(
                    StagingProduct.status == "removed",
                    StagingProduct.removed_at < removal_cutoff,
                )
                .returning(StagingProduct.id)
            )
            history = await session.execute(
                delete(StagingHistory)
                .where(StagingHistory.recorded_at < history_cutoff)
                .returning(StagingHistory.id)
            )
            return PurgeCounts(
                removed_products=len(removed.scalars().all()),
                history_rows=len(history.scalars().all()),
            )
```

- [ ] **Step 4: Extend the scheduler**

In `backend/app/pipeline/scheduler.py`, add next to `job_id` at module level:

```python
SYSTEM_PURGE_JOB_ID = "system-staging-purge"
PURGE_CRON = "0 3 * * *"
```

Add this method to `SchedulerService` after `reschedule`:

```python
    def register_system_job(
        self,
        job_id: str,
        cron_expression: str,
        func,
        *args,
    ) -> None:
        trigger = validate_cron(cron_expression)
        self._scheduler.add_job(
            func,
            trigger,
            args=list(args),
            id=job_id,
            replace_existing=True,
            misfire_grace_time=None,
        )
```

- [ ] **Step 5: Wire startup in main.py**

In `backend/app/main.py`, inside the lifespan right before `await scheduler_service.register_all(session)` (keep `register_all` as-is), add:

```python
                from datetime import datetime, timezone

                from .pipeline.scheduler import PURGE_CRON, SYSTEM_PURGE_JOB_ID
                from .staging.purge import purge_expired

                async def run_staging_purge() -> None:
                    counts = await purge_expired(
                        application.state.db_session_factory,
                        datetime.now(timezone.utc),
                    )
                    logging.getLogger(__name__).info(
                        "staging purge: %s removed products, %s history rows",
                        counts.removed_products,
                        counts.history_rows,
                    )

                scheduler_service.register_system_job(
                    SYSTEM_PURGE_JOB_ID, PURGE_CRON, run_staging_purge
                )
```

Implementation notes:
- APScheduler's AsyncIOScheduler awaits coroutine functions natively, so the job callable is async.
- Ensure `logging` is imported at the top of `main.py` (check; add if missing).
- Registration order relative to `register_all` does not matter — the two job-id namespaces are disjoint by construction.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_staging_purge.py tests/test_scheduler_service.py tests/test_scheduler_startup.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/staging/purge.py app/pipeline/scheduler.py app/main.py tests/test_staging_purge.py tests/test_scheduler_service.py
git commit -m "feat: daily staging purge as namespaced system scheduler job"
```

---

