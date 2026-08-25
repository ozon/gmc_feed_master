# M2 Design: Scheduler & Pipeline Runner Skeleton

**Date:** 2026-08-25
**Status:** Approved
**Builds on:** M1 (commit `eea6f8f` on `main`)

## Scope

M2 delivers the scheduling and execution skeleton for feed pipelines. Pipeline steps are interfaces with no-op implementations; real ingest/plugins/QC/export land in later milestones.

**In scope:**
- APScheduler wiring (AsyncIOScheduler, in-memory job store, UTC, no catch-up)
- Pipeline runner skeleton with `PipelineStep` protocol and four no-op steps
- Per-feed-source asyncio lock (overlapping runs skipped and logged)
- Minimal client and feed source CRUD APIs
- Manual trigger API (`POST /feed-sources/{id}/run`, async 202)
- IngestionRun lifecycle logging (pending → running → success/error/skipped)
- Run history API (`GET /feed-sources/{id}/ingestion-runs`)
- Alembic migration adding feed source scheduling columns

**Out of scope:**
- Real ingestion, plugin execution, QC rules, XML export
- Frontend (client list, feed source UI, dashboard)
- Field mapping, pipeline builder, export tokens
- Plugin CRUD/config APIs

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scheduler | APScheduler 3.11.3 `AsyncIOScheduler` | Spec-mandated; async-native, shares FastAPI event loop |
| Job store | In-memory, re-registered at startup | Spec's no-catch-up rule makes persistence pointless; simplest |
| Cron validation | Construct APScheduler `CronTrigger` at write time | croniter accepts expressions the trigger rejects; a feed source that never schedules must not fail silently |
| Manual trigger | Async: 202 + `asyncio.create_task` | Same code path as scheduled tick; no HTTP connection held |
| Locking | In-process `asyncio.Lock` per feed source ID | Single-worker constraint (M0 decision) makes this sufficient |
| Pipeline steps | `PipelineStep` protocol + no-op implementations | Later milestones swap in real steps without touching runner |
| Feed source CRUD | Minimal subset included | Scheduler needs real DB data; full features deferred |
| Frontend | None in M2 | Backend-only milestone; UI comes later |

## Architecture

### New package: `backend/app/pipeline/`

```
app/pipeline/
  __init__.py
  steps.py        # PipelineStep protocol, RunContext, StepResult, no-op steps
  runner.py       # PipelineRunner: lock check, IngestionRun lifecycle, step orchestration
  locks.py        # LockRegistry: per-feed-source asyncio.Lock dict
  scheduler.py    # SchedulerService: AsyncIOScheduler wrapper, job CRUD
```

### PipelineStep protocol

```python
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
```

The step-level context is named `StepContext`, not `RunContext`: `RunContext` is reserved for the per-product plugin contract (spec §5.4). Different granularity — merging is not an option.

M2 no-op steps: `IngestStep`, `PluginStep`, `QualityCheckStep`, `ExportStep`. Each logs `"<name>: not implemented (M2 skeleton)"` and returns `StepResult()`.

### PipelineRunner

```python
class PipelineRunner:
    def __init__(self, lock_registry, session_factory, steps: list[PipelineStep]): ...
    async def execute(self, feed_source_id: int, run_id: int | None = None) -> int:  # returns IngestionRun.id
```

`run_id=None` is the scheduled path (runner creates the row); a pre-created `run_id` is the manual-trigger path (API creates the row with `status="pending"` so it can return the ID in the 202 response, runner updates it).

Execution flow:
1. Check lock: if held → create or update the run to `status="skipped"`, return run ID
2. Acquire lock
3. Verify feed source exists; if gone → log, create or update the run to `status="skipped"`, return
4. Create (`status="running"`) or update the existing row to `status="running"`
5. Execute steps sequentially, accumulating counts
6. Finalize: `status="success"`, `completed_at`, counts, merged statistics
7. On exception: `status="error"`, `error_message`, `error_stack_trace`; exception is swallowed (background task must not crash the event loop)
8. Release lock in `finally`

### LockRegistry

```python
class LockRegistry:
    def get(self, feed_source_id: int) -> asyncio.Lock: ...  # lazily created
    def is_locked(self, feed_source_id: int) -> bool: ...
    def discard(self, feed_source_id: int) -> None: ...      # drop entry on feed-source DELETE
```

Held in `app.state.lock_registry`. `discard` is called on feed-source DELETE so the registry does not grow unboundedly; discarding a held lock is a caller error (DELETE is rejected with 409 while runs exist, and the runner releases in `finally`).

### SchedulerService

```python
class SchedulerService:
    def __init__(self, runner: PipelineRunner): ...
    async def start(self) -> None: ...          # starts AsyncIOScheduler
    async def shutdown(self) -> None: ...
    async def register_all(self, session) -> None: ...  # startup: load feed sources, register jobs
    def register(self, feed_source) -> None: ...        # add_job, CronTrigger, UTC, job_id=f"feed-source-{id}"
    def unregister(self, feed_source_id: int) -> None: ...
    def reschedule(self, feed_source) -> None: ...      # remove + re-add
```

- `AsyncIOScheduler(timezone=utc)`, in-memory job store
- No catch-up after downtime comes from the in-memory store + re-registration at startup (jobs simply do not exist across a restart); `misfire_grace_time=None` is set so a late-firing job while the process is up is skipped rather than run late
- Job function: `runner.execute(feed_source_id)`
- Held in `app.state.scheduler_service`

### Lifespan wiring

Existing M1 lifespan extended:

```
startup: DB engine → seeding → scheduler_service.start() → scheduler_service.register_all()
shutdown: scheduler_service.shutdown() → DB engine dispose
```

## Schema changes

New Alembic migration `20260825_0001_m2_feed_source_scheduling.py`:

Add to `feed_sources`:
- `cron_expression` — `String(100)`, nullable (feed sources without a schedule are valid; only scheduled ones get jobs)
- `source_format` — `String(50)`, NOT NULL, default `'tsv'` (XML/TSV/CSV/wide-format TSV per spec §3)
- `target_country` — `String(10)`, nullable
- `target_language` — `String(10)`, nullable
- `currency` — `String(3)`, nullable
- `source_url` — `String(2048)`, nullable

Add to `clients`:
- `contact_details` — `JSONB`, NOT NULL, default `{}`
- `status` — `String(50)`, NOT NULL, default `'active'`

SQLAlchemy models updated to match. Downgrade drops the columns.

## API

All endpoints require a valid session (existing `require_session` dependency).

### Clients

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/clients` | `{name, contact_details?, status?}` | 201 + client |
| GET | `/clients` | — | 200 + list |

- Duplicate name → 409

### Feed sources

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/clients/{id}/feed-sources` | `{name, source_format, cron_expression?, target_country?, target_language?, currency?, source_url?}` | 201 + feed source |
| GET | `/clients/{id}/feed-sources` | — | 200 + list |
| PUT | `/feed-sources/{id}` | partial update of above fields | 200 + feed source |
| DELETE | `/feed-sources/{id}` | — | 204 |

- `cron_expression` validated at write time by constructing the actual APScheduler `CronTrigger`; construction failure → 422. croniter alone is not sufficient because it accepts expressions the trigger rejects.
- POST with valid cron → `scheduler_service.register(feed_source)`; registration failure → the write fails (500), never a silently unscheduled feed source
- PUT with changed cron → `scheduler_service.reschedule(feed_source)`; cron removed → `unregister`
- DELETE → `scheduler_service.unregister(id)`, `lock_registry.discard(id)`, then delete row; if ingestion runs exist (RESTRICT FK) → 409
- Unknown client/feed source → 404

### Manual trigger

| Method | Path | Response |
|---|---|---|
| POST | `/feed-sources/{id}/run` | 202 + `{"run_id": N}` |

- Creates the `IngestionRun` row synchronously with `status="pending"` (so `run_id` is returned), then dispatches `runner.execute(feed_source_id, run_id=...)` via `asyncio.create_task`
- If lock held at dispatch time, runner updates the row to `status="skipped"` — visible in run history
- Unknown feed source → 404

### Run history

| Method | Path | Params | Response |
|---|---|---|---|
| GET | `/feed-sources/{id}/ingestion-runs` | `?limit=50&offset=0` | 200 + paginated list, newest first |

Each entry: `id`, `status`, `started_at`, `completed_at`, `processed_count`, `failed_count`, `error_message`, `statistics`.

## Concurrency

- `LockRegistry` in `app.state`; lazily created `asyncio.Lock` per feed source ID
- Runner checks `is_locked()` before acquiring → skip path writes `IngestionRun(status="skipped")` without blocking
- Background task creates its own DB session via session factory; holds no request-scoped resources
- Single-worker constraint (M0) makes in-process locking sufficient

## Error handling

- Step exception → runner catches, records `error_message` + `error_stack_trace` (truncated to column limits), sets `status="error"`, does not re-raise
- Feed source deleted mid-run → runner verifies existence at start; if gone, logs and writes skipped run
- Scheduler registration failure (invalid cron that slipped past validation) → logged, job not added; does not block startup
- `register_all` at startup tolerates individual feed source failures (log and continue)

## Testing

**Unit (no PostgreSQL):**
- `LockRegistry`: lazy creation, `is_locked` semantics
- No-op steps: contract compliance, zero counts
- `PipelineRunner`: success lifecycle, error lifecycle (exception → error run), skip when locked, missing feed source
- `SchedulerService`: register/unregister/reschedule with real `AsyncIOScheduler` (paused, no clock dependency)
- Cron validation: valid/invalid expressions via `CronTrigger` construction, including expressions croniter accepts but the trigger rejects

**API (PostgreSQL via `isolated_database_url` fixture):**
- Client CRUD: create, duplicate name → 409, list
- Feed source CRUD: create with/without cron, invalid cron → 422, update reschedules, delete unregisters, unknown IDs → 404
- Manual trigger: 202 + run row appears with terminal status; locked → skipped run
- Run history: pagination, ordering, fields present
- Startup: `register_all` registers jobs for existing feed sources

**Acceptance:**
- Full backend suite green with Compose PostgreSQL
- Alembic upgrade/downgrade/re-upgrade verified
- compileall clean

## Deferred FeedSource fields (spec §4)

M2 adds only the scheduling-relevant columns. The remaining §4 fields are tracked to the milestones that need them:

| Field | Lands with |
|---|---|
| `feed_type` | Supplemental feeds milestone (MVP is `primary` only; column added when supplemental feeds are implemented) |
| `export_token` | Export/XML writer milestone (public export URL, token rotation) |
| `history_retention_count` | Export versioning milestone (ExportVersion retention) |
| `volume_drop_threshold_pct` | Quality check milestone (volume-drop safeguard rule) |
| `field_mapping` | Column exists since M1 (JSONB, default `{}`); populated by the field-mapping milestone (auto mapper + manual mapper) |

## Dependencies (exact pins)

- `apscheduler==3.11.3`
