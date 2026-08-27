### Task 1: Dependency + settings plumbing

**Files:**
- Modify: `backend/pyproject.toml` (add `jsonschema`)
- Modify: `backend/app/config.py` (add `plugins_dir` setting)
- Modify: `docs/decisions.md` (pin record)

**Interfaces:**
- Produces: `Settings.plugins_dir: str` (absolute default `<repo>/plugins`); importable `jsonschema`.

- [ ] **Step 1: Add and pin jsonschema**

From `backend/`: `uv add jsonschema`, then edit pyproject to the exact resolved `==` pin and `uv sync --frozen`. Record the resolved version in `docs/decisions.md` (extend the tooling entry or a new dated line).

- [ ] **Step 2: Add plugins_dir to Settings**

In `backend/app/config.py`, add after `database_url`:

```python
    plugins_dir: str = str(Path(__file__).resolve().parents[2] / "plugins")
```

(`Path` is already imported there.)

- [ ] **Step 3: Verify**

Run: `cd backend && uv run python -c "from app.config import Settings; print(Settings(_env_file=None, session_secret='x', initial_username='x', initial_password='x').plugins_dir)" && uv run python -c "import jsonschema; print(jsonschema.__version__)"`
Expected: prints the repo-root `plugins` path and the pinned version.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/config.py docs/decisions.md
git commit -m "chore: add jsonschema and plugins_dir setting"
```

---

