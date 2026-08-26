# Task 4 Report: Enable parallel-by-default + documentation + gate

## Status: COMPLETE

**Commit:** `bd7fff3` — `feat: parallel pytest by default with xdist`
(3 files changed, 31 insertions: backend/pyproject.toml, README.md, docs/decisions.md)

## Step 1 — Turn on xdist by default

`backend/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-n auto"
```

## Step 2 — Parallel gate

Run 1:

```
$ TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q
366 passed, 21 warnings in 26.77s        (real ~29.7s)
```

Run 2 (stability):

```
366 passed, 21 warnings in 27.28s        (real ~29.2s)
```

No flaky-looking failures; no `-n0` reproduction needed.

Opt-out path:

```
$ TEST_DATABASE_URL=… uv run pytest -q -n0
366 passed, 11 warnings in 53.38s        (real ~57.2s)
```

## Step 3 — README testing section

Appended after the existing `TEST_DATABASE_URL` guidance in `README.md`, using
the exact wording from the brief (parallel-by-default, `-n0` opt-out,
`PYTEST_XDIST_AUTO_NUM_WORKERS` cap, per-test template-cloned databases,
migration chain once per worker).

## Step 4 — decisions.md results

Extended `### Pytest optimization tooling` with:

- Parallel-by-default configuration (`addopts = "-n auto"`) and opt-outs.
- Wall times: baseline serial ~100.8 s → post-template serial 51.9 s
  (Task 2's 51.88 s) → parallel `-n auto` 26.8 s / 27.3 s (~3.8× vs baseline,
  ~1.9× vs post-template serial).
- Spec-owner notes as implemented:
  1. Template connection disposal inside `load=` (`backend/tests/conftest.py`,
     `_load_alembic_schema`; alembic env.py disposes its engine before the hook
     returns).
  2. Pool caps swept across all test-engine call sites — recorded as the
     verified actual **36 call sites / 20 files** under `backend/tests/`, with
     an explicit note that the earlier "57 sites" figure overcounted by
     including import lines (per Task 3 report scope correction).
  3. pytest-cov parallel-mode explicitly deferred.
- Accuracy check against Task 2/3 reports: serial number matches (51.88 s);
  pool-cap counts match Task 3's corrected figures; disposal note matches
  conftest.py:43-54.

## Step 5 — Final gate

Frontend (all green):

```
$ npm run test -- --run   → Test Files 1 passed (1); Tests 8 passed (8)
$ npm run typecheck       → tsc -b, no errors
$ npm run build           → ✓ built in 191ms (17 modules)
```

Backend:

```
$ uv run python -m compileall app   → clean listing, exit 0
$ git diff --check                  → clean (no whitespace errors)
```

Commit: staged exactly `backend/pyproject.toml`, `README.md`, `docs/decisions.md`;
message `feat: parallel pytest by default with xdist`. Note: the brief's literal
`git add backend/pyproject.toml ../README.md ../docs/decisions.md` mixes
cwd-relative and parent-relative paths and fails from any single directory in a
worktree where the worktree root is the repo root; equivalent repo-root-relative
paths were used instead (same three files).

Pre-existing uncommitted `.superpowers/sdd/*` edits from earlier tasks were left
out of the commit, consistent with Tasks 2–3.

## Self-review

- README wording matches reality: `-n auto` is on by default via addopts;
  `-n0` verified working; template cloning per worker is what conftest does. ✅
- decisions.md numbers accurate (100.82 baseline given by orchestrator;
  51.88 from Task 2 report; 26.77/27.28 measured here; speedups recomputed). ✅
- All gate commands actually run with outputs above; nothing skipped. ✅
- Commit contains only the three intended files (verified via `git show --stat`). ✅

## Concerns

None blocking. Minor: brief's `git add` path mix requires adjustment when run
from a worktree root (documented above).

## Polish round

Applied final-review minors: robustness guards in `_server_params()` (urlsplit
errors and query parameters now yield the canonical friendly failure),
`psycopg.ConnectionInfo` type annotation for `_asyncpg_url`, and a README
sentence documenting explicit worker capping on tight-connection-limit servers.

Gate 1 — full suite with integration env:

```
$ cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q
366 passed, 21 warnings in 27.44s
```

Gate 2 — guard sanity check without env var (expected fast failure at
collection, not fixed):

```
$ cd backend && unset TEST_DATABASE_URL && uv run pytest tests/test_config.py -q
Failed: TEST_DATABASE_URL must point to PostgreSQL via asyncpg
```
