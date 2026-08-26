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

