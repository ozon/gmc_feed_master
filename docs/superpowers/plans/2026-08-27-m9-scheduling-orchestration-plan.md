# M9 Scheduling & Run Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining spec-§2 conformance gaps in scheduling/run orchestration (uniform overlap semantics with the spec-mandated log, startup reconciliation of crash-orphaned runs, manual-trigger task references) and prove the behavior with tests and an acceptance gate.

**Architecture:** Most scheduling machinery exists (internal M2): `SchedulerService` (APScheduler, UTC), `PipelineRunner` + `LockRegistry`, manual `POST /run`. This plan modifies four existing files (`pipeline/runner.py`, `pipeline/scheduler.py`, `main.py`, `routes/clients.py`), adds one small module (`pipeline/reconcile.py`), and adds test files. No schema changes, no new dependencies, no new API surface.

**Tech Stack:** FastAPI, APScheduler 3.11.3 (pinned, unchanged), SQLAlchemy 2.0.43 async, pytest + pytest-asyncio + pytest-postgresql (real PostgreSQL, no DB mocks).

**Spec:** `docs/superpowers/specs/2026-08-27-m9-scheduling-orchestration-design.md` (owner-approved 2026-08-27).

## Global Constraints

- TDD mandatory: RED (failing test) → GREEN (minimal code) → commit, per task.
- Tests run against real PostgreSQL via pytest-postgresql. Env: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres` (container `m2-scheduler-runner-postgres-1` must be running). Never hardcode database names; each xdist worker gets its own cloned DB.
- Full suite: `uv run pytest -n auto -q` from `backend/`. Single test: `uv run pytest tests/test_x.py::test_name -v`. Serial gate: `uv run pytest -n0 -q`.
- Baseline before Task 1: **597 passed** (2026-08-27). Every task ends with its new tests green and no regressions.
- No new dependencies. APScheduler stays pinned at `3.11.3`. Behavior claims verified against the installed 3.11.3 source (`schedulers/base.py`: default `max_instances=1`; `MaxInstancesReachedError` → generic warning, job not submitted).
- No code comments unless required for clarity (house style is minimal).
- Commit prefixes per house style: `feat(pipeline):`, `test(pipeline):`, `fix(...)`, `docs:`.
- The plugin contract suite (`tests/test_plugin_contract.py`) must stay green — it runs inside the full suite.
- Do not touch the unstaged `.superpowers/sdd/task-*` files in the main worktree.

## Prerequisites

- [ ] **Create the milestone worktree from current main**

```bash
git worktree add .worktrees/m9-scheduling -b m9-scheduling
```

Record the base SHA (`git rev-parse --short HEAD` in the new worktree) in the progress ledger. All tasks below run inside `.worktrees/m9-scheduling/backend` unless stated otherwise.

- [ ] **Start a fresh M9 cycle section in `.superpowers/sdd/progress.md`** (main worktree, untracked file) with plan/spec paths, branch, worktree, base SHA, and the 597-passed baseline.

---

### Task 1: Runner overlap log + skip reason

Implements design §2.2 (spec §2 wording "previous run still active").

**Files:**
- Modify: `backend/app/pipeline/runner.py` (locked branch of `execute`, lines 31–38)
- Test: `backend/tests/test_pipeline_runner.py` (append two tests)

**Interfaces:**
- Consumes: `LockRegistry.is_locked/get`, `PipelineRunner._finish(feed_source_id, run_id, status, statistics=...)` (existing signature already accepts `statistics: dict | None`)
- Produces: skipped runs carry `statistics == {"reason": "previous run still active"}`; WARNING log `"previous run still active: skipping run for feed source %s"` from logger `app.pipeline.runner`. Task 6 asserts both at acceptance level.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pipeline_runner.py` (`logging` is already imported at the top of this file):

