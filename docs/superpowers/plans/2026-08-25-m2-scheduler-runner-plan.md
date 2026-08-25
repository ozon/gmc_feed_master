# M2 Implementation Plan: Scheduler & Pipeline Runner Skeleton

**Date:** 2026-08-25
**Spec:** `docs/superpowers/specs/2026-08-25-m2-scheduler-runner-design.md`
**Base:** `main` at `8319ccd`
**Execution:** isolated worktree `.worktrees/m2-scheduler-runner`, branch `m2-scheduler-runner` (create via `superpowers:using-git-worktrees` before Task 1)

## Conventions (read first)

- Backend lives in `backend/`; run commands from there with `uv run ...`
- Models: SQLAlchemy 2.x typed `Mapped[...]`/`mapped_column(...)`, `from app.db.base import Base`
- Tests: pytest + pytest-asyncio (`asyncio_mode` is not set — mark async tests `@pytest.mark.asyncio`); PostgreSQL-backed tests use the `isolated_database_url` fixture from `tests/conftest.py` (requires `TEST_DATABASE_URL` and Compose PostgreSQL running)
- PostgreSQL test app pattern: see `tests/test_postgres_auth.py` (`create_app(settings=..., db_session_factory=...)` + `AsyncClient(transport=ASGITransport(app=app))`)
- Exact dependency pins in `backend/pyproject.toml`; commit `uv.lock`
- TDD: write failing test → implement → green → commit per task
- No comments in code unless required for clarity of a non-obvious decision

## File map

| File | Responsibility |
|---|---|
| `backend/pyproject.toml` | add `apscheduler==3.11.3` |
| `backend/alembic/versions/20260825_0001_m2_feed_source_scheduling.py` | rename `source_type`→`source_format`, add scheduling columns |
| `backend/app/models/feed_source.py` | new columns on model |
| `backend/app/models/client.py` | `contact_details`, `status` |
| `backend/app/pipeline/__init__.py` | package exports |
| `backend/app/pipeline/steps.py` | `StepContext`, `StepResult`, `PipelineStep`, four no-op steps |
| `backend/app/pipeline/locks.py` | `LockRegistry` |
| `backend/app/pipeline/runner.py` | `PipelineRunner` |
| `backend/app/pipeline/scheduler.py` | `validate_cron`, `SchedulerService` |
| `backend/app/routes/__init__.py` | router package |
| `backend/app/routes/clients.py` | client + feed source CRUD, manual trigger, run history |
| `backend/app/schemas/clients.py` | pydantic request/response models |
| `backend/app/main.py` | include router, lifespan wiring |
| `backend/tests/test_pipeline_steps.py` | step contract tests |
| `backend/tests/test_lock_registry.py` | lock registry tests |
| `backend/tests/test_pipeline_runner.py` | runner lifecycle (PostgreSQL) |
| `backend/tests/test_scheduler_service.py` | scheduler + cron validation tests |
| `backend/tests/test_clients_api.py` | CRUD API tests (PostgreSQL) |
| `backend/tests/test_runs_api.py` | trigger + history tests (PostgreSQL) |
| `backend/tests/test_m2_acceptance.py` | milestone gate |

---

## Task 1: Dependency, migration, models

**Files:** `backend/pyproject.toml`, `backend/uv.lock`, `backend/alembic/versions/20260825_0001_m2_feed_source_scheduling.py`, `backend/app/models/feed_source.py`, `backend/app/models/client.py`, `backend/tests/test_m2_migration.py`

1. `uv add "apscheduler==3.11.3"` (runtime dependency), commit lockfile.
2. Write failing test `tests/test_m2_migration.py`: against `isolated_database_url`, run Alembic `upgrade head`, inspect `feed_sources` columns (`source_format` present, `source_type` absent, `cron_expression`, `target_country`, `target_language`, `currency`, `source_url`), inspect `clients` columns (`contact_details`, `status`), then `downgrade -1` and assert columns reverted, then `upgrade head` again. Follow the pattern in `tests/test_migrations.py`.
3. Create migration `20260825_0001_m2_feed_source_scheduling.py`:
   - `op.alter_column('feed_sources', 'source_type', new_column_name='source_format', existing_type=sa.String(length=100), type_=sa.String(length=50), existing_nullable=False)`
   - add `feed_sources.cron_expression` `String(100)` nullable
   - add `feed_sources.target_country` `String(10)` nullable
   - add `feed_sources.target_language` `String(10)` nullable
   - add `feed_sources.currency` `String(3)` nullable
   - add `feed_sources.source_url` `String(2048)` nullable
   - add `clients.contact_details` `JSONB` NOT NULL `server_default='{}'`
   - add `clients.status` `String(50)` NOT NULL `server_default='active'`
   - downgrade reverses all (rename back, drop columns)
