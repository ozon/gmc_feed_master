# Task 1 Report: Canonical hashing module

## What was implemented

Created the pure hashing foundation for the M5 staging milestone, exactly per the brief:

- `backend/app/staging/__init__.py` — empty package marker.
- `backend/app/staging/hashing.py`:
  - `strip_derived(value)` — recursively removes dict keys starting with `_`, recursing into nested dicts and lists; scalars returned untouched.
  - `canonical_json(value)` — compact JSON (`(",", ":")`), recursively sorted keys via `sort_keys=True`, `ensure_ascii=False` for unicode preservation, applied to `strip_derived` output.
  - `content_hash(value)` — SHA-256 hexdigest of the canonical JSON encoded as UTF-8.

No extra features beyond the brief (YAGNI respected). Implementation matches the brief's code verbatim.

## TDD Evidence

### RED

Command:

```
cd backend && uv run pytest tests/test_staging_hashing.py -v
```

Output (relevant):

```
tests/test_staging_hashing.py:1: in <module>
    from app.staging.hashing import canonical_json, content_hash, strip_derived
E   ModuleNotFoundError: No module named 'app.staging'
========================= 1 error during collection =========================
```

Expected failure: the test module imports `app.staging.hashing`, which did not exist yet. This confirms the tests exercise new code (not existing behavior).

### GREEN

Command:

```
cd backend && uv run pytest tests/test_staging_hashing.py -v
```

Output (relevant):

```
collected 9 items
tests/test_staging_hashing.py::TestStripDerived::test_removes_top_level_underscore_keys PASSED
tests/test_staging_hashing.py::TestStripDerived::test_removes_nested_and_inside_lists PASSED
tests/test_staging_hashing.py::TestStripDerived::test_leaves_scalars_untouched PASSED
tests/test_staging_hashing.py::TestCanonicalJson::test_key_order_independent PASSED
tests/test_staging_hashing.py::TestCanonicalJson::test_nested_keys_sorted PASSED
tests/test_staging_hashing.py::TestCanonicalJson::test_unicode_preserved_and_compact PASSED
tests/test_staging_hashing.py::TestContentHash::test_is_sha256_hexdigest PASSED
tests/test_staging_hashing.py::TestContentHash::test_sidecars_do_not_change_hash PASSED
tests/test_staging_hashing.py::TestContentHash::test_content_change_changes_hash PASSED
========================= 9 passed in 0.02s =========================
```

All 9 tests pass.

## Full suite

Command: `cd backend && uv run pytest -q`

Result with my changes: **241 passed, 77 errors** (318 collected).
Baseline without my changes (verified via `git stash -u`): **232 passed, 77 errors** (309 collected).

- The 9 new tests all pass and no existing tests regressed (232 → 241 passed).
- The 77 errors are **pre-existing and environmental**: they come from `backend/tests/conftest.py:61` failing setup with `Failed: TEST_DATABASE_URL must point to PostgreSQL via asyncpg`. They occur identically on the clean baseline (verified before committing) and are unrelated to this task. Note: the task prompt said "expect 309 baseline + your new tests passing" — the actual local baseline is 232 passing + 77 DB-dependent collection/setup errors = 309 collected total, which matches that expectation once the DB-less environment is accounted for.

## Files changed

- Created `backend/app/staging/__init__.py`
- Created `backend/app/staging/hashing.py`
- Created `backend/tests/test_staging_hashing.py`

## Commit

- `aae1221` feat: canonical product hashing with derived-key stripping

## Self-review findings

- Completeness: all three functions implemented per brief interfaces; all 9 brief tests present verbatim and passing. Edge cases covered: nested stripping, stripping inside lists, scalar passthrough, key-order independence at top and nested level, unicode/compactness, hash format, sidecar insensitivity, content sensitivity.
- Quality: matches the style of existing modules (e.g., `app/ingest/flat_notation.py`); stdlib only as specified.
- Discipline: nothing added beyond the brief.
- Testing: TDD followed strictly — tests written first, watched fail for the right reason (missing module), then implementation, then watched pass. Output pristine apart from a pre-existing `StarletteDeprecationWarning` from `fastapi/testclient` present across the whole suite (not introduced by this change).

## Issues / concerns

- None blocking. Only note: the 77 pre-existing `TEST_DATABASE_URL` errors described above exist in this worktree environment regardless of this task's changes.