```python
async def test_locked_skip_logs_previous_run_still_active(session_factory, feed_source_id, caplog):
    registry = LockRegistry()
    runner = PipelineRunner(registry, session_factory, [RecordingStep()])
    lock = registry.get(feed_source_id)
    await lock.acquire()
    try:
        with caplog.at_level(logging.WARNING, logger="app.pipeline.runner"):
            run_id = await runner.execute(feed_source_id)
    finally:
        lock.release()
    run = await _get_run(session_factory, run_id)
    assert run.status == "skipped"
    assert run.statistics == {"reason": "previous run still active"}
    assert run.error_message is None
    assert any("previous run still active" in message for message in caplog.messages)


async def test_locked_skip_precreated_run_carries_reason(session_factory, feed_source_id):
    registry = LockRegistry()
    async with session_factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed_source_id, status="pending")
            session.add(run)
            await session.flush()
            run_id = run.id
    runner = PipelineRunner(registry, session_factory, [RecordingStep()])
    lock = registry.get(feed_source_id)
    await lock.acquire()
    try:
        returned_id = await runner.execute(feed_source_id, run_id=run_id)
    finally:
        lock.release()
    assert returned_id == run_id
    run = await _get_run(session_factory, run_id)
    assert run.status == "skipped"
    assert run.statistics == {"reason": "previous run still active"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_runner.py::test_locked_skip_logs_previous_run_still_active tests/test_pipeline_runner.py::test_locked_skip_precreated_run_carries_reason -v`
Expected: FAIL — `run.statistics == {}` (and no "previous run still active" in caplog).

- [ ] **Step 3: Implement the log + reason**

In `backend/app/pipeline/runner.py`, replace the locked branch (current lines 31–38):

```python
    async def execute(self, feed_source_id: int, run_id: int | None = None) -> int | None:
        if self._lock_registry.is_locked(feed_source_id):
            if run_id is None and not await self._feed_source_exists(feed_source_id):
                logger.warning(
                    "feed source %s not found; no run recorded", feed_source_id
                )
                return None
            return await self._finish(feed_source_id, run_id, "skipped")
```

with:

```python
    async def execute(self, feed_source_id: int, run_id: int | None = None) -> int | None:
        if self._lock_registry.is_locked(feed_source_id):
            logger.warning(
                "previous run still active: skipping run for feed source %s",
                feed_source_id,
            )
            if run_id is None and not await self._feed_source_exists(feed_source_id):
                logger.warning(
                    "feed source %s not found; no run recorded", feed_source_id
                )
                return None
            return await self._finish(
                feed_source_id,
                run_id,
                "skipped",
                statistics={"reason": "previous run still active"},
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline_runner.py -v`
Expected: all PASS (including the pre-existing skip tests `test_lock_held_marks_run_skipped_without_executing_steps` and `test_precreated_run_id_skipped_when_lock_held` — they do not assert on `statistics`, so the new value does not break them).

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/runner.py backend/tests/test_pipeline_runner.py
git commit -m "feat(pipeline): log 'previous run still active' and record skip reason"
```

---

### Task 2: Feed jobs get max_instances=2

Implements design §2.1 (scheduled overlaps reach the runner instead of being swallowed by APScheduler's default).

**Files:**
- Modify: `backend/app/pipeline/scheduler.py` (`SchedulerService.register`, lines 51–62)
- Test: `backend/tests/test_scheduler_service.py` (append three tests)

**Interfaces:**
- Consumes: nothing new
- Produces: every feed-source job registered via `register()` has `max_instances == 2`; system jobs keep the APScheduler default `1`. Task 4 asserts this through the lifespan.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_scheduler_service.py`:

```python
def test_register_sets_max_instances_two(service):
    service.register(feed_source(1, "0 * * * *"))
    job = service._scheduler.get_job("feed-source-1")
    assert job.max_instances == 2


def test_system_job_keeps_default_max_instances():
    from app.pipeline.scheduler import SYSTEM_PURGE_JOB_ID, SchedulerService

    service = SchedulerService(runner=FakeRunner())
    service.register_system_job(SYSTEM_PURGE_JOB_ID, "0 3 * * *", lambda: None)
    job = service._scheduler.get_job(SYSTEM_PURGE_JOB_ID)
    assert job.max_instances == 1


def test_register_next_run_time_follows_cron_in_utc(service):
    from datetime import datetime, timezone

    service.register(feed_source(1, "0 * * * *"))
    job = service._scheduler.get_job("feed-source-1")
    now = datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc)
    nxt = job.trigger.get_next_fire_time(None, now)
    assert nxt == datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    assert str(nxt.tzinfo) == "UTC"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_scheduler_service.py::test_register_sets_max_instances_two tests/test_scheduler_service.py::test_system_job_keeps_default_max_instances tests/test_scheduler_service.py::test_register_next_run_time_follows_cron_in_utc -v`
Expected: `test_register_sets_max_instances_two` FAILS (`job.max_instances == 1`); the other two PASS (guards that must stay green).

- [ ] **Step 3: Implement**

In `backend/app/pipeline/scheduler.py`, in `SchedulerService.register`, add `max_instances=2` to the `add_job` call:

```python
    def register(self, feed_source: FeedSource) -> None:
        trigger = validate_cron(feed_source.cron_expression)
        if not self._scheduler.running and self.has_job(feed_source.id):
            self._scheduler.remove_job(job_id(feed_source.id))
        self._scheduler.add_job(
            self._runner.execute,
            trigger,
            args=[feed_source.id],
            id=job_id(feed_source.id),
            replace_existing=True,
            misfire_grace_time=None,
            max_instances=2,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/scheduler.py backend/tests/test_scheduler_service.py
git commit -m "feat(pipeline): dispatch overlapping cron ticks to the runner (max_instances=2)"
```

---

### Task 3: Startup reconciliation module

Implements design §3 (owner-approved; spec silent). New module only — lifespan wiring is Task 4.

**Files:**
- Create: `backend/app/pipeline/reconcile.py`
- Test: `backend/tests/test_reconcile.py`

**Interfaces:**
- Consumes: `IngestionRun` model, `Clock` protocol (`app/clock.py`)
- Produces: `async def reconcile_interrupted_runs(session_factory, clock) -> int` and constant `INTERRUPTED_MESSAGE = "interrupted by restart"`. Task 4 calls it from the lifespan.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_reconcile.py`:

```python
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.models import Client, FeedSource, IngestionRun
from app.pipeline.reconcile import INTERRUPTED_MESSAGE, reconcile_interrupted_runs


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def feed_source_id(session_factory):
    async with session_factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="xml",
                source_url="https://example.com/feed.xml",
            )
            session.add(feed_source)
            await session.flush()
            return feed_source.id


async def _seed_run(factory, feed_source_id, status):
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed_source_id, status=status)
            session.add(run)
            await session.flush()
            return run.id


async def _get_run(factory, run_id):
    async with factory() as session:
        return await session.get(IngestionRun, run_id)


async def test_reconcile_flips_only_nonterminal_runs(session_factory, feed_source_id):
    running_id = await _seed_run(session_factory, feed_source_id, "running")
    pending_id = await _seed_run(session_factory, feed_source_id, "pending")
    success_id = await _seed_run(session_factory, feed_source_id, "success")
    error_id = await _seed_run(session_factory, feed_source_id, "error")
    skipped_id = await _seed_run(session_factory, feed_source_id, "skipped")
    clock = TestClock(datetime(2026, 2, 3, 4, 5, tzinfo=timezone.utc))

    count = await reconcile_interrupted_runs(session_factory, clock)

    assert count == 2
    for run_id in (running_id, pending_id):
        run = await _get_run(session_factory, run_id)
        assert run.status == "error"
        assert run.error_message == INTERRUPTED_MESSAGE
        assert run.completed_at == clock.now()
    assert (await _get_run(session_factory, success_id)).status == "success"
    assert (await _get_run(session_factory, error_id)).status == "error"
    assert (await _get_run(session_factory, skipped_id)).status == "skipped"
    for run_id in (success_id, error_id, skipped_id):
        assert (await _get_run(session_factory, run_id)).error_message != INTERRUPTED_MESSAGE