4. Update models to match (`source_format: Mapped[str] = mapped_column(String(50), nullable=False)` etc.; `cron_expression: Mapped[str | None]`, `contact_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)`, `status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")`).
5. Run: migration test with Compose PostgreSQL + `TEST_DATABASE_URL`, full backend suite, `uv run python -m compileall app alembic registry`.
6. Commit.

---

## Task 2: Step protocol, no-op steps, LockRegistry

**Files:** `backend/app/pipeline/__init__.py`, `backend/app/pipeline/steps.py`, `backend/app/pipeline/locks.py`, `backend/tests/test_pipeline_steps.py`, `backend/tests/test_lock_registry.py`

1. Failing tests first:
   - `test_pipeline_steps.py`: each of `IngestStep`, `PluginStep`, `QualityCheckStep`, `ExportStep` has a distinct `name`, `execute(StepContext)` returns `StepResult(processed_count=0, failed_count=0)`; `DEFAULT_STEPS` contains exactly those four in pipeline order; `StepContext`/`StepResult` are frozen dataclasses. Use a dummy session factory (`lambda: None`) and `logging.getLogger("test")`.
   - `test_lock_registry.py`: `get(id)` returns an `asyncio.Lock`, same object on repeat calls, distinct per id; `is_locked` false initially, true while held, false after release; `discard(id)` removes the entry (next `get` returns a new lock), discarding an unknown id is a no-op.
2. Implement `steps.py`:

```python
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class StepContext:
    feed_source_id: int
    session_factory: Callable[[], AsyncSession]
    logger: logging.Logger


@dataclass(frozen=True)
class StepResult:
    processed_count: int = 0
    failed_count: int = 0
    statistics: dict[str, Any] = field(default_factory=dict)


class PipelineStep(Protocol):
    name: str

    async def execute(self, ctx: StepContext) -> StepResult: ...


class _NoOpStep:
    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, ctx: StepContext) -> StepResult:
        ctx.logger.info("%s: not implemented (M2 skeleton)", self.name)
        return StepResult()


IngestStep = lambda: _NoOpStep("ingest")          # replace with real classes if preferred;
PluginStep = lambda: _NoOpStep("run_plugins")     # tests only require name + contract
QualityCheckStep = lambda: _NoOpStep("quality_check")
ExportStep = lambda: _NoOpStep("export")

DEFAULT_STEPS: list[PipelineStep] = [IngestStep(), PluginStep(), QualityCheckStep(), ExportStep()]
```

(Implementer may use explicit subclasses instead of the lambda factories if cleaner — tests define the contract.)

3. Implement `locks.py`:

```python
from __future__ import annotations

import asyncio


class LockRegistry:
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    def get(self, feed_source_id: int) -> asyncio.Lock:
        lock = self._locks.get(feed_source_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[feed_source_id] = lock
        return lock

    def is_locked(self, feed_source_id: int) -> bool:
        lock = self._locks.get(feed_source_id)
        return lock is not None and lock.locked()

    def discard(self, feed_source_id: int) -> None:
        self._locks.pop(feed_source_id, None)
```

4. `pipeline/__init__.py` exports `StepContext`, `StepResult`, `PipelineStep`, `DEFAULT_STEPS`, `LockRegistry`.
5. Run tests, compileall, commit.

---

## Task 3: PipelineRunner

**Files:** `backend/app/pipeline/runner.py`, `backend/tests/test_pipeline_runner.py`

Runner contract (spec §Architecture):

```python
class PipelineRunner:
    def __init__(self, lock_registry: LockRegistry, session_factory, steps: list[PipelineStep]) -> None: ...
    async def execute(self, feed_source_id: int, run_id: int | None = None) -> int: ...
```

