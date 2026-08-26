# Task 7 Report: Purge job + scheduler system-job namespace

## Status
COMPLETE

## Commit
- `016b8e9` feat: daily staging purge as namespaced system scheduler job (5 files changed, 229 insertions)

## Implementation
- **Created `backend/app/staging/purge.py`**: `REMOVAL_RETENTION_DAYS = 90`, `HISTORY_RETENTION_DAYS = 90`, frozen dataclass `PurgeCounts(removed_products, history_rows)`, and `async def purge_expired(session_factory, now) -> PurgeCounts` running both deletes in one transaction.
- **Modified `backend/app/pipeline/scheduler.py`**: module-level `SYSTEM_PURGE_JOB_ID = "system-staging-purge"` and `PURGE_CRON = "0 3 * * *"` next to `job_id`; new `SchedulerService.register_system_job(job_id, cron_expression, func, *args)` after `reschedule`, using the same `add_job` parameters as feed-source jobs (`misfire_grace_time=None`, `replace_existing=True`) keyed by caller-supplied id.
- **Modified `backend/app/main.py`**: added `import logging` at top; in lifespan before `register_all` (kept as-is), registered the ASYNC coroutine job `run_staging_purge()` which calls `purge_expired(application.state.db_session_factory, datetime.now(timezone.utc))` and logs counts. Used ONLY the async variant from the brief.

## Tests
- **Created `backend/tests/test_staging_purge.py`** per the brief: expired removed product purged, fresh removed product kept, active product with aged history keeps product but loses aged history row; empty-tables case returns zeros.
- **Appended `TestSystemJobs` to `backend/tests/test_scheduler_service.py`**, mirroring existing style (`SchedulerService(runner=FakeRunner())`, existing `feed_source()` helper).

### Deviations from the brief's literal test code (all required to make the brief's own assertions pass)
1. `_seed()` also inserts `IngestionRun(id=1, ...)` — `staging_products.ingestion_run_id` has an FK to `ingestion_runs`; mirrors `tests/test_staging_step.py:35`.
2. The raw SQL UPDATEs in `_product()` are wrapped in `async with session.begin():` — as written in the brief they ran after the first transaction committed and were rolled back on session close (nothing persisted).
3. `purge_expired` implementation adjusted: it pre-counts history rows bound to expiring products before deleting them. With the Task 5 FK CASCADE, deleting a product silently removes its history; counting only the explicit aged-history DELETE returned 1 where the brief's test expects `history_rows == 2`. Final semantics: `history_rows` = cascade-deleted rows + explicitly aged-deleted rows; `removed_products` = expired removed products.

## RED/GREEN evidence
- RED: `ModuleNotFoundError: No module named 'app.staging.purge'` (test_staging_purge.py collection error); `ImportError: cannot import name 'SYSTEM_PURGE_JOB_ID'` + `AttributeError ... register_system_job` → 2 failed, 12 passed in test_scheduler_service.py.
- GREEN: `TEST_DATABASE_URL=... uv run pytest tests/test_staging_purge.py tests/test_scheduler_service.py tests/test_scheduler_startup.py -v` → **19 passed**.
- Full suite: `TEST_DATABASE_URL=... uv run pytest` → **355 passed** (351 baseline + 4 new), ~89s.

## Self-review
- Completeness: purge deletes BOTH expired removed products (history via cascade, counted) and aged live history; counts returned. ✓
- Quality: repo style (`from __future__ import annotations`, no comments); single transaction; `in_([])` safe on empty result. ✓
- Discipline/YAGNI: nothing beyond brief scope; async wiring variant only. ✓
- Testing: integration tests against PostgreSQL via `isolated_database_url`; pristine output (no stray logs in captured output beyond standard alembic INFO). ✓

## Concerns
- Three deviations documented above; all were forced by inconsistencies between the brief's test expectations, the Task 5 CASCADE FK, and the DB schema. If the spec owner prefers literal-brief behavior (counts excluding cascade-deleted rows), `purge_expired` can be reverted to the brief's exact body, but then the brief's own assertion `history_rows == 2` fails.
