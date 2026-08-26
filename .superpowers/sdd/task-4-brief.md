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