Behavior:
- Lock held → create run (`status="skipped"`) or update pre-created run to `skipped`, set `completed_at`, return run id — without acquiring the lock
- Acquire lock; in `finally` release
- Feed source missing (select by id returns None) → create/update run to `skipped`, return
- Create run (`status="running"`) or update pre-created `pending` run to `running`
- Execute steps in order with `StepContext(feed_source_id, session_factory, logger)`; sum `processed_count`/`failed_count`, merge `statistics`
- Success → `status="success"`, `completed_at`, counts, statistics
- Exception → `status="error"`, `error_message` (str(exc) truncated to 4000), `error_stack_trace` (`traceback.format_exc()` truncated to 20000), `completed_at`; swallow exception
- Each phase commits its own session (`async with session_factory() as session: async with session.begin(): ...`)
- `completed_at` from `datetime.now(timezone.utc)`

Tests (`test_pipeline_runner.py`, PostgreSQL-backed via `isolated_database_url`, follow `test_postgres_sessions.py` fixture style — create engine/factory, run nothing else; insert `Client` + `FeedSource` rows directly):
- success path with no-op steps → run row `success`, counts 0, `completed_at` set
- success path with counting fake steps → counts summed, statistics merged
- failing step → run row `error` with message + stack trace, exception does not propagate
- lock held by another task → run row `skipped`, steps not executed (use a fake step that records calls)
- missing feed source id → `skipped`
- pre-created `run_id` (status `pending`) → same row updated through lifecycle, no second row created
- returns the run id in all paths

Run with Compose PostgreSQL, plus full suite regression, compileall. Commit.

---

## Task 4: Cron validation + SchedulerService

**Files:** `backend/app/pipeline/scheduler.py`, `backend/tests/test_scheduler_service.py`

1. Failing tests first (`test_scheduler_service.py`, no DB needed — construct lightweight stand-in objects with `id` and `cron_expression` attributes, e.g. `types.SimpleNamespace`):
   - `validate_cron("0 * * * *")` returns a `CronTrigger`
   - `validate_cron("not a cron")` raises `ValueError`
   - an expression croniter would accept but APScheduler rejects raises `ValueError` (find one empirically, e.g. a 6-field expression with unsupported seconds semantics or invalid month name — verify against installed APScheduler 3.11.3 and pin the example in the test)
   - `register(fs)` adds job with id `feed-source-{id}` and the feed source's cron; duplicate register replaces without error
   - `unregister(id)` removes the job; unregistering unknown id is a no-op
   - `reschedule(fs)` updates the trigger to the new expression
   - scheduler timezone is UTC; job's `misfire_grace_time` is None
   - `start()`/`shutdown()` are idempotent enough for lifespan use (shutdown without start does not raise)
2. Implement:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from ..models.feed_source import FeedSource
    from .runner import PipelineRunner

logger = logging.getLogger(__name__)


def validate_cron(expression: str) -> CronTrigger:
    try:
        return CronTrigger.from_crontab(expression, timezone="UTC")
    except ValueError as exc:
        raise ValueError(f"invalid cron expression {expression!r}: {exc}") from exc


def job_id(feed_source_id: int) -> str:
    return f"feed-source-{feed_source_id}"


class SchedulerService:
    def __init__(self, runner: PipelineRunner) -> None:
        self._runner = runner
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    async def start(self) -> None:
        self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def register(self, feed_source: FeedSource) -> None:
        trigger = validate_cron(feed_source.cron_expression)
        self._scheduler.add_job(
            self._runner.execute,
            trigger,
            args=[feed_source.id],
            id=job_id(feed_source.id),
            replace_existing=True,
            misfire_grace_time=None,
        )

    def unregister(self, feed_source_id: int) -> None:
        self._scheduler.remove_job(job_id(feed_source_id)) if self.has_job(feed_source_id) else None

    def has_job(self, feed_source_id: int) -> bool:
        return self._scheduler.get_job(job_id(feed_source_id)) is not None

    def reschedule(self, feed_source: FeedSource) -> None:
        self.register(feed_source)

    async def register_all(self, session) -> int:
        from sqlalchemy import select
        from ..models.feed_source import FeedSource

        result = await session.execute(select(FeedSource))
        registered = 0
        for feed_source in result.scalars():
            if not feed_source.cron_expression:
                continue
            try:
                self.register(feed_source)
                registered += 1
            except ValueError:
                logger.exception("failed to register feed source %s", feed_source.id)
        return registered
