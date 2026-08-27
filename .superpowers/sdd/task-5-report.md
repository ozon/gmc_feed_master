# Task 5 Report: Migration + runtime contract execution

## Status: COMPLETE

## Commits
1. `83dbda6` — `feat: processed-output store migration` (migration `20260827_0001`, model columns, migration test)
2. `9bb3096` — `feat: PluginStep executes registered pipeline plugins` (runtime.py, apply_plugin_outcomes, PluginStep, RunState/StagingStep stash, default_steps + main.py wiring, step tests, contract-test updates)

## Tests
- Full suite serial `-n0`: **447 passed** (437 baseline + 10 new)
- Full suite parallel (default addopts `-n auto`): **447 passed**
- New suites: `test_m6_migration.py` (2 tests, RED→GREEN), `test_plugin_step.py` (8 tests)
- `alembic heads` shows a single head: `20260827_0001`

## Implementation notes
- Migration `down_revision = '20260826_0002'` per the orchestrator correction (brief said `20260826_0001`; Task 4 added an intermediate revision).
- `apply_plugin_outcomes` mirrors the chunked sibling pattern; one transaction per chunk; `now` computed once per call. Processed → `processed_data=final, excluded=False, last_seen_at=now`; dropped → `processed_data=NULL, excluded=True`.
- `StagingStep` now stashes `client_id`, `config_bundle`, and the `product_pks` map on `RunState`.

## Deviations from brief / judgment calls (flag for review)
1. **original_product deepcopy timing**: the brief's literal code does `deepcopy(product)` fresh inside each instance loop. Because plugins receive `current` (aliased to the run_state product), a mutating first plugin would leak mutations into the second instance's `original_product`. The locked semantic says original is "a deep copy of THIS run's incoming mapped product taken before first instance" and the brief's own test note asserts it unchanged in instance 2 after mutation in instance 1 — so I hoist one `deepcopy(product)` before the instance loop and reuse it for all instances of that product.
2. **Empty-registry outcome writes**: with zero configured instances, every product is a survivor, so the brief's code still writes `processed_data = raw_data` outcomes for staged pks (and counts them in `plugins.processed`). This follows the brief's code literally; products flow through unchanged (`capture.captured` assertions intact).
3. **M3 acceptance counters updated**: because PluginStep now returns `processed_count=len(survivors)` and PipelineRunner sums steps, two M3 assertions changed: happy path 9→12 (3×4 steps), row-error path 3→4. Product-content assertions (`capture.captured == [...]`) are untouched and pass. Without this update they cannot be green given the mandated StepResult shape; flagged in case the milestone owner prefers PluginStep contribute 0 to run totals when idle.
4. **No-op contract test**: removed `PluginStep` from `test_no_op_steps_contract` parametrization in `test_pipeline_steps.py` (it is no longer a no-op; covered by `test_plugin_step.py`).

## Self-review checklist
- down_revision correct / single head: YES
- Exception path writes nothing to staging: YES (errored products excluded from outcomes; test asserts raw_data/processed_data/excluded preserved)
- deepcopy semantics match locked design: YES (per deviation #1)
- Statistics shape `{plugins: {processed, dropped, errored}}`: YES (tested)
- Pass-through with empty registry: YES (products unchanged through run_state)

## Concerns
- Deviations #1–#3 above; #3 changes two M3 acceptance numbers — needs milestone-owner sign-off if exact legacy totals matter downstream (e.g., dashboards).
- Pre-existing LSP/pyright noise in test files (StubFetcher vs HttpFetcher typing) unrelated to this task.

## Report path
/home/ozon/gmc_feed_master/.worktrees/m6-plugin-host/.superpowers/sdd/task-5-report.md