async def test_reconcile_empty_table_returns_zero(session_factory):
    clock = TestClock(datetime(2026, 2, 3, tzinfo=timezone.utc))
    assert await reconcile_interrupted_runs(session_factory, clock) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reconcile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.reconcile'`.

- [ ] **Step 3: Implement**

Create `backend/app/pipeline/reconcile.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy import update

from ..models.ingestion import IngestionRun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..clock import Clock

INTERRUPTED_MESSAGE = "interrupted by restart"


async def reconcile_interrupted_runs(
    session_factory: Callable[[], AsyncSession],
    clock: Clock,
) -> int:
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                update(IngestionRun)
                .where(IngestionRun.status.in_(("running", "pending")))
                .values(
                    status="error",
                    error_message=INTERRUPTED_MESSAGE,
                    completed_at=clock.now(),
                )
            )
            return result.rowcount
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reconcile.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/reconcile.py backend/tests/test_reconcile.py
git commit -m "feat(pipeline): reconcile crash-orphaned runs at startup"
```

---

### Task 4: Lifespan wiring + integration tests

Implements design §3 wiring and design §5 lifespan coverage (gap G5).

**Files:**
- Modify: `backend/app/main.py` (lifespan, between the purge-job registration and `register_all`, lines ~125–129)
- Test: `backend/tests/test_m9_lifespan.py` (new)

**Interfaces:**
- Consumes: `reconcile_interrupted_runs(session_factory, clock)` and `INTERRUPTED_MESSAGE` from Task 3; `SYSTEM_PURGE_JOB_ID`, `job_id` from `app.pipeline.scheduler`; `SchedulerService` on `app.state.scheduler_service`
- Produces: lifespan that reconciles orphaned runs before `register_all`; integration proof that startup starts the scheduler, registers the purge job, registers feed jobs with `max_instances=2`, reconciles, and shuts down cleanly.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_m9_lifespan.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.pipeline.reconcile import INTERRUPTED_MESSAGE
from app.pipeline.scheduler import SYSTEM_PURGE_JOB_ID, job_id


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_env(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
        export_dir=str(tmp_path / "exports"),
    )
    yield factory, settings, tmp_path
    await engine.dispose()


async def _seed_feed(factory, cron_expression=None):
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="xml",
                source_url="https://example.com/feed.xml",
                cron_expression=cron_expression,
            )
            session.add(feed_source)
            await session.flush()
            return feed_source.id


async def test_lifespan_starts_scheduler_registers_jobs_and_shuts_down(app_env):
    factory, settings, tmp_path = app_env
    fs_id = await _seed_feed(factory, cron_expression="0 * * * *")
    app = create_app(
        settings=settings,
        db_session_factory=factory,
        plugins_dir=tmp_path / "plugins-empty",
    )
    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler_service
        assert scheduler._scheduler.running
        job = scheduler._scheduler.get_job(job_id(fs_id))
        assert job is not None
        assert job.max_instances == 2
        assert scheduler._scheduler.get_job(SYSTEM_PURGE_JOB_ID) is not None
    assert not app.state.scheduler_service._scheduler.running


async def test_lifespan_reconciles_orphaned_runs(app_env):
    factory, settings, tmp_path = app_env
    fs_id = await _seed_feed(factory)
    async with factory() as session:
        async with session.begin():
            session.add(IngestionRun(feed_source_id=fs_id, status="running"))
            session.add(IngestionRun(feed_source_id=fs_id, status="pending"))
            session.add(IngestionRun(feed_source_id=fs_id, status="success"))
    app = create_app(
        settings=settings,
        db_session_factory=factory,
        plugins_dir=tmp_path / "plugins-empty",
    )
    async with app.router.lifespan_context(app):
        pass
    async with factory() as session:
        runs = list(
            (await session.execute(select(IngestionRun).order_by(IngestionRun.id))).scalars()
        )
    assert [run.status for run in runs] == ["error", "error", "success"]
    assert runs[0].error_message == INTERRUPTED_MESSAGE
    assert runs[0].completed_at is not None
    assert runs[2].error_message is None
