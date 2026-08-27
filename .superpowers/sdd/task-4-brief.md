### Task 4: Discovery, registration, route mounting, startup wiring

**Files:**
- Create: `backend/app/plugins/discovery.py`
- Modify: `backend/app/main.py` (create_app signature, lifespan, include_router)
- Test: `backend/tests/test_plugins_discovery.py` (unit/integration), `backend/tests/test_plugins_startup.py` (lifespan wiring)

**Interfaces:**
- Consumes: `parse_manifest`, `load_plugin_class`, models `Plugin`.
- Produces:

```python
@dataclass
class Candidate:
    manifest: PluginManifest
    directory: Path
    instance: Any                     # instantiated plugin object
    core: bool                        # path prefix "core" under plugins_dir
    router: APIRouter | None          # from optional register_routes()

def discover(plugins_dir: Path) -> tuple[list[Candidate], list[str]]:
    # returns (accepted candidates, rejection reason strings); missing dir → ([], [])

async def register_candidates(session: AsyncSession,
                              candidates: Sequence[Candidate]) -> dict[str, int]:
    # upsert one Plugin row per candidate keyed by manifest id stored in the
    # `name` column; refreshes version + manifest JSONB; preserves enabled;
    # returns manifest id -> plugin row pk

def collect_router(candidate: Candidate) -> APIRouter | None:
    # calls instance.register_routes(router) when present; raises
    # PluginLoadError if any contributed route path would land on the
    # reserved sub-paths "/config" or "/data" (with or without trailing segments)

async def discover_and_mount(app: FastAPI) -> None:
    # orchestrates: scan app.state.plugins_dir → register via
    # app.state.db_session_factory → fill app.state.plugin_registry
    # ({manifest_id: instance}) → mount routers at prefix f"/plugins/{id}"
    # logs "plugins: N registered, M rejected"
```

Behavioral rules:
- Rejection reasons are collected and returned; nothing raises for bad plugins.
- Reserved-path check inspects every route in the contributed router: any path equal to `/config`, `/data` or starting with `/config/`, `/data/` ⇒ reject the whole candidate.
- Upsert-in-place: `SELECT Plugin WHERE name == manifest.id`; found → update `version`, `manifest`; else insert with `enabled = candidate.core`. The row's `enabled` value is never modified by registration.

**main.py wiring:**

1. `create_app(...)` gains keyword param `plugins_dir: Path | str | None = None`; store on state:

```python
    app.state.plugins_dir = (
        Path(plugins_dir)
        if plugins_dir is not None
        else (Path(settings.plugins_dir) if settings is not None else None)
    )
    app.state.plugin_registry: dict[str, Any] = {}
```

2. In lifespan, immediately before the scheduler block (`scheduler_service = getattr(...)` line):

```python
            if application.state.plugins_dir is not None:
                from .plugins.discovery import discover_and_mount

                await discover_and_mount(application)
```

3. With the other routers: `app.include_router(plugins_router)` (Task 6 adds the import; add it in Task 6 to keep this task's diff green — instead expose mounting purely via `discover_and_mount` here).

4. In the runner-construction block, create the shared registry dict BEFORE `default_steps` and pass it through (see Task 5's `default_steps` change): replace `steps = default_steps(fetcher..., load_registry())` with:

```python
        steps = default_steps(
            fetcher if fetcher is not None else HttpFetcher(),
            load_registry(),
            app.state.plugin_registry,
        )
```

To keep this task self-contained and green before Task 5 lands, make ONLY the `app.state.plugin_registry = {}` assignment now; defer the `default_steps` call-site change to Task 5.

Tests:
- Unit (tmp dirs): valid plugin discovered with correct core flag (`<tmp>/core/x` vs `<tmp>/x`); invalid manifest rejected with reason; loader failure rejected; reserved-route plugin rejected; empty/missing dir → no candidates.
- Integration (Postgres): register twice — second run updates version, preserves a manually-flipped `enabled`, keeps a single row; FK stability (a ModuleInstance referencing the row survives re-registration).
- Startup: with an injected `db_session_factory` + `plugins_dir` tmp fixture, run the lifespan via `httpx.ASGITransport(lifespan="on")` OR invoke the lifespan context manually (`async with app.router.lifespan_context(app):`) and assert rows exist and `app.state.plugin_registry` is filled. Prefer manual lifespan-context invocation — existing tests never trigger lifespan.

TDD per suite; commits: `feat: plugin discovery and DB registration` then wiring included in same commit (one commit for the task is fine: `feat: plugin discovery, registration, and startup wiring`).

---
