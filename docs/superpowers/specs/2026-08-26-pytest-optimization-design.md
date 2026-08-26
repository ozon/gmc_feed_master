# Pytest Optimization Design: pytest-postgresql + pytest-xdist

**Date:** 2026-08-26
**Status:** Approved
**Builds on:** M5 (`dd2dce2` on `main`)
**Implements:** infrastructure only — no product behavior; governed by AGENTS.md §4 (library docs, exact pins) and the testing conventions established in M1–M5.

## Problem

The backend suite (366 tests) takes ~100 s serially. Two compounding costs:

1. **Per-test migrations.** `isolated_database_url` runs the full Alembic chain
   for every DB-backed test (~56 tests × ~0.85 s setup ≈ 45–50 s).
2. **Serial execution.** All 366 tests run in one process despite being
   parallelizable (no shared mutable state, no ports; DB isolation is
   per-test by construction).

## Solution

Two plugins, exact-pinned as dev dependencies via uv:

| Plugin | Role |
|---|---|
| `pytest-postgresql` (7.x) | Manages per-test database lifecycle against the existing Docker Postgres using template-database cloning |
| `pytest-xdist` (3.x) | Runs the suite across worker processes, `-n auto` by default |

## conftest rework

Fixture contract is unchanged: `isolated_database_url` keeps its name and its
yield-a-`postgresql+asyncpg://`-URL behavior. Zero changes in consuming tests.

- `TEST_DATABASE_URL` remains the documented entry point: still required,
  still must be `postgresql+asyncpg://`, still fails fast otherwise. It is
  parsed once into host/port/user/password/admin-database components.
- A `load=[...]` callable passed to `factories.postgresql_noproc(...)`
  populates the plugin's template database by running the Alembic migration
  chain once (per xdist worker) — same programmatic
  `asyncio.run(command.upgrade(config, "head"))` pattern used today.
- `factories.postgresql("...")` produces a per-test database cloned from that
  template (`CREATE DATABASE … TEMPLATE`), dropping it afterwards. Clone cost
  replaces migration cost (~50–100 ms vs ~850 ms). Database names are unique
  per test and per xdist worker (safe since pytest-postgresql 4.0).
- The fixture builds the asyncpg URL from the plugin's connection info.
- Tests that drive Alembic themselves (`test_migrations.py`,
  `test_m5_migration.py`) start from an already-migrated clone instead of an
  empty database. Their downgrade/upgrade flows are expected to tolerate this;
  implementation must verify each assumption and adapt those specific tests
  only if they genuinely require a clean slate (e.g. explicit
  `downgrade base` first).

## xdist configuration

`[tool.pytest.ini_options] addopts = "-n auto"` in `backend/pyproject.toml`:

- Plain `uv run pytest` is parallel (approved decision 2026-08-26).
- `-n0` disables; `PYTEST_XDIST_AUTO_NUM_WORKERS` caps worker count.
- Connection budget: per-test engines are created and disposed within a test,
  so peak load ≈ workers × small pool against Docker's default
  `max_connections=100`. Documented fallback: `-n 4` for low-limit servers.
- Parallel-safety review of existing suites: subprocess tooling tests spawn
  independent interpreters; scheduler tests use in-process APScheduler with no
  ports; TestClient tests are in-process; registry fixtures are read-only
  module-scoped. No FileLock coordination needed.

## Docs & CI

- README test section: parallel-by-default note, `-n0` opt-out, unchanged
  `TEST_DATABASE_URL` contract.
- CI needs no structural change (Postgres service already present); lockfile
  updates flow through the committed `uv.lock`.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Fixture surface | Keep `isolated_database_url` name/contract | ~56 call sites stay untouched; diff stays inside conftest |
| Migration entry point | `TEST_DATABASE_URL` parsed for plugin params | Preserves documented contract and CI wiring verbatim |
| Parallelism default | On (`addopts = "-n auto"`) | Approved 2026-08-26; opt-out via `-n0` |
| Template population | Alembic inside the plugin `load=` hook | Single source of schema truth stays the migration chain |
| Pins | Exact versions recorded in `docs/decisions.md` at install | AGENTS.md §4 rule |

## Verification

- Full suite green both ways: parallel (new default) and `-n0`.
- Before/after wall times recorded in `docs/decisions.md`
  (baseline: 366 passed in ~100 s serial).
- No test-file changes expected outside conftest; if any prove necessary,
  each is justified in the implementation report.