```

Note: `plugins_dir` points at a nonexistent empty path on purpose — `discover()` returns no candidates for a missing directory (verified in `app/plugins/discovery.py`), isolating the test from the repo's `plugins/` directory.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_m9_lifespan.py -v`
Expected: `test_lifespan_reconciles_orphaned_runs` FAILS with statuses still `["running", "pending", "success"]` (the lifespan does not reconcile yet) — this is the required RED. `test_lifespan_starts_scheduler_registers_jobs_and_shuts_down` may already PASS (scheduler start, purge job, and `max_instances=2` from Task 2 already exist); it is kept as a lifespan-level guard for those behaviors.

- [ ] **Step 3: Wire reconciliation into the lifespan**

In `backend/app/main.py`, inside the lifespan, replace:

```python
                scheduler_service.register_system_job(
                    SYSTEM_PURGE_JOB_ID, PURGE_CRON, run_staging_purge
                )
                async with application.state.db_session_factory() as session:
                    await scheduler_service.register_all(session)
```

with:

```python
                scheduler_service.register_system_job(
                    SYSTEM_PURGE_JOB_ID, PURGE_CRON, run_staging_purge
                )

                from .pipeline.reconcile import reconcile_interrupted_runs

                reconciled = await reconcile_interrupted_runs(
                    application.state.db_session_factory, application.state.clock
                )
                logging.getLogger(__name__).info(
                    "startup reconciliation: marked %s orphaned runs as interrupted",
                    reconciled,
                )
                async with application.state.db_session_factory() as session:
                    await scheduler_service.register_all(session)
```

