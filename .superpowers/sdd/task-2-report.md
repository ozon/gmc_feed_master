# Task 2 Report: Three-tier scope merge (pure function)

## What Was Implemented

- `backend/app/staging/config_resolver.py` — pure function `merge_scopes(global_payload, client_payload, feed_source_payload) -> dict` implementing spec §5.3: per key, dicts merge recursively (`_merge_dicts` helper), everything else replaces wholesale; client overrides global, feed source overrides both; `None` payloads skipped. Code matches the brief verbatim.
- `backend/tests/test_config_merge.py` — 7 tests covering: global-only, per-key client override, feed-source precedence, wholesale replacement of non-dict values, recursive dict merge, fall-through for keys missing at specific scopes, and type-flip replacement.

## TDD Evidence

### RED

Command:
```
uv run pytest tests/test_config_merge.py -v
```
Output (key line):
```
ImportError while importing test module '.../backend/tests/test_config_merge.py'.
E   ModuleNotFoundError: No module named 'app.staging.config_resolver'
```
Expected because the test module imports `merge_scopes` from `app.staging.config_resolver`, which did not exist yet.

### GREEN

Command:
```
uv run pytest tests/test_config_merge.py -v
```
Output:
```
tests/test_config_merge.py::TestMergeScopes::test_global_only PASSED     [ 14%]
tests/test_config_merge.py::TestMergeScopes::test_client_overrides_global_per_key PASSED [ 28%]
tests/test_config_merge.py::TestMergeScopes::test_feed_source_wins PASSED [ 42%]
tests/test_config_merge.py::TestMergeScopes::test_non_dict_values_replace_wholesale PASSED [ 57%]
tests/test_config_merge.py::TestMergeScopes::test_dict_values_merge_recursively PASSED [ 71%]
tests/test_config_merge.py::TestMergeScopes::test_missing_at_specific_scope_falls_through PASSED [ 85%]
tests/test_config_merge.py::TestMergeScopes::test_type_flip_replaces PASSED [100%]
========================= 7 passed, 1 warning in 0.02s =========================
```

## Full Suite Verification

Command:
```
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q
```
Output:
```
325 passed, 84 warnings in 76.13s (0:01:16)
```
Matches expectation: 309 baseline + 9 (Task 1) + 7 new = 325, all passing.

## Files Changed

- Created: `backend/app/staging/config_resolver.py`
- Created: `backend/tests/test_config_merge.py`

## Commit

- `56d6413` feat: three-tier scope merge per spec 5.3

## Self-Review Findings

- Implementation is exactly the brief's code — no extra features (YAGNI respected), minimal comments, `from __future__ import annotations` present.
- Only the two task files staged/committed; an unrelated modified `.superpowers/sdd/task-1-report.md` was left untouched in the working tree.
- Test output pristine apart from a pre-existing starlette/httpx deprecation warning present across the whole suite.
- Function name/signature preserved verbatim for Task 3 consumption.

## Concerns

None.
