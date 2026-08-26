# Pytest Optimization Implementation Plan (pytest-postgresql + pytest-xdist)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut backend suite wall time (~100 s baseline) by cloning Alembic-migrated template databases per test (pytest-postgresql) and running the suite in parallel by default (pytest-xdist).

**Architecture:** `backend/tests/conftest.py` swaps the hand-rolled create/migrate/drop fixture for the plugin's `postgresql_noproc` + `postgresql` pair. A `load=` callable runs the Alembic chain once per worker into the plugin's template database; each test gets a fast `CREATE DATABASE … TEMPLATE` clone. `isolated_database_url` keeps its exact name and yield-a-URL contract, so consuming tests don't change. Parallelism turns on via `addopts = "-n auto"`.

**Tech Stack:** pytest-postgresql 7.x (psycopg 3 sync driver — used only by the plugin internally; tests stay on asyncpg), pytest-xdist 3.x, uv, Alembic programmatic API. Exact pins recorded in `docs/decisions.md`.

**Design doc:** `docs/superpowers/specs/2026-08-26-pytest-optimization-design.md` (incl. spec-owner notes: dispose template connections before clone; cap test-engine pools `pool_size=2, max_overflow=0`; pytest-cov deferred)

## Global Constraints

- `TEST_DATABASE_URL` remains required, must remain `postgresql+asyncpg://`, and missing/invalid must fail fast with today's messages. All commands run with it set: `export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres`.
- Fixture contract: `isolated_database_url(request)` yields a `postgresql+asyncpg://` URL pointing at a fully-migrated, per-test database. No consuming test may be edited except the Alembic-driving migration tests **if** (and only if) their assumptions break against a pre-migrated clone.
- Engine pool caps: every `create_async_engine(...)` in `backend/tests/` gains `pool_size=2, max_overflow=0` (spec-owner decision).
- Parallelism: `[tool.pytest.ini_options] addopts = "-n auto"`; opt-out `-n0`; cap via `PYTEST_XDIST_AUTO_NUM_WORKERS`.
- Exact dependency pins; record resolved versions + before/after wall times in `docs/decisions.md` under a dated entry.
- Baseline for comparisons: 366 passed, ~100 s serial (measured 2026-08-26).
- Worktree workflow: implement in `.worktrees/pytest-optimization` on branch `pytest-optimization`.

---

### Task 1: Install and pin the plugins

**Files:**
- Modify: `backend/pyproject.toml` (dev dependencies)
- Modify: `backend/uv.lock` (via uv)
- Modify: `docs/decisions.md` (versions entry)

**Interfaces:**
- Produces: importable `pytest_postgresql.factories` and xdist `-n` flag in the backend venv; exact pins in `pyproject.toml`.

- [ ] **Step 1: Add the plugins**

From `backend/`:

```bash
uv add --dev pytest-postgresql pytest-xdist
```

- [ ] **Step 2: Pin exact versions**

Read the resolved versions (`uv pip list | grep -E "pytest-postgresql|pytest-xdist"`), then edit `pyproject.toml` dev-dependencies to exact `==` pins (e.g. `pytest-postgresql==7.0.2`, `pytest-xdist==3.8.0` — whatever uv resolved) and run `uv sync --frozen` to regenerate consistency.

- [ ] **Step 3: Verify plugin registration**

Run: `cd backend && uv run pytest --co -q tests/test_config.py -p no:xdist 2>&1 | tail -2 && uv run pytest --version`
Expected: collection succeeds; `pytest --version` output lists `pytest-xdist` and `pytest-postgresql` among registered plugins. Also confirm `uv run pytest tests/test_config.py -n0` still passes (plugins inert so far).

- [ ] **Step 4: Record versions**

Append to `docs/decisions.md` under a new `### Pytest optimization tooling` entry (dated 2026-08-26): topic, decision (plugins adopted for template-DB isolation + parallel execution), resolved exact versions, and rationale referencing the spec.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock docs/decisions.md
git commit -m "chore: add pinned pytest-postgresql and pytest-xdist"
```

---

### Task 2: Template-database fixture rework

**Files:**
- Modify: `backend/tests/conftest.py` (replace `isolated_database_url` internals; add plugin wiring)
- Possibly modify: `backend/tests/test_migrations.py`, `backend/tests/test_m2_migration.py`, `backend/tests/test_m5_migration.py` ONLY if their assumptions break (see Step 4)

**Interfaces:**
- Consumes: `TEST_DATABASE_URL` env var; Alembic programmatic API; `pytest_postgresql.factories`.
- Produces: unchanged `isolated_database_url(request)` fixture yielding `postgresql+asyncpg://user:pass@host:port/dbname` for a fully-migrated per-test database. All other test files untouched.