```

(Implementer may tidy `unregister`; contract is what tests assert.)
3. Export `validate_cron`, `SchedulerService`, `job_id` from `pipeline/__init__.py`.
4. Run tests, full suite, compileall. Commit.

---

## Task 5: Schemas + client/feed-source CRUD API

**Files:** `backend/app/schemas/__init__.py`, `backend/app/schemas/clients.py`, `backend/app/routes/__init__.py`, `backend/app/routes/clients.py`, `backend/app/main.py`, `backend/tests/test_clients_api.py`

1. Schemas (`app/schemas/clients.py`, pydantic v2):
   - `ClientCreate {name: str (min 1, max 255), contact_details: dict = {}, status: str = "active"}`
   - `ClientOut {id, name, contact_details, status, created_at}` (`from_attributes=True`)
   - `FeedSourceCreate {name, source_format: Literal["xml","tsv","csv","wide_tsv"], cron_expression: str | None, target_country/language/currency/source_url: str | None}`
   - `FeedSourceUpdate` — all fields optional
   - `FeedSourceOut {id, client_id, name, source_format, cron_expression, target_country, target_language, currency, source_url, created_at, updated_at}`
2. Router `app/routes/clients.py` (`APIRouter`, all endpoints `Depends(require_user)` from `app.auth`; DB session via `Depends(get_db_session)` — if `None`, raise 503):
   - `POST /clients` → insert, unique-name violation (`IntegrityError` on `uq_clients_name`) → 409; 201 + `ClientOut`
   - `GET /clients` → list ordered by name
   - `POST /clients/{client_id}/feed-sources` → 404 unknown client; validate cron via `validate_cron` → 422 on `ValueError`; insert; if cron set, `request.app.state.scheduler_service.register(feed_source)` inside try — registration failure → rollback + 500; 201 + `FeedSourceOut`
   - `GET /clients/{client_id}/feed-sources` → 404 unknown client, list ordered by name
   - `PUT /feed-sources/{id}` → 404 unknown; apply provided fields; cron handling: new valid cron → validate (422 on invalid) + `reschedule`; cron set to `None` → `unregister`; 200 + `FeedSourceOut`
   - `DELETE /feed-sources/{id}` → 404 unknown; `IntegrityError` (existing ingestion runs, RESTRICT) → 409; on success `scheduler_service.unregister(id)` + `lock_registry.discard(id)`; 204
   - Guard all `app.state.scheduler_service`/`lock_registry` access with `getattr(..., None)` so in-memory test apps without DB keep working (skip scheduling side effects when absent)
3. Include router in `create_app` (`app.include_router(clients_router)`).
4. Tests (`test_clients_api.py`, PostgreSQL-backed; logged-in client pattern from `test_postgres_auth.py`; app created with `settings` + `db_session_factory` so lifespan builds scheduler service):
   - create client 201, duplicate name 409, list
   - create feed source without cron 201 (no job), with valid cron 201 + job registered (`app.state.scheduler_service.has_job(id)`), invalid cron 422
   - unknown client 404 on both feed source endpoints
   - update cron → rescheduled; clear cron → unregistered; invalid cron on update 422
   - delete feed source → 204 + job gone + lock entry discarded; delete unknown 404
   - all endpoints without session → 401
5. Run with Compose PostgreSQL, full suite, compileall. Commit.

---

## Task 6: Manual trigger + run history API

**Files:** `backend/app/routes/clients.py` (extend), `backend/app/schemas/clients.py` (extend), `backend/tests/test_runs_api.py`

1. Extend router:
   - `POST /feed-sources/{id}/run` → 404 unknown; require `app.state.pipeline_runner` (503 if absent); insert `IngestionRun(feed_source_id=id, status="pending")`, commit, capture id; `asyncio.create_task(runner.execute(id, run_id=run_id))`; 202 + `{"run_id": run_id}`
   - `GET /feed-sources/{id}/ingestion-runs?limit=50&offset=0` → 404 unknown; `limit` clamped 1..200 default 50, `offset` ≥ 0; select ordered `started_at DESC, id DESC`; return list of `{id, status, started_at, completed_at, processed_count, failed_count, error_message, statistics}`
2. Tests (`test_runs_api.py`, PostgreSQL-backed):
   - trigger unknown feed source → 404
   - trigger → 202 with `run_id`; poll/await until the run reaches a terminal status (`success` for no-op steps) by querying the DB directly; assert single row, counts 0
   - trigger while lock held (acquire the lock via `app.state.lock_registry` first) → 202, run ends `skipped`
   - history: seed runs directly, assert ordering, pagination (`limit`/`offset`), field presence
   - unauthenticated → 401
   - Background task completion: tests must await task completion deterministically — either poll the DB with a short `asyncio.sleep` loop with timeout, or hold a reference to created tasks via a small test hook; prefer polling with `asyncio.timeout(5)`
3. Run with Compose PostgreSQL, full suite, compileall. Commit.

---

## Task 7: Lifespan wiring + startup registration

**Files:** `backend/app/main.py`, `backend/tests/test_scheduler_startup.py`

1. In `create_app` lifespan, after user seeding, when `db_session_factory is not None`:

```python
from .pipeline import DEFAULT_STEPS, LockRegistry, PipelineRunner, SchedulerService

