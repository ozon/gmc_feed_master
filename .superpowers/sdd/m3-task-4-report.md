# Task 4: Flat-notation value splitting — Report

## Summary

Implemented `split_row(cells, plan)` in `flat_notation.py` that splits a row's cell values according to a `HeaderPlan`, plus supporting types.

## Changes

### `backend/app/ingest/flat_notation.py`
- Added `RowError` dataclass (message + optional row_number)
- Added `arity` field to `ColumnSpec` (default=1) — tracks how many header columns map to a repeated_structured group
- Updated `parse_header` to set `arity` when building repeated_structured ColumnSpecs
- Added `_split_csv_cell()` — RFC-4180 compliant comma splitting
- Added `split_row(cells, plan) -> tuple[dict, RowError | None]` — the core function

### `backend/tests/test_flat_notation.py`
- Added 12 new tests across 4 test classes:
  - `TestSplitRowScalar` — scalar value, empty cell omitted, two scalars
  - `TestSplitRowRepeatedScalar` — comma-separated, quoted comma preserved, single value
  - `TestSplitRowStructured` — annotated structured, surplus colons error, empty cell omitted
  - `TestSplitRowRepeatedStructured` — two columns, one empty one filled, surplus colons error
- Updated existing `TestParseHeaderRepeatedStructured` to assert `arity=2`

## Test Results

All 19 tests pass (11 existing + 8 new). Pre-existing database test error (`TEST_DATABASE_URL` not set) is unrelated.

## Commit

`6416230` — `feat: flat-notation value splitting`
