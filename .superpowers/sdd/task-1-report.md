# Task 1 Report: Install and pin the plugins

**Status:** DONE
**Commit:** `0a7192a` — chore: add pinned pytest-postgresql and pytest-xdist

## What was done

1. **Step 1 — Add plugins.** Ran `uv add --dev pytest-postgresql pytest-xdist`
   from `backend/`. Resolved: `pytest-postgresql==8.1.0`,
   `pytest-xdist==3.8.0`, plus transitive deps (execnet 2.1.2, mirakuru 3.0.2,
   port-for 1.0.0, psutil 7.2.2, psycopg 3.3.4).

2. **Step 2 — Pin exact versions.** `uv add` wrote `>=` specifiers; edited
   `backend/pyproject.toml` dev group to exact pins:
   - `pytest-postgresql==8.1.0`
   - `pytest-xdist==3.8.0`

   Then `uv lock && uv sync --frozen`. Lockfile confirms:
   ```
   [[package]]
   name = "pytest-postgresql"
   version = "8.1.0"

   [[package]]
   name = "pytest-xdist"
   version = "3.8.0"
   ```

3. **Step 3 — Verify plugin registration.**
   - `uv run pytest --co -q tests/test_config.py -p no:xdist` →
     `5 tests collected in 0.01s`.
   - `uv run pytest --version --version` lists registered third-party plugins:
     `pytest-xdist-3.8.0` and `pytest-postgresql-8.1.0` (plus anyio,
     pytest-asyncio).
   - `uv run python -c "import pytest_postgresql.factories; import xdist"` →
     `imports OK`.
   - `uv run pytest tests/test_config.py -n0` → `5 passed`.

4. **Full-suite greenness check** (baseline must stay green):
   `TEST_DATABASE_URL=... uv run pytest -q` → **366 passed** in 100s.
   Matches the serial baseline exactly.

5. **Step 4 — Record versions.** Appended `### Pytest optimization tooling`
   entry dated 2026-08-26 to `docs/decisions.md` under the existing
   `## 2026-08-26` section: topic, decision, exact resolved versions,
   rationale referencing the pytest-optimization design doc.

6. **Step 5 — Commit.** Staged exactly `backend/pyproject.toml`,
   `backend/uv.lock`, `docs/decisions.md`; committed with the brief's message.

## Files changed

- `backend/pyproject.toml` — two exact-pinned dev deps added
- `backend/uv.lock` — regenerated via `uv lock` after pinning
- `docs/decisions.md` — new `### Pytest optimization tooling` entry

## Self-review

- Pins truly exact (`==`) in pyproject? ✅ verified via diff and lockfile.
- Lockfile consistent with pyproject? ✅ `uv sync --frozen` succeeded after
  pin edit (frozen check passes only when lock matches manifest).
- Decisions entry accurate (versions, date, rationale)? ✅ versions match
  resolved/locked values; date 2026-08-26.
- Only the three intended files committed? ✅ `git status --short` shows only
  `.superpowers/sdd/task-1-brief.md` left modified (pre-existing unstaged
  rewrite of that file from before this task started — intentionally not
  touched or staged).

## Concerns

- None blocking. Environment note: a stale `VIRTUAL_ENV` pointing at the main
  checkout's venv produced a harmless uv warning in every command; worktree's
  own `.venv` was used correctly throughout.