lock_registry = LockRegistry()
runner = PipelineRunner(lock_registry, db_session_factory, list(DEFAULT_STEPS))
scheduler_service = SchedulerService(runner)
application.state.lock_registry = lock_registry
application.state.pipeline_runner = runner
application.state.scheduler_service = scheduler_service
await scheduler_service.start()
async with db_session_factory() as session:
    await scheduler_service.register_all(session)
```

In shutdown, before engine dispose: `scheduler_service = getattr(application.state, "scheduler_service", None)` → `await scheduler_service.shutdown()` if present.

2. Tests (`test_scheduler_startup.py`, PostgreSQL-backed):
   - seed a client + two feed sources (one with cron `0 * * * *`, one without) directly in DB, then start app via `AsyncClient` lifespan (or `TestClient` context manager); assert `has_job` true for the scheduled one, false for the other; `lock_registry`/`pipeline_runner` present on `app.state`
   - feed source with invalid cron already in DB (insert bypassing API) → startup still succeeds, that source not registered, others registered
   - app without DB (injected `session_store`) → no scheduler attributes, app still serves `/health`
3. Run with Compose PostgreSQL, full suite, compileall. Commit.

---

## Task 8: CI + M2 acceptance

**Files:** `backend/tests/test_m2_acceptance.py`, `docs/decisions.md` (append M2 acceptance entry at the end)

1. Acceptance test (PostgreSQL-backed, single end-to-end scenario):
   - login → create client → create feed source with cron `*/5 * * * *` → job registered
   - manual trigger → 202 → run reaches `success`
   - run history returns the run with all fields
   - invalid cron on create → 422
   - update cron → rescheduled; delete feed source → job gone
   - Alembic at head; 15 tables + no schema drift (reuse M1 acceptance pattern)
2. Verify CI workflow needs no changes (pytest + compileall already cover new modules; no new services). If `ci.yml` needs no edit, say so in the report.
3. Full gate from `backend/`:
   - `uv run python -m compileall app alembic registry`
   - `uv run pytest -q` with Compose PostgreSQL + `TEST_DATABASE_URL`
   - `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
   - `git diff --check`
4. Append M2 acceptance entry to `docs/decisions.md` (same format as M1 final verification, with resolved APScheduler version).
5. Commit.

---

## Self-review notes

- Spec coverage: every spec section maps to a task (schema → T1, steps/locks → T2, runner → T3, scheduler/cron → T4, CRUD → T5, trigger/history → T6, lifespan → T7, acceptance → T8). Deferred-fields table and decisions.md entries are spec/doc artifacts already done.
- No placeholders: all code blocks are complete or explicitly delegate a named contract to tests.
- Type/consistency check: `StepContext` name used consistently (never `RunContext`); `source_format` rename only in T1 migration + model; `run_id` optional param consistent between T3 runner and T6 endpoint; `lock_registry.discard` called only in T5 DELETE.