- [ ] **Step 1: Rework conftest.py**

Replace the imports block and the whole `isolated_database_url` fixture with the following. Keep every other existing fixture (`artifact_path`, `clock`, `store`, `settings`, `client`) byte-identical.

New/changed imports (top of file):

```python
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest
from alembic import command
from alembic.config import Config
from pytest_postgresql import factories
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.config import Settings
from app.main import create_app
from app.session_store import InMemorySessionStore
```

Remove now-unused imports (`asyncio`, `uuid`, `urlunsplit`, `asyncpg`) unless something else in the file still uses them — nothing else does.

Module-level wiring (place after the `_ARTIFACT_PATH` definition):

```python
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _server_params() -> dict:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL via asyncpg")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg:// dialect")
    parts = urlsplit(value)
    return {
        "host": parts.hostname or "localhost",
        "port": parts.port or 5432,
        "user": parts.username or "postgres",
        "password": parts.password or "",
    }


def _load_alembic_schema(**kwargs):
    """Populate the plugin's template database with the full migration chain."""
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    password = quote(kwargs.get("password") or "", safe="")
    url = (
        f"postgresql+asyncpg://{kwargs['user']}:{password}"
        f"@{kwargs['host']}:{kwargs['port']}/{kwargs['dbname']}"
    )
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    # alembic's env.py disposes its own engine before returning, so no
    # connections hold the template open when the plugin clones it.


_server = _server_params()

gmc_postgres_noproc = factories.postgresql_noproc(
    host=_server["host"],
    port=_server["port"],
    user=_server["user"],
    password=_server["password"],
    load=[_load_alembic_schema],
)

gmc_database = factories.postgresql("gmc_postgres_noproc")


def _asyncpg_url(info) -> str:
    password = quote(info.password or "", safe="")
    return (
        f"postgresql+asyncpg://{info.user}:{password}"
        f"@{info.host}:{info.port}/{info.dbname}"
    )


@pytest.fixture
def isolated_database_url(request):
    _server_params()
    connection = request.getfixturevalue("gmc_database")
    return _asyncpg_url(connection.info)
```

Delete the entire old `isolated_database_url` fixture (the asyncpg CREATE/DROP DATABASE version).

Notes for the implementer:
- `_server_params()` is called twice by design: once at import to parametrize the factory, once inside the fixture to preserve the fail-fast contract when the env var is missing (the check runs *before* `getfixturevalue` spins up the plugin machinery).
- The plugin's `postgresql` fixture yields a psycopg `Connection`; `.info` exposes host/port/dbname/user/password.
- If the installed pytest-postgresql version names the loader parameter or kwarg shape differently than `load=[callable]` / `**kwargs` with `dbname`, consult its docs (`uv run python -c "import pytest_postgresql.factories as f; help(f.postgresql_noproc)"`) and adapt the call — the behavioral contract above is binding, not the literal signature.

- [ ] **Step 2: Verify serially against the DB-heavy suites**

```bash
cd backend && export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
uv run pytest tests/test_config_bundle.py tests/test_staging_step.py -q -n0
```
Expected: PASS. First test pays the one-time template migration; subsequent setups should be visibly faster (look at `--durations=5` if curious).

- [ ] **Step 3: Full suite, serial**

```bash
uv run pytest -q -n0 2>&1 | tail -1
```
Expected: 366 passed. If any of the three migration-driving test files fail because they assumed an empty database, adapt ONLY those tests minimally (e.g. begin with `command.downgrade(config, "base")` before their upgrade flow) and justify each change in the report. Anything beyond those three files failing = stop and report BLOCKED.

- [ ] **Step 4: Measure and record**