(`logging` is already imported at module level in `main.py`; the function-local import follows the existing lifespan style used for `purge_expired`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_m9_lifespan.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_m9_lifespan.py
git commit -m "feat(pipeline): reconcile orphaned runs in app lifespan before register_all"
```

---

### Task 5: Manual-trigger task references

Implements design §4 (gap G4; amends the M2 fire-and-forget decision — recorded in Task 7).

**Files:**
- Modify: `backend/app/main.py` (`create_app`, after `app.state.plugin_registry = {}`, line ~158)
- Modify: `backend/app/routes/clients.py` (`trigger_run`, lines 239–241)
- Test: `backend/tests/test_run_trigger_tracking.py` (new)

**Interfaces:**
- Consumes: nothing new
- Produces: `app.state.background_tasks: set[asyncio.Task]`; `trigger_run` adds its task to the set and discards it via done-callback. Task 6's acceptance file relies on nothing here — this task is self-contained.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_run_trigger_tracking.py`:

```python
import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


class StubFetcher:
    async def fetch(self, url, basic_auth=None, _client=None):
        return b"<rss><channel></channel></rss>"


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
        export_dir=str(tmp_path / "exports"),
    )
    app = create_app(settings=settings, db_session_factory=factory, fetcher=StubFetcher())
    yield app, factory
    await engine.dispose()


async def _logged_in_client(app):
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_feed_source(client):
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={
            "name": "Main",
            "source_format": "xml",
            "source_url": "https://example.com/feed.xml",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_manual_run_task_is_tracked_until_done(app_factory):
    app, factory = app_factory
    client = await _logged_in_client(app)
    fs_id = await _seed_feed_source(client)

    started = asyncio.Event()
    release = asyncio.Event()
    real_execute = app.state.pipeline_runner.execute

    async def gated_execute(feed_source_id, run_id=None):
        started.set()
        await release.wait()
        return await real_execute(feed_source_id, run_id=run_id)

    app.state.pipeline_runner.execute = gated_execute

    resp = await client.post(f"/feed-sources/{fs_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    await started.wait()
    assert len(app.state.background_tasks) == 1

    release.set()
    for _ in range(200):
        if not app.state.background_tasks:
            break
        await asyncio.sleep(0.05)
    assert app.state.background_tasks == set()

    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
    assert run.status == "success"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_trigger_tracking.py -v`
Expected: FAIL with `AttributeError: background_tasks` (or `TypeError` on `len`) — `app.state.background_tasks` does not exist yet.

- [ ] **Step 3: Implement**

In `backend/app/main.py` (`create_app`), after the line `app.state.plugin_registry = {}` add:

```python
    app.state.background_tasks = set()
```

In `backend/app/routes/clients.py` (`trigger_run`), replace:

```python
    run_id = run.id
    asyncio.create_task(runner.execute(feed_source_id, run_id=run_id))
    return {"run_id": run_id}
```

with:

```python
    run_id = run.id
    task = asyncio.create_task(runner.execute(feed_source_id, run_id=run_id))
    background_tasks = getattr(request.app.state, "background_tasks", None)
    if background_tasks is not None:
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    return {"run_id": run_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_trigger_tracking.py -v`
Expected: PASS.

- [ ] **Step 5: Regression check on existing trigger coverage**

Run: `uv run pytest tests/test_m2_acceptance.py -v`
Expected: all PASS (the M2 acceptance exercises `POST /run` end-to-end).

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/routes/clients.py backend/tests/test_run_trigger_tracking.py
git commit -m "feat(api): hold strong references to manual-trigger background tasks"
```

---

### Task 6: M9 acceptance tests

Implements design §5 acceptance (gap G6 + spec-level overlap proof).

**Files:**
- Create: `backend/tests/test_m9_acceptance.py`

**Interfaces:**
- Consumes: full app via `create_app(settings=..., db_session_factory=..., fetcher=...)`; `app.state.pipeline_runner` (the scheduled entry point is `runner.execute(feed_source_id)` with no `run_id` — exactly the scheduler's `args=[feed_source.id]`); `app.state.scheduler_service`; `app.state.lock_registry`; `job_id` from `app.pipeline.scheduler`
- Produces: the milestone's "done when" evidence for the scheduled path.

- [ ] **Step 1: Write the acceptance tests**

Create `backend/tests/test_m9_acceptance.py`:

```python
import logging
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.pipeline.scheduler import job_id


pytestmark = pytest.mark.asyncio

WIDE_TSV = (
    "id\ttitle\tdescription\tlink\timage_link\tavailability\tprice\tcondition\tbrand\tgtin\tshipping(country:price)\tshipping(country:price)\n"
    "SKU-1\tRed Shirt\tA red shirt\thttp://shop.example/1\thttp://shop.example/1.jpg\tin_stock\t10.00 USD\tnew\tAcme\t0012345678905\tUS:6.49 USD\tUK:5.99 GBP\n"
    "SKU-2\tBlue Hat\tA blue hat\thttp://shop.example/2\thttp://shop.example/2.jpg\tin_stock\t5.00 USD\tnew\tAcme\t0012345678912\tUS:6.49 USD\n"
).encode("utf-8")


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data

    async def fetch(self, url, basic_auth=None, _client=None):
        return self.data


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
        export_dir=str(tmp_path / "exports"),
        public_base_url="http://test.public",
    )
    app = create_app(settings=settings, db_session_factory=factory, fetcher=StubFetcher(WIDE_TSV))
    yield app, factory, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _create_feed_source(app_factory, cron_expression=None):
    client = await logged_in_client(app_factory)
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    payload = {
        "name": "Main",
        "source_format": "wide_tsv",
        "currency": "USD",
        "source_url": "http://shop.example/feed.tsv",
    }
    if cron_expression is not None:
        payload["cron_expression"] = cron_expression
    resp = await client.post(f"/clients/{client_id}/feed-sources", json=payload)
    assert resp.status_code == 201
    return resp.json()


