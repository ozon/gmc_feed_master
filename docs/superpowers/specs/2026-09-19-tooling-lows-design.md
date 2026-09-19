# Tooling Lows (T10, T11, T12) — Design

**Date:** 2026-09-19
**Status:** Approved (design), pending implementation plan
**Scope:** Backend/tooling config + CI only. Closes `T10`, `T11`, `T12` from `docs/reports/2026-09-17-04-tooling-testing.md`. `T8`/`T9` were explicitly deferred by the operator (stale root instruction docs and the duplicate `examples/feed.xml` stay).

## Problem

Three low-severity tooling findings remain:

- **T10** — `.env.example` ships the sync `postgresql://` dialect while every documented command and the `Makefile` default use `postgresql+asyncpg://`. The app normalizes both, so it works, but it is a needless contributor trap.
- **T11** — `ci.yml` runs on `push` (all branches) **and** `pull_request`, double-running PR branches, and sets both `DATABASE_URL` and `TEST_DATABASE_URL` at job level, which `backend/tests/conftest.py` warns about by design on every test run.
- **T12** — pinning is inconsistent: nearly everything is exact-pinned, but `uvicorn[standard]>=0.30,<1`, `structlog>=25.1,<27`, and `mypy>=2.3.1` remain ranges.

## Decision

| Topic | Decision |
|-------|----------|
| T10 | `.env.example` uses `postgresql+asyncpg://` and a comment noting `postgresql://`/`postgres://` are also accepted |
| T11 | `push` limited to `main`; move `DATABASE_URL` from the backend job `env` onto the two Alembic steps, leaving `TEST_DATABASE_URL` job-wide |
| T12 | Exact-pin `uvicorn[standard]==0.52.4`, `structlog==26.1.0`, `mypy==2.3.1` (the installed lock versions, so the lock is unchanged) |
| T8/T9 | Deferred by operator decision — recorded, not done |

Rationale: these are the last cheap credibility items from the review. `DATABASE_URL` must stay available to `alembic upgrade head`/`alembic check` (they read it), so the fix is scope-by-step rather than removal; the pytest step then sees only `TEST_DATABASE_URL` and stops tripping the intentional warning. The pins match what is already installed, so they document the current reality without a dependency change.

## Design

### T10 — `.env.example`
Replace the URL and comment:

```
# Runtime and Alembic migration URL. Prefer the asyncpg form; the app and
# Alembic also accept plain `postgresql://` / `postgres://` and normalize it.
# Alembic CLI migrations are explicit; the backend never creates tables at
# runtime.
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed
```

### T11 — `.github/workflows/ci.yml`
- `on:` → `push: branches: [main]` plus the existing `pull_request:`.
- Remove `DATABASE_URL` from the backend job's `env` block (keep `TEST_DATABASE_URL`).
- Add a step-level `env: DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed` to `Run alembic migrations` and `Alembic drift gate (no pending model changes)`.

No other step reads `DATABASE_URL`; `docker compose up -d --wait postgres` and `compileall` do not.

### T12 — `backend/pyproject.toml`
```
"uvicorn[standard]==0.52.4",
"structlog==26.1.0",
...
"mypy==2.3.1",
```

### Docs
Update the tooling report status table (`T8`/`T9` → Deferred, `T10`–`T12` → Fixed), the overview remediation line, and add a `TODO.md` cycle-log entry.

## Verification

- `uv lock --check` passes and `uv lock` is a no-op (pins equal installed versions).
- `cd frontend` untouched; `ruff`/`mypy`/full `pytest` unaffected (config-only).
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` parses.
- `env | grep DATABASE_URL` semantics: the test step no longer has `DATABASE_URL` set (verified by the job/step env layout).
- `git grep -n 'asyncpg' .env.example` shows the new URL.

## Risks and non-goals

- **T11 Alembic env.** `backend/alembic/env.py` reads `config.attributes["database_url"]` first, then `DATABASE_URL`; the step-level env feeds the second path. If a future step needs the DB URL, it must declare it too.
- **T12 cosmetic.** Exact pins for already-installed versions; `uv sync --locked` behaviour is unchanged. Dependabot (T2) will still propose upgrades.
- **Non-goals:** `T8`/`T9` (operator-deferred), any dependency version change, and any application behavior change.

## References

- `docs/reports/2026-09-17-04-tooling-testing.md` findings `T10`–`T12`.
- `.env.example`, `.github/workflows/ci.yml`, `backend/pyproject.toml`, `backend/alembic/env.py`, `backend/tests/conftest.py`.
