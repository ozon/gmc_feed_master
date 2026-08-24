# Task 3 report: M1 baseline migration

## Implemented

- Added `backend/alembic/versions/20260824_0001_m1_baseline.py` as the concrete M1 baseline revision.
- The revision creates all 15 application tables, PostgreSQL JSONB columns, timezone-aware timestamps, token/revocation fields, primary/unique constraints, foreign keys, indexes, scoped plugin partial unique indexes, and scope-owner checks.
- Cyclic feed-source/pipeline and export-run/export-version relationships are created with deferred foreign-key operations after their tables exist.
- Downgrade removes cyclic foreign keys, indexes, and tables in reverse dependency order.
- Added PostgreSQL-only migration tests with an isolated temporary database. Tests explicitly run Alembic CLI commands for upgrade, downgrade, and re-upgrade and verify table names, indexes, constraints, foreign keys, and scoped checks. Missing or non-PostgreSQL `TEST_DATABASE_URL` fails clearly.
- Updated root `.env.example` and `README.md` with explicit migration URL and `alembic upgrade head` / `alembic downgrade base` commands. Runtime application code remains free of `create_all` calls.

## Verification

- Focused migration test: `1 passed` against Compose PostgreSQL.
- Full backend tests: `49 passed` against Compose PostgreSQL migration test configuration.
- `uv run python -m compileall -q app alembic tests`: passed.
- Explicit CLI downgrade and upgrade against Compose PostgreSQL: both exited successfully.

## Notes

- Alembic emits its existing `prepend_sys_path` deprecation warning and the existing Starlette/httpx deprecation warning; no test failures or migration errors remain.