async def test_scheduled_entry_point_drives_full_pipeline(app_factory):
    app, factory, settings = app_factory
    feed_source = await _create_feed_source(app_factory, cron_expression="0 * * * *")
    fs_id = feed_source["id"]

    run_id = await app.state.pipeline_runner.execute(fs_id)

    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
        staged = list(
            (
                await session.execute(
                    select(StagingProduct).where(StagingProduct.feed_source_id == fs_id)
                )
            ).scalars()
        )
        versions = list(
            (
                await session.execute(
                    select(ExportVersion).where(ExportVersion.feed_source_id == fs_id)
                )
            ).scalars()
        )
        export_runs = list(
            (
                await session.execute(
                    select(ExportRun).where(ExportRun.feed_source_id == fs_id)
                )
            ).scalars()
        )
    assert run.status == "success"
    assert run.error_message is None
    assert len(staged) == 2
    assert len(versions) == 1
    assert versions[0].product_count == 2
    assert len(export_runs) == 1
    assert export_runs[0].status == "completed"
    published = Path(settings.export_dir) / "published" / f"{fs_id}.xml"
    assert published.is_file()
    body = published.read_bytes()
    assert b"<g:id>SKU-1</g:id>" in body
    assert b"<g:id>SKU-2</g:id>" in body


async def test_scheduled_overlap_is_skipped_and_logged(app_factory, caplog):
    app, factory, _ = app_factory
    feed_source = await _create_feed_source(app_factory, cron_expression="0 * * * *")
    fs_id = feed_source["id"]

    lock = app.state.lock_registry.get(fs_id)
    await lock.acquire()
    try:
        job = app.state.scheduler_service._scheduler.get_job(job_id(fs_id))
        assert job is not None
        assert job.max_instances == 2
        with caplog.at_level(logging.WARNING, logger="app.pipeline.runner"):
            run_id = await job.func(*job.args)
    finally:
        lock.release()

    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
    assert run.status == "skipped"
    assert run.statistics == {"reason": "previous run still active"}
    assert run.error_message is None
    assert any("previous run still active" in message for message in caplog.messages)
```

Notes:
- `app.state.pipeline_runner.execute(fs_id)` with no `run_id` is byte-for-byte the call APScheduler makes (`args=[feed_source.id]` in `SchedulerService.register`).
- `job.func(*job.args)` invokes the scheduled job exactly as the scheduler's executor would.
- The wide-TSV fixture and feed-source payload mirror the green M8 acceptance test (`tests/test_m8_acceptance.py`), including the `source_url` requirement of `IngestStep`.

- [ ] **Step 2: Run the acceptance tests**

Run: `uv run pytest tests/test_m9_acceptance.py -v`
Expected: both PASS (all behavior was implemented in Tasks 1–5; any failure here is a wiring regression to fix before continuing).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_m9_acceptance.py
git commit -m "test: M9 acceptance gate — scheduled path and overlap semantics"
```

---

### Task 7: Decision records, gate script, final verification

Implements design §7 and the acceptance gate.

**Files:**
- Modify: `docs/decisions.md` (append under the existing `## 2026-08-27` heading)
- Create: `backend/scripts/verify_m9_gate.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6
- Produces: durable decision records and the milestone gate script; final "done when" evidence.

- [ ] **Step 1: Record the decisions**

Append to `docs/decisions.md` under the existing `## 2026-08-27` heading:

