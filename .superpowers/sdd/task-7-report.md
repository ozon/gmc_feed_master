## Task 7: Contract checker + example fixture — COMPLETE

**Status:** Done
**Commit:** `89ccb68 feat: plugin contract checker and example fixture`

### Files Created
- `backend/app/plugins/contract.py` — `contract_violations(candidate) -> list[str]`
- `backend/tests/fixtures/example_plugin/plugin.json` — manifest with required config_schema
- `backend/tests/fixtures/example_plugin/plugin.py` — UpperPlugin (validate_config + process)
- `backend/tests/test_plugin_contract.py` — 9 tests (1 positive, 5 negative classes)

### Files Modified
- `backend/app/plugins/manifest.py` — allow empty scope lists (data_scope: [] edge case)
- `backend/tests/test_plugins_manifest.py` — updated 3 tests for empty-scope behavior

### Test Summary
- 472 passed (463 baseline + 9 new contract tests)
- 0 failed, 0 errors

### Implementation Details
- `contract_violations` is synchronous (not async)
- 5 checks: meta-schema, process return type, original_product mutation, validate_config rejection, reserved routes
- Config gating: if `validate_config({})` raises, checks 2-4 are skipped (config-gated)
- Reserved route check catches `PluginLoadError` from `collect_router` and converts to violation string

### Concerns
- Empty scope lists now accepted by `parse_manifest` (was previously rejected). This is required for the `data_scope: []` edge case but changes existing behavior. Tests updated accordingly.

## Fix Round 1
Reverted empty scope list acceptance: restored `_parse_scope` guard that rejects `[]`, updated fixture to `"data_scope": ["global"]`, re-added 7th distinct-failure test case. 472 passed.
