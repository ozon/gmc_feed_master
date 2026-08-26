# Task 3 Report: Cap test-engine pools

## Status: COMPLETE

**Commit:** `4404c0b` — `perf: cap test-engine pools (pool_size=2, max_overflow=0)`

## Scope correction

Brief said "21 files / 57 call sites". Actual repo state: 57 was the count of ALL
`create_async_engine` matches including import lines (21 imports + 36 call sites).
Call sites: **36**, across **20 files** under `backend/tests/` (conftest.py only
imports; it has no call site). All 36 were single-line calls of exact form
`create_async_engine(<identifier>)` with no pre-existing kwargs — verified before
editing:

```
grep -rn "create_async_engine(" backend/tests --include="*.py" \
  | grep -vE "create_async_engine\([a-z_]+\)$"
# (no output)
```

## Files touched (20)

test_m5_migration.py, test_runs_api.py, test_migrations.py, test_m4_acceptance.py,
test_m2_migration.py, test_postgres_sessions.py, test_m3_acceptance.py,
test_user_persistence.py, test_clients_api.py, test_staging_purge.py,
test_m5_acceptance.py, test_field_mapping_api.py, test_postgres_auth.py,
test_staging_step.py, test_config_bundle.py, test_registry_api.py,
test_pipeline_runner.py, test_m2_acceptance.py, test_m1_acceptance.py,
test_scheduler_startup.py

Per-file site counts match diff line counts (e.g. test_staging_step.py: 9 sites,
test_migrations.py: 3, others 1–2).

## Verification

1. Completeness grep:
   ```
   $ grep -rn "create_async_engine(" backend/tests | grep -v "pool_size=2" || echo CLEAN
   CLEAN
   ```
2. Diff purity — every +/- line in the commit touches a `create_async_engine(...)` line:
   ```
   $ git diff backend/tests | grep "^[+-]" | grep -vE "^[+-][+-]|create_async_engine"
   # (no output)
   ```
3. Full suite serial:
   ```
   $ TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \
     uv run pytest -q -n0
   366 passed, 11 warnings in 51.91s
   ```

## Self-review

- No `backend/app/` changes: commit contains exactly 20 paths, all `backend/tests/*`. ✅
- No reformatting noise: 36 insertions / 36 deletions, one line swapped per site. ✅
- Every site capped exactly once: 36 call-site lines changed; completeness grep CLEAN;
  kwargs appear exactly once per call. ✅
- Pre-existing uncommitted `.superpowers/sdd/` edits from earlier tasks were left out
  of this commit (brief stages `backend/tests` only). ✅

## Concerns

None blocking. Note for the plan owner: brief's "21 files / 57 call sites" figure
overcounted (imports included); actuals are 20 files / 36 call sites.
