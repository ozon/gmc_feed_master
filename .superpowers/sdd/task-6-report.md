# Task 6 Report: StagingStep + runner wiring

**Status:** COMPLETE
**Commit:** `870a2dc` — "feat: StagingStep persists staged state and reduces run to delta set"
**Branch:** `m5-staging-delta`

## Implementation

- **Created `backend/app/staging/persistence.py`** exactly per brief:
  - `load_stored_rows(session_factory, feed_source_id) -> dict[str, StoredRow]`
  - `apply_staging_delta(session_factory, feed_source_id, ingestion_run_id, delta, config_hash, *, chunk_size=1000) -> dict[str, int]` returning product_id -> pk for all enqueued products. Each chunk wrapped in its own transaction.
- **Modified `backend/app/pipeline/steps.py`:**
  - `StepContext` gains `ingestion_run_id: int = 0` (existing constructions unaffected).
  - Added `StagingStep(chunk_size=1000)` with `name="staging"` after `MappingStep`; loads feed source, resolves config bundle via `resolve_config_bundle`, hashes it with `content_hash`, classifies via `classify`, persists via `apply_staging_delta`, replaces `ctx.run_state.products` with `delta.enqueue`, returns `processed_count=len(enqueue)`, `failed_count=counts.failed`, `statistics={"staging": asdict(counts)}`.
  - `default_steps()` now: Ingest, Mapping, **Staging**, Plugin, QualityCheck, Export.
- **Modified `backend/app/pipeline/runner.py`:** passes `ingestion_run_id=run_id` into `StepContext`.
- **Modified `backend/app/pipeline/__init__.py`:** exports `StagingStep`.

## Persistence-action verification (spec §4 table)

| Action | Verified |
|---|---|
| inserts | INSERT with all fields incl. `status="active"`, `removed_at=None`, flush per chunk for pks ✓ |
| updates (insert=False) | UPDATE by `(feed_source_id, product_id)`; raw_data, both hashes, active, `removed_at=None`, run id, last_seen ✓ |
| reactivations | UPDATE pk: active, `removed_at=None`, last_seen, run id ✓ |
| removals | UPDATE pk: removed, `removed_at=now`, run id ✓ |
| touches | UPDATE `last_seen_at=now` ONLY ✓ |
| history | INSERT `StagingHistory` only for upserts with `write_history=True` ✓ |

## TDD Evidence

- **RED:** `ImportError: cannot import name 'StagingStep' from 'app.pipeline.steps'` (7 test collection errors) — captured before implementation.
- **GREEN:** `tests/test_staging_step.py` → 7 passed.
- **Affected suites:** staging + mapping + ingest + pipeline_steps + pipeline_runner → 49 passed.

## Full suite

`TEST_DATABASE_URL=... uv run pytest -q` → **350 passed** (343 baseline + 7 new), ~90s, pristine output (only pre-existing deprecation warnings).

## Files changed

- `backend/app/staging/persistence.py` (new)
- `backend/tests/test_staging_step.py` (new)
- `backend/app/pipeline/steps.py`
- `backend/app/pipeline/runner.py`
- `backend/app/pipeline/__init__.py`
- `backend/tests/test_pipeline_steps.py` (sanctioned)
- `backend/tests/test_m3_acceptance.py` (see deviations)
- `backend/tests/test_m4_acceptance.py` (see deviations)

## Deviations from brief (all documented in commit message)

1. **Test seeding of `IngestionRun` rows 1–3** (`test_staging_step.py::_seed`): the brief's tests use `run_id=1..3`, but `staging_products.ingestion_run_id` has a real FK to `ingestion_runs.id`; without seeded runs every test fails with `ForeignKeyViolationError`. Production code always passes a real run id from the runner, so only the fixture needed fixing. All other brief test code is verbatim except item 2.
2. **Test logger uses `logging.getLogger(__name__)` instead of `"test"`**: root-caused cross-test interference — `alembic/env.py` calls `fileConfig()` (disable_existing_loggers=True) on every `isolated_database_url` setup; once my tests create the shared `"test"` logger, the next alembic run disables it and `test_ingest_step::test_row_errors_logged_as_warning` fails when run after my tests. Module-scoped logger removes the interference; nothing asserts on my tests' log output. (Latent repo-wide landmine in alembic/env.py — flagged as concern.)
3. **Sanctioned (brief Step 5):** `test_pipeline_steps.py` exact-composition assertions updated to 6 steps / names include "staging".
4. **Acceptance expectations (not explicitly sanctioned, required for milestone semantics):**
   - `test_m3_acceptance`: `run.processed_count` totals 6→9 and 2→3 — runner sums per-step counts; StagingStep legitimately adds its enqueue counts.
   - `test_m4_acceptance`: identical rerun now captures `[]` instead of both products — this is precisely M5's delta behavior (unchanged products don't reach plugins). Removed the now-vacuous `margin` loop over the empty capture list.

## Self-review

- Persistence-action table re-checked line by line against spec §4 — no findings.
- No debug artifacts; minimal comments; `from __future__ import annotations` style followed.
- No lint/typecheck commands configured in pyproject (checked); pytest is the arbiter. LSP "errors" in test files are pre-existing strictness about stub fetchers/lambdas, not introduced here.

## Concerns

- `alembic/env.py`'s unconditional `fileConfig()` disables any pre-existing non-alembic loggers on each test DB creation — a latent trap for any future test that creates a logger and later relies on caplog. Suggest `fileConfig(config.config_file_name, disable_existing_loggers=False)` in a future task (out of scope here).

## Fix Round 1

**Reviewer finding:** `apply_staging_delta` pk_map missing entries for flip-only reactivations (they are enqueued but never mapped).

**Fix:** `backend/app/staging/persistence.py` — inside the reactivations chunk loop (same transaction), batch-resolve `(id, product_id)` for the chunk via `select(...).where(StagingProduct.id.in_(group))` and add `pk_map[product_id] = pk`.

**New test:** `test_apply_staging_delta_maps_reactivations_in_pk_map` — stages a product, removes it (empty second run), then calls `apply_staging_delta` directly with `StagingDelta(reactivations=[pk])`; asserts returned map == `{product_id: pk}`.

Commands and output:

```
$ TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_staging_step.py -v
...
tests/test_staging_step.py::test_apply_staging_delta_maps_reactivations_in_pk_map PASSED
======================== 8 passed, 9 warnings in 5.75s =========================

$ TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q
351 passed, 101 warnings in 89.81s
```

**Commit:** `517d1b9` — "fix: include reactivated products in staging pk_map"
