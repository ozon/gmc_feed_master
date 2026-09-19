# Tooling Lows (T10, T11, T12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three remaining low-severity tooling findings: `.env.example` dialect, CI double-run + both-DB-URLs warning, and inconsistent dependency pinning.

**Architecture:** Config/CI-only. No application logic changes, no dependency version changes.

**Tech Stack:** GitHub Actions, uv, Ruff/mypy/pytest.

**Spec:** `docs/superpowers/specs/2026-09-19-tooling-lows-design.md`.

## Global Constraints

- `T8` and `T9` are **deferred** — do not move the root instruction docs or delete `examples/feed.xml`.
- No dependency version changes: the three pins must equal the installed lock versions (`uvicorn 0.52.4`, `structlog 26.1.0`, `mypy 2.3.1`), so `uv lock` is a no-op.
- `DATABASE_URL` must remain available to the two Alembic CI steps.
- Backend commands run from `backend/`; DB-backed tests need `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres`.

---

### Task 1: `.env.example` dialect (T10)

**Files:** Modify `.env.example`

- [ ] **Step 1: Edit the URL + comment**

Replace:

```
# Runtime and Alembic migration URL. Alembic CLI migrations are explicit; the
# backend never creates tables at runtime.
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/gmc_feed
```

with:

```
# Runtime and Alembic migration URL. Prefer the asyncpg form; the app and
# Alembic also accept plain `postgresql://` / `postgres://` and normalize it.
# Alembic CLI migrations are explicit; the backend never creates tables at
# runtime.
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed
```

- [ ] **Step 2: Verify and commit**

Run: `git grep -n 'asyncpg' .env.example`
Expected: the new URL is present.

```bash
git add .env.example
git commit -m "docs(env): ship the asyncpg DATABASE_URL form"
```

---

### Task 2: CI branch filter + DB-URL scoping (T11)

**Files:** Modify `.github/workflows/ci.yml`

- [ ] **Step 1: Limit `push` to main and drop the job-level `DATABASE_URL`**

Replace the workflow trigger and backend job env:

```yaml
on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    env:
      SESSION_SECRET: ci-only-session-secret
      INITIAL_USERNAME: ci-user
      INITIAL_PASSWORD: ci-only-password
      TEST_DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed
```

- [ ] **Step 2: Scope `DATABASE_URL` to the two Alembic steps**

Add a step-level `env` to both `Run alembic migrations` and `Alembic drift gate (no pending model changes)`:

```yaml
      - name: Run alembic migrations
        working-directory: backend
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed
        run: uv run alembic upgrade head
      - name: Alembic drift gate (no pending model changes)
        working-directory: backend
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed
        run: uv run alembic check
```

- [ ] **Step 3: Verify the YAML parses and the test step has no `DATABASE_URL`**

Run: `uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok`.

Read the file and confirm no `DATABASE_URL` appears in the `backend.env` block and the two `DATABASE_URL` entries are on the Alembic steps only.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run on main pushes only and scope DATABASE_URL to alembic"
```

---

### Task 3: Exact pins (T12)

**Files:** Modify `backend/pyproject.toml`

- [ ] **Step 1: Pin the three ranges**

In `[project].dependencies`:

```
  "uvicorn[standard]==0.52.4",
  "structlog==26.1.0",
```

In `[dependency-groups].dev`:

```
  "mypy==2.3.1",
```

- [ ] **Step 2: Confirm the lock is unchanged**

Run: `uv lock 2>&1 | tail -3 && uv lock --check 2>&1 | tail -1`
Expected: resolution unchanged; `uv lock --check` succeeds.

Run: `uv sync --locked 2>&1 | tail -3`
Expected: no version changes.

- [ ] **Step 3: Verify gates unaffected**

Run: `uv run ruff check . ../plugins && uv run mypy . 2>&1 | tail -1`
Expected: ruff `All checks passed!`; mypy `Success`.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build(deps): exact-pin uvicorn, structlog, and mypy"
```

---

### Task 4: Record status

**Files:** Modify `docs/reports/2026-09-17-04-tooling-testing.md`, `docs/reports/2026-09-17-00-review-overview.md`, `TODO.md`

- [ ] **Step 1: Update the tooling report status table**

Change the `T8`/`T9` rows to `Deferred (operator decision)` and the `T10`/`T11`/`T12` rows to Fixed with one-line notes: asyncpg form in `.env.example`; CI `push` limited to `main` with `DATABASE_URL` scoped to Alembic steps; `uvicorn`/`structlog`/`mypy` exact-pinned.

- [ ] **Step 2: Update the overview remediation line**

Change the open-items sentence so `T8`/`T9` read as deferred by choice and `T10`–`T12` are removed from the open list (or noted as fixed).

- [ ] **Step 3: Add the cycle-log entry**

At the top of `## Cycle log` in `TODO.md`, add a concise bullet for the `chore/tooling-lows` branch: T10/T11/T12, with the gates.

- [ ] **Step 4: Commit**

```bash
git add docs/reports/2026-09-17-04-tooling-testing.md docs/reports/2026-09-17-00-review-overview.md TODO.md
git commit -m "docs: record tooling-lows status (T10-T12)"
```

---

## Final Verification

- [ ] `cd backend && uv lock --check` → consistent, unchanged.
- [ ] `cd backend && uv run ruff check . ../plugins` → exit 0.
- [ ] `cd backend && uv run mypy . && MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins` → clean.
- [ ] `uv run --with pyyaml` parses `.github/workflows/ci.yml`.
- [ ] `git grep -n 'DATABASE_URL' .github/workflows/ci.yml` → only the two Alembic steps.
- [ ] `git grep -n 'asyncpg' .env.example` → present.

## Self-Review (completed by plan author)

- **Spec coverage:** T10 → Task 1; T11 → Task 2; T12 → Task 3; status docs → Task 4. T8/T9 deferred per spec. Covered.
- **Placeholder scan:** none.
- **Type consistency:** the `DATABASE_URL` value (`postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed`) is byte-identical in `.env.example`, both CI steps, and Final Verification; pin versions match the spec.
