# Task 8 Report: M5 acceptance gate

**Status:** COMPLETE
**Commit:** `6c13f08` — `feat: M5 acceptance gate — staging delta verified`
**Files changed:** `backend/tests/test_m5_acceptance.py` (new, 8 scenarios), `docs/decisions.md` (`### M5 final verification` entry)

## Scenarios implemented (all in `backend/tests/test_m5_acceptance.py`)

Structured after `test_m4_acceptance.py`: same `app_factory` fixture (isolated DB engine/factory, seeded operator user, `create_app(settings=..., db_session_factory=..., fetcher=...)`), API login via httpx ASGITransport, mutable `StubFetcher` serving TSV bytes. All scenarios assert through public surfaces: REST endpoints (`POST /feed-sources/{id}/run`, `GET /feed-sources/{id}/ingestion-runs`) plus DB state via SQLAlchemy/SQL. Only exception allowed by brief: scenario 6 calls `app.staging.purge.purge_expired(factory, now)` directly.

1. `test_first_run_stages_everything` — full runner over 2-product TSV; latest run stats `"staging": {new: 2, ...}`; both rows `status="active"`.
2. `test_identical_second_run_enqueues_nothing` — rerun; latest stats `unchanged: 2, new: 0`; history count still 2.
3. `test_content_change_reprocesses_with_history` — swapped stub data (A2 title); rerun; `changed: 1`; history count 3; raw_data updated.
4. `test_config_change_reprocesses_without_history` — seeded Plugin + ModulePipeline + ModuleInstance (per `test_config_bundle._seed` fields) with `active_pipeline_id` set before first run; sequence: run1 (new:2, history 2) → content change run2 (changed:1, history 3) → mutate `instance.configuration` in DB → run3 shows `changed: 2` while history stays at **3**, matching the brief's numbers exactly.
5. `test_removed_product_flips_status_and_returns` — one-product source → `removed: 1`, row `removed`, `removed_at` set; original source again → `reactivated: 1`, active, `removed_at` None, no extra history.
6. `test_purge_clears_expired_rows_end_to_end` — removal, `removed_at` backdated 91 days via SQL UPDATE, direct `purge_expired(factory, now)` → product + its history gone, A1 intact.
7. `test_invalid_ids_do_not_block_run` — TSV row with empty `sku`; run `success`, `failed_count >= 1`, staging stats `failed >= 1 / new: 1`, only A1 staged.
8. `test_migration_head_matches_models` — isolated DB is a fresh database taken to `alembic upgrade head` by the shared fixture; `inspect()` shows `removed_at` column and CASCADE FK on `staging_history.staging_product_id`.

## RED evidence (one-scenario sanity check)

Temporarily patched `classify()` in `app/staging/delta.py` to force `write_history=False` on content updates → `test_content_change_reprocesses_with_history` FAILED as expected. Reverted via `git checkout`; working tree clean for `app/`.

## Gate results (Step 3, all from worktree)

| Command | Result |
|---|---|
| `uv run python -m compileall -q app` | OK (note: bare `uv run compileall` fails to spawn on this box — used `python -m compileall`, equivalent) |
| `TEST_DATABASE_URL=... uv run pytest` | **363 passed** in 100s |
| `uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check` | OK, artifact unchanged |
| `git diff --check` | clean |
| frontend `npm run test -- --run` / `typecheck` / `build` | 8 tests passed / tsc clean / built in 190ms |

## Deviations

- Dropped absolute `processed_count` assertions: the runner sums `processed_count` across steps (ingest + mapping + staging enqueue), so e.g. first run yields 6, not 2. Staging counts/history/state invariants carry the spec weight instead. Recorded in the decisions entry.
- Brief's Step 3 lists `uv run compileall app`; executed as `python -m compileall app` because uv failed to spawn a `compileall` executable.

## Self-review

- All 8 brief scenarios present, each asserting through public surfaces ✔
- Suite green against real PostgreSQL stack; RED evidence shown and reverted ✔
- Full gate actually run, every command green, results reported honestly ✔
- decisions.md entry follows M1/M2 final-verification template with actual test count (363) ✔
- Commit message matches brief Step 5; only the two intended files committed ✔
- Untracked/modified `.superpowers/sdd/task-*-report.md` files left out of the commit intentionally ✔

## Concerns

- Minor: two runs within the same microsecond would tie on `started_at`; ordering falls back to `id desc` server-side, so "latest run" reads are deterministic.
- Pre-existing LSP/type noise in other test files (e.g., `_env_file` kwarg, StubFetcher protocol casts) is unchanged by this task and does not affect pytest.
