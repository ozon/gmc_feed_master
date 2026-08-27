# Task 1 Report: Dependency + settings plumbing

**Status:** COMPLETE
**Commit:** `5806fc9` — `chore: add jsonschema and plugins_dir setting`

## Steps performed

1. **Add and pin jsonschema** (`backend/`):
   - `uv add jsonschema` → resolved `jsonschema==4.26.0`.
   - Edited `backend/pyproject.toml` from `>=4.26.0` to exact pin `==4.26.0`
     (per AGENTS.md exact-pin rule), then `uv lock && uv sync --frozen`.
   - Lockfile now carries `specifier = "==4.26.0"` (uv.lock line 398).
2. **plugins_dir setting**: added after `database_url` in
   `backend/app/config.py:15`, exactly per brief:
   ```python
   plugins_dir: str = str(Path(__file__).resolve().parents[2] / "plugins")
   ```
3. **Pin record**: new dated entry "M6 plugin-host dependency pins" under
   2026-08-26 in `docs/decisions.md`.

## Verification

```
$ uv run python -c "...Settings(...).plugins_dir)"
/home/ozon/gmc_feed_master/.worktrees/m6-plugin-host/plugins
$ uv run python -c "import jsonschema; print(jsonschema.__version__)"
4.26.0
```

Both match expectations (repo-root `plugins` path, pinned version).
Note: `jsonschema.__version__` emits a DeprecationWarning (deprecated access
path); version confirmed as 4.26.0 regardless.

Regression check: full backend suite against
`TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres`
→ **366 passed, 21 warnings in 28.10s** (baseline held).

## Commit

Staged exactly the four brief-specified files:
- `backend/pyproject.toml` (+1 line)
- `backend/uv.lock` (+309 lines: jsonschema + transitive attrs,
  jsonschema-specifications, referencing, rpds-py)
- `backend/app/config.py` (+1 line)
- `docs/decisions.md` (+11 lines)

The pre-existing dirty `.superpowers/sdd/task-1-brief.md` was left unstaged.

## Self-review

- Diff reviewed via `git show`; matches brief verbatim.
- Pre-existing LSP diagnostic on `get_settings()` (missing required args) is
  unrelated to this change and unchanged.
- Concerns: none.
