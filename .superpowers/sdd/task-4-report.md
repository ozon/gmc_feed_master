# Task 4 Report: Discovery, registration, route mounting, startup wiring

**Status:** COMPLETE
**Commit:** `0c1fbb3` — `feat: plugin discovery, registration, and startup wiring`
**Branch:** `m6-plugin-host` (worktree `.worktrees/m6-plugin-host`)

## What was built

- `backend/app/plugins/discovery.py`:
  - `Candidate` dataclass (manifest, directory, instance, core, router).
  - `discover(plugins_dir)` → scans immediate subdirs containing `plugin.json`; `core/` prefix subdir ⇒ `core=True`; missing dir ⇒ `([], [])`; manifest/loader/reserved-route failures become rejection reason strings (nothing raises). Reserved paths: any contributed route equal to `/config`|`/data` or starting with `/config/`|`/data/` rejects the whole candidate.
  - `register_candidates(session, candidates)` → upsert-in-place: SELECT by `name == manifest.id`; found → update `version` + `manifest`, **never touches `enabled`**; else insert with `enabled = candidate.core`. Returns `{manifest_id: pk}`.
  - `collect_router(candidate)` → calls `instance.register_routes(router)` when present; raises `PluginLoadError` on reserved-path collision.
  - `discover_and_mount(app)` → scan → register via `app.state.db_session_factory` (single transaction) → fill `app.state.plugin_registry` → mount routers at `/plugins/{id}` → logs `"plugins: N registered, M rejected"` + per-rejection warnings.
- `backend/app/main.py`: `create_app(..., plugins_dir: Path | str | None = None)`; sets `app.state.plugins_dir` (param > `settings.plugins_dir` > None) and `app.state.plugin_registry = {}`; lifespan calls `discover_and_mount(application)` immediately before the scheduler block. **`default_steps` call-site untouched (deferred to Task 5 as instructed).**
- Migration `20260826_0002_m6_plugin_enabled.py` + `Plugin.enabled` column (see Plan Gap below).

## TDD evidence

- RED: both new test files failed with `ModuleNotFoundError: No module named 'app.plugins.discovery'` before implementation; LSP flagged unknown `Plugin.enabled`.
- GREEN: 20 new tests pass.
  - `test_plugins_discovery.py` (17): unit tmp-dir discovery (core flag via `<tmp>/core/x`, invalid manifest, loader failure, dir without `plugin.json` skipped, reserved-route parametrized over `/config`, `/data`, `/config/thing`, `/data/x/y`, near-miss paths `/configs`|`/database` accepted, missing-dir tolerance) + Postgres integration (re-registration updates version/preserves manually-flipped enabled/single row, insert defaults from core flag, ModuleInstance FK survives re-registration).
  - `test_plugins_startup.py` (3): manual `async with app.router.lifespan_context(app):` with injected factory+plugins_dir asserts rows persisted (`enabled=False` for third-party), registry filled, route mounted at `/plugins/example_upper/status`; state fallbacks for plugins_dir.
- Full suite: **437 passed** (417 baseline + 20 new), `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres`.

## Plan gap found & resolved (IMPORTANT for Task 5)

The brief requires an `enabled` column on `plugins` ("insert with enabled = candidate.core", "preserves a manually-flipped enabled"), and design spec §"GET /plugins payload" requires it too — but **no model column or migration existed anywhere in the plan** (Task 5's migration only covers staging columns). I added:

- `Plugin.enabled: Mapped[bool]` (nullable=False, default False, server_default false()) in `backend/app/models/plugin.py`
- Alembic revision **`20260826_0002`** (down_revision `20260826_0001`) adding the column.

⚠️ **Task 5 must set its migration's `down_revision = '20260826_0002'`** (its brief says `'20260826_0001'`) to avoid two heads.

## Self-review checklist

- Reserved-path rejection covers `/config`, `/data`, `/config/...`, `/data/...` ✓ (parametrized)
- Enabled preserved on re-registration ✓ (integration test flips to True across runs)
- Core flag from path prefix ✓
- Missing-dir tolerance ✓
- No `default_steps` change leaked ✓ (verified diff)

## Notes

- Test route introspection needed care: this FastAPI wraps `include_router` results in lazy `_IncludedRouter` objects (`path=None`); startup test walks `original_router.routes` + `include_context.prefix`.
- Unrelated modified files under `.superpowers/sdd/` were left out of the commit.