Record the `-n0` wall time (from pytest's summary line) in a working note (final numbers go into decisions.md in Task 4).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/conftest.py backend/tests/test_migrations.py backend/tests/test_m2_migration.py backend/tests/test_m5_migration.py
git commit -m "feat: template-database test isolation via pytest-postgresql"
```
(Include migration-test files only if actually modified.)

---

### Task 3: Cap test-engine pools

**Files:**
- Modify: all 21 test files under `backend/tests/` containing `create_async_engine(` (57 call sites; authoritative list via `grep -rln create_async_engine backend/tests`)

**Interfaces:**
- Consumes: nothing new.
- Produces: every test engine created with `pool_size=2, max_overflow=0` (spec-owner decision).

- [ ] **Step 1: Mechanical sweep**

Every `create_async_engine(<url-expr>)` call in `backend/tests/**` becomes `create_async_engine(<url-expr>, pool_size=2, max_overflow=0)`. Multi-line calls get the kwargs appended to the argument list. Do NOT touch `backend/app/` production engine creation (`app/db/engine.py` or equivalent) — this cap applies to tests only.

After the sweep, verify completeness:

```bash
grep -rn "create_async_engine(" backend/tests | grep -v "pool_size=2" || echo CLEAN
```
Expected: `CLEAN`.

- [ ] **Step 2: Full suite, serial**

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q -n0 2>&1 | tail -1
```
Expected: 366 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests
git commit -m "perf: cap test-engine pools (pool_size=2, max_overflow=0)"
```

---

### Task 4: Enable parallel-by-default + documentation + gate

**Files:**
- Modify: `backend/pyproject.toml` (`[tool.pytest.ini_options]`)
- Modify: `README.md` (testing instructions)
- Modify: `docs/decisions.md` (wall-time results)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `uv run pytest` runs parallel by default; documented opt-outs.

- [ ] **Step 1: Turn on xdist by default**

In `backend/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-n auto"
```

- [ ] **Step 2: Run the parallel gate**

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q 2>&1 | tail -1
```
Expected: 366 passed. Run it twice if flaky-looking; investigate any failure individually with `-n0` reproduction before assuming parallelism is at fault (report BLOCKED if a genuine parallel-only defect appears).

Also verify the opt-out path: `uv run pytest -q -n0` → 366 passed.

- [ ] **Step 3: Update README testing section**

In `README.md`, extend the existing test guidance with:

```markdown
Backend tests run in parallel by default (pytest-xdist, `-n auto`). Disable
with `uv run pytest -n0` or cap workers with `PYTEST_XDIST_AUTO_NUM_WORKERS`.
Integration tests still require `TEST_DATABASE_URL` pointing at a
`postgresql+asyncpg://` server; each test runs against its own database cloned
from an Alembic-migrated template, so the migration chain runs once per
worker rather than once per test.
```

- [ ] **Step 4: Record results in decisions.md**

Extend the `Pytest optimization tooling` entry with: baseline (366 passed, ~100 s serial), after-template-serial time (Task 2 Step 4), after-parallel time (Step 2 above), and the three spec-owner notes as implemented (template connection disposal inside `load=`; pool caps swept across 57 sites; pytest-cov parallel-mode explicitly deferred).

- [ ] **Step 5: Final gate + commit**

```bash
cd frontend && npm run test -- --run && npm run typecheck && npm run build && cd ../backend
uv run python -m compileall app
git diff --check
git add backend/pyproject.toml ../README.md ../docs/decisions.md
git commit -m "feat: parallel pytest by default with xdist"
```
Expected: frontend green, compileall clean, diff check clean.

---

## Self-Review Checklist (completed during planning)

- Spec coverage: template cloning via `load=` hook (Task 2), `TEST_DATABASE_URL` contract preserved (Task 2), pool caps incl. 57-site sweep (Task 3), `-n auto` default with opt-outs (Task 4), README + decisions.md updates incl. wall times and the three spec-owner notes (Tasks 1/4), migration-test contingency named (Task 2 Step 3).
- Placeholder scan: none; every code step carries full code or exact edit rules.
- Type consistency: fixture name/yield type unchanged; helper names (`_server_params`, `_load_alembic_schema`, `_asyncpg_url`, `gmc_postgres_noproc`, `gmc_database`) defined in Task 2 and referenced nowhere else.
