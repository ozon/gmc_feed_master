# Task 3 Report: Plugin Module Loader

**Status:** Complete
**Commit:** `b8a8de3` — `feat: plugin module loader with entry-point convention`
**Branch:** `m6-plugin-host` (worktree `.worktrees/m6-plugin-host`)

## What was built

- `backend/app/plugins/loader.py`
  - `class PluginLoadError(Exception)`
  - `def load_plugin_class(directory: Path, manifest: PluginManifest) -> Any`
  - Entry point resolution: `manifest.raw.get("entry_point")` as `"module:ClassName"`; default convention `plugin.py` / attribute `Plugin`.
  - Registers module under unique name `gmc_plugin_{manifest.id}` in `sys.modules` **before** exec.
  - On success the registration is retained; on any failure the entry is deleted before re-raising so a half-executed module cannot poison later loads.
- `backend/tests/test_plugins_loader.py` — 12 tests using real temp plugin dirs (`pathlib` + `tmp_path`).

## Failure modes → distinct `PluginLoadError` messages

1. Malformed entry point — non-string, wrong number of `:` parts, or empty module/class parts ("malformed entry_point ... expected 'module:ClassName'").
2. Module file missing — default and explicit entry-point paths ("module file not found: <path>").
3. Exec raises — wrapped with original exception text ("error executing module ...").
4. Attribute missing ("attribute 'X' not found in <path>").
5. Instantiation raises — wrapped ("error instantiating 'X' ...").
6. Result lacks callable `process` — covers both absent attr and non-callable attr ("does not provide a callable 'process' method").

## TDD evidence

- **RED:** wrote tests first; run produced `ImportError: ModuleNotFoundError: No module named 'app.plugins.loader'`.
- **GREEN:** implemented loader; `tests/test_plugins_loader.py`: **12 passed**.
- **Full suite:** `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q` → **417 passed** (405 prior + 12 new).

## Self-review

- All six failure modes covered with distinct, greppable messages: yes.
- sys.modules semantics per contract: unique pre-exec registration; no cleanup needed on success (kept); failures delete their entry (no poisoning). Two-plugins-different-ids test asserts independent loading and both registrations present on success.
- Exact interface names match brief: `PluginLoadError`, `load_plugin_class`.

## Concerns

None blocking. Note: success retains the `sys.modules` entry by design (per contract); a future registry that loads many plugins may want an unload hook.
