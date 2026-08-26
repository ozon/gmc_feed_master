# M5 Final Review Fixes — Report

Branch: `m5-staging-delta` (worktree `.worktrees/m5-staging-delta`)
Baseline suite: 363 passed → Final: **365 passed** (+2 new tests), `compileall app` OK.

## Finding 1 — N+1 pk lookups in `apply_staging_delta` updates path
- `backend/app/staging/delta.py`: added `pk: int | None = None` as the last field of
  `RowUpsert`; both update-path branches in `classify()` (active-changed and
  removed-reappears) now pass `pk=row.pk`.
- `backend/app/staging/persistence.py`: dropped the per-row SELECT after each UPDATE in
  the updates loop; `pk_map[u.product_id] = u.pk` when `u.pk is not None`.
  Inserts/reactivations/history paths unchanged.
- Tests:
  - `backend/tests/test_staging_delta.py`: `test_config_only_change_enqueues_without_history`
    now asserts `delta.upserts[0].pk == 7`.
  - `backend/tests/test_staging_step.py`: new integration test
    `test_apply_staging_delta_maps_updates_in_pk_map` — stages a product, builds an
    update-path delta with classifier-shaped `RowUpsert(pk=...)`, calls
    `apply_staging_delta` directly, asserts `pk_map == {"1": pk}` and that `raw_data`
    was updated. First run failed (`KeyError`) because the constructed `RowUpsert`
    omitted `pk`; fixed by passing `pk=pk` to mirror real classifier output.

## Finding 2 — missing positive feed_source-scope test
- `backend/tests/test_config_bundle.py`: new `test_declared_feed_source_scope_wins` —
  seeds manifest `"config_scope": ["global", "client", "feed_source"]` with colliding
  `dims` PluginConfig rows at global ("10"), client ("20"), feed_source ("30"); asserts
  `resolved_config == {"min_price": "30"}`. Built locally in the test (no `_seed` change).

## Findings 3+4 — minor one-liners
- `backend/tests/test_staging_purge.py`: empty-tables assertion replaced with explicit
  `counts.removed_products == 0` / `counts.history_rows == 0`.
- `backend/tests/test_m5_acceptance.py`: deleted dead `SCENARIOS` list constant.

## Commands run
1. Focused: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q tests/test_staging_delta.py tests/test_config_bundle.py tests/test_staging_step.py tests/test_staging_purge.py tests/test_m5_acceptance.py`
   → `35 passed, 25 warnings` (after fixing the new test).
2. Full gate: same env, `uv run pytest -q` → `365 passed, 113 warnings in 100.88s`.
3. `uv run python -m compileall -q app` → exit 0 (COMPILE_OK).
   Note: harmless warning about mismatched VIRTUAL_ENV from parent shell; ignored.

## Commits
- `306a54c` perf: derive update-path staging pks from stored rows
- `8addee6` test: positive feed_source scope resolution coverage
- `6b8bced` chore: tidy purge assertion and drop dead SCENARIOS constant

## Files changed
- backend/app/staging/delta.py
- backend/app/staging/persistence.py
- backend/tests/test_staging_delta.py
- backend/tests/test_staging_step.py
- backend/tests/test_config_bundle.py
- backend/tests/test_staging_purge.py
- backend/tests/test_m5_acceptance.py

## Concerns
- Update-path upserts must now carry `pk` (classifier guarantees it). A hand-built
  update `RowUpsert` without `pk` would be skipped from `pk_map` and its history row
  would raise KeyError — acceptable contract given `classify()` is the sole producer,
  but worth noting for future callers.
