# Task 3 Report: Config bundle resolution from DB

## What Was Implemented

- `backend/app/staging/config_resolver.py` (append-only; Task 2's `_merge_dicts`/`merge_scopes` untouched):
  - `_SCOPE_ORDER`, `_normalize_scopes` (missing → `["global"]`, string → one-element list), `_resolve_declared` (merges only declared scopes in global → client → feed_source order via `_merge_dicts`) — all verbatim from the brief.
  - `async resolve_config_bundle(session, feed_source) -> dict`: returns `{"pipeline": None, "instances": []}` when no active pipeline (or pipeline missing / no instances); otherwise loads the pipeline, its instances ordered by `position`, the referenced plugins (`manifest["id"]` with fallback to `Plugin.name`), and all `PluginConfig`/`PluginData` rows grouped per plugin. Ownership filters applied: `client` rows must match `feed_source.client_id`, `feed_source` rows must match `feed_source.id`; undeclared scopes never contribute. Function-local model imports avoid module-load cycles (per brief).
- `backend/tests/test_config_bundle.py`: 4 integration tests exactly as specified, using the `_make(url)` helper (the unused `_engine` coroutine from the draft was not included). Model import paths verified with grep — all matched the brief.

## Deviation From The Brief's Reference Implementation (important)

The brief's sample implementation is inconsistent with the brief's own tests. With `bucket[row.key] = payload` for both configs and data, `resolved_config` comes out nested (`{"dims": {"min_price": "20"}}`), but three test assertions require flat `{"min_price": "20"}` — while the data assertion requires keyed `{"ids": {"list": ["1"]}}`. No uniform rule satisfies both; the tests define the contract Task 6 hashes. Per TDD (fix code, not tests), I kept every test verbatim and made the minimal implementation change: `scoped_rows(..., keyed_by_row_key=False)` for configs (row payloads merged flat within each scope) and `keyed_by_row_key=True` for data (rows keyed by `row.key`). Everything else matches the brief verbatim.

## TDD Evidence

### RED

Command: `uv run pytest tests/test_config_bundle.py -v`

```
tests/test_config_bundle.py:8: in <module>
    from app.staging.config_resolver import resolve_config_bundle
E   ImportError: cannot import name 'resolve_config_bundle' from 'app.staging.config_resolver'
========================= 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

Expected ImportError confirmed before any implementation existed.

First GREEN run of the brief's verbatim implementation failed 3/4 tests:
```
assert {'dims': {'min_price': '20'}} == {'min_price': '20'}
FAILED tests/test_config_bundle.py::test_bundle_resolves_instances_and_merge
FAILED tests/test_config_bundle.py::test_client_scope_of_other_client_is_ignored
FAILED tests/test_config_bundle.py::test_undeclared_feed_source_scope_never_applies
```
(see deviation above).

### GREEN

Command: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_config_merge.py tests/test_config_bundle.py -v`

```
tests/test_config_merge.py .............. (7 passed)
tests/test_config_bundle.py .... (4 passed)
======================== 11 passed, 5 warnings in 2.69s ========================
```

### Full suite

Command: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q`

```
329 passed, 88 warnings in 77.64s
```

(325 baseline + 4 new.)

## Files Changed

- `backend/app/staging/config_resolver.py` (appended)
- `backend/tests/test_config_bundle.py` (new)

## Commit

- `4f34ea4` feat: resolve output-relevant config bundle per feed source

## Self-Review Findings

- Only the two intended files were staged/committed (`.superpowers/sdd/*` report artifacts left uncommitted).
- Existing `merge_scopes`/`_merge_dicts` untouched; file appends cleanly with `from __future__ import annotations` style preserved.
- Test helper uses `_make`; no dead `_engine` coroutine.
- Full suite green before commit.

## Concerns

1. **Brief inconsistency resolved toward the tests** (detailed above). If the intended contract was actually fully key-nested (`{"dims": ...}` for config too), the three config assertions in the brief's tests would need changing instead — flagging for the orchestrator/reviewer since Task 6 hashes this exact shape. Current shape: flat merged settings for `resolved_config`, `{key: payload}` datasets for `resolved_data`.
2. Pre-existing warnings only (Starlette/httpx deprecation, Alembic `path_separator`); none introduced by this change.

## Fix Round 1

Orchestrator decision on the flagged contract question: BOTH `resolved_config` and `resolved_data` use flat merge (spec §8: one full-replace payload per plugin/scope validated against a single manifest schema — never `{row.key: payload}` nests).

Changes (commit `9f001df` "fix: resolve config and data payloads flat across scopes"):
- `backend/app/staging/config_resolver.py`: removed the `keyed_by_row_key` parameter; `scoped_rows` now always merges row payloads flat (`bucket.update(getattr(row, attribute))`). Call sites back to the brief's original two-argument form.
- `backend/tests/test_config_bundle.py`: data assertion in `test_bundle_resolves_instances_and_merge` updated from `{"ids": {"list": ["1"]}}` to `{"list": ["1"]}`.

Covering tests:
```
$ TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_config_merge.py tests/test_config_bundle.py -v
...
tests/test_config_bundle.py::test_bundle_resolves_instances_and_merge PASSED
tests/test_config_bundle.py::test_bundle_without_active_pipeline_is_stable PASSED
tests/test_config_bundle.py::test_client_scope_of_other_client_is_ignored PASSED
tests/test_config_bundle.py::test_undeclared_feed_source_scope_never_applies PASSED
======================== 11 passed, 5 warnings in 2.67s ========================
```

Full suite:
```
$ TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q
329 passed, 88 warnings in 82.57s (0:01:22)
```