```markdown
### M9 uniform overlap semantics

- **Topic:** Scheduled vs. manual run-overlap handling
- **Decision:** Feed-source jobs are registered with `max_instances=2` so a
  cron tick that fires while a run is still executing is dispatched into
  `PipelineRunner.execute` instead of being swallowed by APScheduler. The
  `LockRegistry` handles every overlap uniformly: the overlapping run
  finalizes as `skipped` with
  `statistics={"reason": "previous run still active"}` and the runner logs
  WARNING "previous run still active: skipping run for feed source <id>"
  (spec §2 wording). System jobs keep APScheduler's default
  `max_instances=1`.
- **Rationale:** Verified against installed APScheduler 3.11.3 source
  (`schedulers/base.py`): the default is 1 and on `MaxInstancesReachedError`
  the scheduler only logs a generic warning — no run row, asymmetric with
  the manual path. The skip path is one small DB write, so at most one
  running plus one briefly-skipping instance coexist; `max_instances=2`
  suffices.

### M9 startup reconciliation of crash-orphaned runs

- **Topic:** `IngestionRun` rows left `running`/`pending` after a crash
- **Decision:** Owner-approved (spec silent). At startup, before
  `register_all`, a single UPDATE marks all `running`/`pending` runs as
  `error` with `error_message='interrupted by restart'` and sets
  `completed_at`; the count is logged at INFO. No new status value, no
  migration. Implemented in `app/pipeline/reconcile.py` with an injectable
  clock.
- **Rationale:** Locks are in-memory; after a restart nothing is actually
  running. Non-terminal rows would otherwise show "running" forever in run
  history and in the M10 status icon.

### M9 manual-trigger task references (amends the M2 decision)

- **Topic:** Strong references for `POST /run` background tasks
- **Decision:** Amendment to the M2 manual-trigger decision: the
  `asyncio.create_task` dispatch is kept, but each task is added to
  `app.state.background_tasks` (a set) with a done-callback that discards
  it. No observable behavior change.
- **Rationale:** CPython may garbage-collect an unreferenced task mid-run;
  the M2 fire-and-forget semantics are preserved while removing the GC
  hazard.

### M9 seam-level cron-fire verification

- **Topic:** How tests prove the scheduled path without real timers
- **Decision:** Tests invoke the scheduled job the way APScheduler would
  (`job.func(*job.args)` — the scheduler's job callable is
  `runner.execute` itself) and assert registration correctness (job id,
  UTC cron trigger, `max_instances=2`, `next_run_time` for a known cron).
  No real-timer wait test.
- **Rationale:** Cron is minute-granular; a live-fire test would wait up
  to 60 s and stay flaky. The seam is the job callable — exercising it
  exercises everything below APScheduler's dispatch.
```

- [ ] **Step 2: Create the gate script**

Create `backend/scripts/verify_m9_gate.py` (pattern copied from `backend/scripts/verify_m6_gate.py`):

```python
#!/usr/bin/env python3
"""M9 acceptance gate — runs the full backend suite serial + parallel,
compileall, and git diff --check as subprocesses.

Run standalone:
    export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
    python scripts/verify_m9_gate.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], timeout: int = 900, **kw) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    print(f"  OK: {' '.join(cmd)}")
    return result


def main() -> None:
    backend = Path(__file__).resolve().parent.parent

    print("=== M9 scheduling & run orchestration gate ===")
    _run([sys.executable, "-m", "pytest", "-n0", "--tb=short", "-q"],
         cwd=backend, timeout=900)
    _run([sys.executable, "-m", "pytest", "--tb=short", "-q"],
         cwd=backend, timeout=900)
    _run([sys.executable, "-m", "compileall", "-q", str(backend / "app")],
         cwd=backend)
    _run(["git", "diff", "--check"],
         cwd=backend.parent)

    print("\nAll gates green.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the gate**

Run (from `backend/`):
`TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run python scripts/verify_m9_gate.py`
Expected: serial suite PASS with 609 tests (597 baseline + 12 new: 2 runner + 3 scheduler + 2 reconcile + 2 lifespan + 1 trigger-tracking + 2 acceptance), parallel suite PASS, compileall clean, `git diff --check` clean. Record the exact count from the run output.

Also run the plugin contract suite explicitly to confirm it is untouched:
`uv run pytest tests/test_plugin_contract.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/decisions.md backend/scripts/verify_m9_gate.py
git commit -m "docs: M9 decisions; add M9 gate script"
```

- [ ] **Step 5: Record milestone completion**

Append an `### M9 final verification` entry to `docs/decisions.md` (same shape as the M8 entry: topic, date, decision "Recorded as complete", the gate evidence with exact test counts, deviations if any). Update the M9 cycle section in `.superpowers/sdd/progress.md` with the task table and final review. Commit:

```bash
git add docs/decisions.md
git commit -m "docs: M9 final verification"
```

- [ ] **Step 6: Final whole-branch review and merge prep**

Run `git diff --stat <base-sha>..HEAD`, review every hunk against the design doc, then follow `superpowers:finishing-a-development-branch` (merge/PR per owner preference).
