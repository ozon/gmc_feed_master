# Task 2 Report: Manifest parsing + validation

**Status:** Complete
**Commit:** `df52969` — `feat: plugin manifest parsing and validation`

## Files

- Created: `backend/app/plugins/__init__.py` (empty package marker)
- Created: `backend/app/plugins/manifest.py`
- Created: `backend/tests/test_plugins_manifest.py` (39 tests)

## Tests written

Beyond the brief's enumerated minimums, added edge cases:
- Non-string `id`, non-string `name`/`version`
- Scope: bare empty string → `()`; mixed valid/invalid scope list; non-string/non-list scope value (`42`)
- Parametrized over both `config_scope` and `data_scope`
- Immutability of frozen dataclass result
- Distinct-reason assertion: 7 distinct failure cases yield 7 distinct reason strings
- Valid nontrivial schema (object with properties/required) accepted

## RED/GREEN evidence

RED (before implementation):

```
ImportError while importing test module '.../tests/test_plugins_manifest.py'.
E   ModuleNotFoundError: No module named 'app.plugins'
```

GREEN (after implementation):

```
$ TEST_DATABASE_URL=... uv run pytest tests/test_plugins_manifest.py -q
39 passed, 5 warnings in 2.93s
```

Full suite:

```
$ TEST_DATABASE_URL=... uv run pytest -q
405 passed, 21 warnings in 31.07s
```

366 prior + 39 new = 405. ✓

## Self-review

- Interface names/types exactly per brief: `_ID_RE`, `_ALLOWED_SCOPES`, `ManifestError.reason`,
  frozen `PluginManifest` with all 9 fields in order, `parse_manifest(data: Any) -> PluginManifest`. ✓
- Every rule has a distinct reason string; verified by test (`test_distinct_reasons_for_distinct_failures`). ✓
- No extra features beyond the brief (no loading from disk, no version comparison, etc.). ✓
- Empty string as a bare scope normalizes to `()` — interpretation choice; brief says "a bare string → 1-tuple",
  but an empty string cannot be a valid scope element so an empty tuple is the only consistent reading.
  Flagging in case Task 3/4 expect otherwise.

## Concerns

- None blocking. The `"" → ()` scope normalization is the one judgment call (see above).

## Fix Round 1

Reviewer finding: bare empty-string scope normalized to `()` instead of raising. Fixed —
bare strings now normalize to `(value,)` and the existing `_ALLOWED_SCOPES` membership
check rejects `""` (and any undeclared scope) with the same distinct reason.

```
$ uv run pytest tests/test_plugins_manifest.py -q   # with TEST_DATABASE_URL set
39 passed, 5 warnings in 3.28s

$ TEST_DATABASE_URL=... uv run pytest -q
405 passed, 21 warnings in 31.53s
```

Also tightened `test_result_is_immutable` to expect `dataclasses.FrozenInstanceError`.

Commit: `58eb5c4` — `fix: reject empty-string plugin scopes at manifest parse`
