# Task 8 Report

## Status

DONE

## What I implemented

- `backend/app/ingest/__init__.py` — `read_feed(data, source_format, registry)`
  dispatch: `tsv`/`csv`/`wide_tsv` → `parse_delimited`, `xml` → `parse_xml`,
  else `ValueError(f"unsupported source format: {source_format!r}")`.
  Re-exports `HttpFetcher`, `FetchError`, `IngestReport`, `RowError`,
  `XmlParseError`.
- `backend/app/pipeline/steps.py` — real `IngestStep(fetcher, registry)`:
  loads `FeedSource` via `ctx.session_factory` (missing → `RuntimeError`),
  missing/empty `source_url` → `RuntimeError`, `configuration["basic_auth"]`
  dict → `(username, password)` tuple, fetch → `read_feed` → extend
  `ctx.run_state.products`, returns `StepResult(processed_count,
  failed_count, statistics={"row_errors": first 100 as dicts})`. Fetch/parse
  exceptions propagate.
- `DEFAULT_STEPS` constant replaced by `default_steps(fetcher, registry)`
  factory returning `(IngestStep(fetcher, registry), PluginStep(),
  QualityCheckStep(), ExportStep())`; `pipeline/__init__.py` exports updated.
- `backend/app/main.py` — `create_app` gains an optional `fetcher` injection
  parameter (defaults to `HttpFetcher()`); loads registry via
  `load_registry()` and wires `default_steps(...)` into `PipelineRunner`.
- `backend/tests/test_ingest_step.py` — 10 unit tests (no PostgreSQL):
  happy TSV path, missing source_url, missing feed source, fetch error,
  basic-auth tuple passthrough, row-error counting + first-100 statistics
  truncation, XML path, unsupported format, empty registry.
- Fixed existing tests referencing `DEFAULT_STEPS`/zero-arg `IngestStep()`:
  `test_pipeline_steps.py` (no-op contract test now parametrized over the
  three remaining no-op steps; `default_steps` shape test),
  `test_pipeline_runner.py` (stub fetcher + `RegistryDocument(attributes={})`,
  feed source gains `source_url`).
- Fixed M2-era regressions surfaced by the real IngestStep:
  `test_m2_acceptance.py` and `test_runs_api.py` now inject a `StubFetcher`
  via the new `create_app(fetcher=...)` seam and seed `source_url` on feed
  sources (runs without a URL now correctly fail).
- `.superpowers/sdd/task-7-report.md` — restored the correct M3 Task 7
  (HttpFetcher) report; the committed file was the stale M1-era report.

## TDD evidence

RED (implementation stashed, tests present):

```
$ git stash push backend/app/ingest/__init__.py backend/app/pipeline/steps.py \
    backend/app/pipeline/__init__.py backend/app/main.py
$ uv run pytest tests/test_ingest_step.py -x -q
E   ImportError: cannot import name 'FetchError' from 'app.ingest'
ERROR tests/test_ingest_step.py
1 warning, 1 error in 0.14s
```

GREEN (implementation restored):

```
$ TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \
    uv run pytest tests/test_ingest_step.py tests/test_pipeline_steps.py \
    tests/test_pipeline_runner.py -x -q
33 passed, 9 warnings in 5.32s
```

## Test results

Focused (exact command from brief):

```
$ TEST_DATABASE_URL=... uv run pytest tests/test_ingest_step.py \
    tests/test_pipeline_steps.py tests/test_pipeline_runner.py -x -q
33 passed, 9 warnings in 5.32s
```

Full suite (PostgreSQL via local docker container on :5432):

```
$ TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \
    uv run pytest tests/ -q
210 passed, 63 warnings in 55.14s
```

Compile check: `uv run python -m compileall app registry -q` → clean.
`git diff --check` → clean.

## Files changed

- `backend/app/ingest/__init__.py`
- `backend/app/pipeline/steps.py`
- `backend/app/pipeline/__init__.py`
- `backend/app/main.py`
- `backend/tests/test_ingest_step.py` (new)
- `backend/tests/test_pipeline_steps.py`
- `backend/tests/test_pipeline_runner.py`
- `backend/tests/test_m2_acceptance.py`
- `backend/tests/test_runs_api.py`
- `.superpowers/sdd/task-7-report.md` (doc fix, separate commit)
- `.superpowers/sdd/task-8-report.md` (this report)

## Self-review findings

- `expire_on_commit=False` is set on the production session factory
  (`app/db/engine.py`), so accessing `FeedSource` attributes after the
  session closes in `IngestStep.execute` is safe.
- `read_feed` also re-exports `XmlParseError` (beyond the brief's list)
  since `steps.py`/tests may need it; harmless superset.
- The `fetcher` parameter on `create_app` follows the existing injection
  pattern (`session_store`, `clock`, `db_session_factory`) and was required
  to keep M2 acceptance/runs-API tests green without network access.
- Row-error statistics cap at 100 entries per the decision; verified by a
  dedicated test with 150 bad rows.

## Concerns

- `test_m2_acceptance.py` and `test_runs_api.py` semantics shifted slightly:
  feed sources now require `source_url` for a successful run (correct new
  behavior), and they use a stub fetcher. Task 9's M3 acceptance test will
  exercise the same seam with richer fixtures.
- `IngestStep` treats a missing `basic_auth` username/password key as an
  absent-credentials case only when the whole dict is absent; a partial
  `{"username": ...}` dict yields `KeyError`. Not covered by the brief;
  configuration validation is out of scope here.
