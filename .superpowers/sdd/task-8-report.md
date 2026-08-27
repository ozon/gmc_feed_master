# Task 8: M6 acceptance gate — Report

## Status: Complete

## Commit
`7f95abe feat: M6 acceptance gate — plugin host verified`

## Test Summary
6 acceptance scenarios, all GREEN:

1. **test_dummy_plugin_passes_contract_without_core_changes** — fixture plugin registered in DB with `enabled=False`, no contract violations
2. **test_discovery_is_idempotent_across_restarts** — single row after two discovery runs, version bumped to 1.1.0, `enabled=True` preserved
3. **test_end_to_end_execution_through_runner** — product A transformed (title uppercased + suffix), product B dropped (`excluded=True`), stats `processed==1, dropped==1`
4. **test_error_isolation_preserves_last_known_good** — plugin error on specific product leaves staging row untouched, run status success
4b. **test_drop_then_pass_reactivation** — product drops in run 1 (`excluded=True`), passes in run 2 (`excluded=False` with `processed_data`)
5. **test_toggle_and_config_round_trip_via_api** — GET/PUT enabled, PUT/GET config, undeclared scope → 422
6. **test_full_suite_serial_and_parallel_green** — meta-gate: serial, parallel, compileall, git diff --check

479 total tests in the suite.

## Concerns
None. All scenarios pass cleanly. The drop→pass reactivation test (scenario 4b) was added per Task 5 reviewer feedback.

## Files Modified
- `backend/tests/test_m6_acceptance.py` (created, 627 lines)
- `docs/decisions.md` (M6 final verification entry added)

## Report Path
`/home/ozon/gmc_feed_master/.worktrees/m6-plugin-host/.superpowers/sdd/task-8-report.md`
