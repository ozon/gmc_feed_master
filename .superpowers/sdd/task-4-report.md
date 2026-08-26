# Task 4 Report: Delta classifier (pure)

## Status: DONE

## Implementation

Created `backend/app/staging/delta.py` per the brief:
- Dataclasses: `StoredRow`, `RowUpsert`, `StagingCounts` (all frozen in brief — see deviation below), `StagingDelta`
- `classify(products, stored, config_hash) -> StagingDelta` implementing the binding matrix:
  - invalid product (non-dict / missing / empty / non-str id) → `counts.failed += 1`, skip
  - duplicate id within run → first wins, later ones counted as failed
  - no stored row → insert upsert with history, enqueue, `new`
  - active row, either hash differs → update upsert, `write_history=(content differs)`, enqueue, `changed`
  - active row, both equal → touch pk, `unchanged`
  - removed row reappears with any hash differing → update upsert (`insert=False`; persistence flips status to active), `write_history=(content differs)`, enqueue, `reactivated`
  - removed row reappears with equal hashes → `reactivations.append(pk)`, enqueue, `reactivated`
  - active stored row absent → `removals.append(pk)`, `removed`
  - removed stored row absent → no-op

## Deviation from brief's verbatim code

The brief's verbatim implementation marks `StagingCounts` as `@dataclass(frozen=True)` while `classify` mutates it (`delta.counts.failed += 1` etc.). That raises `dataclasses.FrozenInstanceError` at runtime and fails 9 of the brief's own tests. Fix applied: removed `frozen=True` from `StagingCounts`. All field names, defaults, and ordering are unchanged, so Task 6's consumption surface is identical. No other deviations; tests are byte-for-byte from the brief.

## TDD Evidence

**RED** (before implementation existed):
```
ERROR tests/test_staging_delta.py
E   ModuleNotFoundError: No module named 'app.staging.delta'
========================= 1 error during collection !!!!!!!!!!!!!!!!!!
```

**Intermediate failure with verbatim brief code** (frozen StagingCounts):
```
E   dataclasses.FrozenInstanceError: cannot assign to field 'new'
9 failed, 2 passed
```

**GREEN** after removing `frozen=True` from `StagingCounts`:
```
11 passed, 1 warning in 0.03s
```
All 11 tests: test_first_run_inserts_everything, test_identical_rerun_only_touches,
test_content_change_enqueues_with_history, test_config_only_change_enqueues_without_history,
test_removal_when_active_row_absent, test_removed_row_absent_again_is_noop,
test_reactivation_with_equal_hashes_flips_only,
test_reactivation_with_changed_content_upserts_with_history,
test_missing_or_invalid_ids_fail, test_duplicate_ids_first_wins_rest_fail,
test_counts_default_zero.

## Full suite

```
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q
340 passed, 88 warnings in 79.50s
```
329 baseline + 11 new = 340. Matches expectation exactly.

## Files changed

- Created: `backend/app/staging/delta.py`
- Created: `backend/tests/test_staging_delta.py`

## Commit

- `d968630` feat: staging delta classifier

## Self-review

- Completeness: all 8 matrix rows implemented and covered by tests ✓
- Interfaces: dataclass fields/signature match the brief exactly (Task 6 contract intact) ✓
- Discipline: no extra features (YAGNI), no comments, `from __future__ import annotations` ✓
- Testing: 11/11 new pass; full suite green ✓

## Concerns

- The single deviation above (unfrozen `StagingCounts`) is required for the brief's own tests to pass. If Task 6 or reviewers require frozen counts, the alternative is replacing `delta.counts` wholesale via a mutable builder — but the current form is minimal and matches Task 6's read-only usage.
