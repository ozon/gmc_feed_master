# M6 Plugin Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the plugin host: startup discovery + manifest validation + registration of `plugins/` directories, the runtime contract executed inside `PluginStep` (with the processed-output store), scope-aware `/plugins*` APIs, and the §5.10 contract test suite proven by a dummy third-party plugin.

**Architecture:** New `app/plugins/` package with focused modules (`manifest`, `loader`, `discovery`, `runtime`, `contract`). Discovery runs in lifespan, upserts one `plugins` row per manifest id (stored in the `name` column), and fills a mutable registry dict that `PluginStep` reads at execution time — this decouples create_app-time step construction from lifespan-time discovery. Per-product outcomes persist to the new `staging_products.processed_data`/`excluded` columns (owner Option A).

**Tech Stack:** FastAPI, SQLAlchemy 2.0.43 async, Alembic, `jsonschema` (new exact-pinned runtime dep), importlib stdlib. No other new dependencies.

**Design doc:** `docs/superpowers/specs/2026-08-26-m6-plugin-host-design.md`

## Global Constraints

- Adding a plugin must never require core changes (spec §5) — the acceptance criterion is a dummy third-party plugin passing the contract suite and running end-to-end without touching `backend/app/`.
- Reserved sub-paths `config` and `data` under `/plugins/{id}/…`: a plugin contributing such routes is rejected entirely at registration (logged); the contract suite independently asserts it.
- `GET /plugins` returns ALL registered plugins (enabled + disabled); menu filtering is the frontend's job.
- Scope params on config/data endpoints must be declared in the manifest's `config_scope`/`data_scope` (422 otherwise), reference existing rows (404 otherwise), never both at once (422).
- `original_product` = THIS run's incoming mapped product, deep-copied before the first instance executes — never a stored snapshot.
- Plugin exception ⇒ that product's chain aborts, its staging row is NOT updated (last-known-good output preserved), product counted errored, run continues.
- Invalid manifest/load failure ⇒ plugin rejected, reason logged, startup continues. Never crash startup over one bad plugin.
- Exact pins: `jsonschema` added to main deps with `==` pin recorded in `docs/decisions.md`.
- Integration tests: `export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres`; suite runs parallel (`-n auto` is in addopts) — keep tests worker-safe (tmp dirs, unique ids).
- Worktree workflow: `.worktrees/m6-plugin-host`, branch `m6-plugin-host`.
- Match repo style: `from __future__ import annotations`, minimal comments.

---

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

### Task 2: Manifest parsing + validation

**Files:**
- Create: `backend/app/plugins/__init__.py`
- Create: `backend/app/plugins/manifest.py`
- Test: `backend/tests/test_plugins_manifest.py`

**Interfaces:**
- Produces:

```python
_ID_RE: re.Pattern                      # ^[a-z][a-z0-9_]*$
_ALLOWED_SCOPES: frozenset[str]         # {"global","client","feed_source"}
class ManifestError(Exception): ...     # .reason: str
@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    extension_point: str
    config_schema: dict[str, Any]
    data_schema: dict[str, Any]
    config_scope: tuple[str, ...]
    data_scope: tuple[str, ...]
    raw: dict[str, Any]                 # original manifest document
def parse_manifest(data: Any) -> PluginManifest   # raises ManifestError
```

Tasks 3+ consume exactly these names.

Validation rules (each violation → `ManifestError` with a specific reason string):
- document must be a JSON object
- required keys present: `id, name, version, extension_point, config_schema, data_schema`
- `id` matches `_ID_RE`; `name`/`version` non-empty strings
- `extension_point == "pipeline_module"` (anything else rejected for MVP)
- `config_schema`/`data_schema` are dicts AND valid against the JSON-Schema 2020-12 meta-schema (`jsonschema.Draft202012Validator.check_schema`, catching `jsonschema.SchemaError`)
- `config_scope`/`data_scope`: missing → defaults `(global,)`; a bare string → 1-tuple; a list/tuple → every element in `_ALLOWED_SCOPES`, at least one element

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_plugins_manifest.py` covering, at minimum: valid minimal manifest round-trips (defaults applied); each failure reason above (missing keys, bad id `"Bad-Id"`, wrong extension point `"quality_rule"`, non-dict schema, schema invalid against meta-schema (`{"type": "nope"}`), undeclared scope value, empty scope list, string→tuple normalization); `raw` preserves the input document.

- [ ] **Step 2: RED** — `cd backend && uv run pytest tests/test_plugins_manifest.py -q` fails on import.

- [ ] **Step 3: Implement** `backend/app/plugins/manifest.py` exactly per the interface above (empty `__init__.py` package marker alongside).

- [ ] **Step 4: GREEN** — same command passes.

- [ ] **Step 5: Commit** — `feat: plugin manifest parsing and validation`

---

### Task 3: Module loader

**Files:**
- Create: `backend/app/plugins/loader.py`
- Test: `backend/tests/test_plugins_loader.py`

**Interfaces:**
- Consumes: `PluginManifest`.
- Produces: `class PluginLoadError(Exception)`; `def load_plugin_class(directory: Path, manifest: PluginManifest) -> Any` — returns an instantiated plugin object.

Behavior:
- Explicit entry point: `manifest.raw.get("entry_point")` formatted `"module:ClassName"` → loads `<directory>/<module>.py` and gets `ClassName`.
- Default: `plugin.py` / attribute `Plugin`.
- Registers under unique module name `gmc_plugin_{manifest.id}` in `sys.modules` before exec.
- Failure modes → `PluginLoadError`: malformed entry_point, file missing, exec raises, attribute missing, instantiation raises, result lacks callable `process`.

Tests build real temp plugin dirs (write `plugin.py` files with `pathlib`), covering: default convention happy path; explicit entry point; each failure mode; two plugins with different ids loading independently (unique sys.modules names).

TDD: RED → implement → GREEN → commit `feat: plugin module loader with entry-point convention`.

---
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

### Task 5: Migration + runtime contract execution

**Files:**
- Create: `backend/alembic/versions/20260827_0001_m6_plugin_host.py`
- Modify: `backend/app/models/staging.py` (two columns)
- Create: `backend/app/plugins/runtime.py`
- Modify: `backend/app/pipeline/steps.py` (`RunState`, `StagingStep`, `PluginStep`, `default_steps`)
- Modify: `backend/app/staging/persistence.py` (`apply_plugin_outcomes`)
- Modify: `backend/app/main.py` (the deferred `default_steps` call-site change)
- Test: `backend/tests/test_m6_migration.py`, `backend/tests/test_plugin_step.py`

**Interfaces:**
- Consumes: M5's `apply_staging_delta(...) -> dict[str, int]` (pk_map), `resolve_config_bundle`.
- Produces:

```python
# runtime.py
@dataclass(frozen=True)
class RunContext:
    client_id: int
    feed_source_id: int
    run_id: int
    logger: logging.Logger
    original_product: dict[str, Any]

# persistence.py
@dataclass(frozen=True)
class PluginOutcome:
    product_id: str
    pk: int
    status: str                    # "processed" | "dropped"
    final_product: dict[str, Any] | None

async def apply_plugin_outcomes(
    session_factory, feed_source_id: int, ingestion_run_id: int,
    outcomes: Sequence[PluginOutcome], *, chunk_size: int = 1000,
) -> None
```

Migration revision `20260827_0001` (down_revision `20260826_0001`):

```python
def upgrade() -> None:
    op.add_column('staging_products', sa.Column('processed_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('staging_products', sa.Column('excluded', sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade() -> None:
    op.drop_column('staging_products', 'excluded')
    op.drop_column('staging_products', 'processed_data')
```

Model additions on `StagingProduct` (after `raw_data`):

```python
    processed_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
```
(import `false` from sqlalchemy alongside existing imports; extend the sqlalchemy import list.)

RunState gains three fields (after `source_fields`):

```python
    client_id: int | None = None
    config_bundle: dict[str, Any] = field(default_factory=dict)
    product_pks: dict[str, int] = field(default_factory=dict)
```

`StagingStep.execute` additions (after resolving `bundle`, before classify):

```python
        ctx.run_state.client_id = feed_source.client_id
        ctx.run_state.config_bundle = bundle
```

and capture the pk map: `pk_map = await apply_staging_delta(...)` followed by `ctx.run_state.product_pks = pk_map`.

`apply_plugin_outcomes` writes, chunked like its sibling (single transaction per chunk):
- `status == "processed"` → UPDATE by pk: `processed_data = final_product`, `excluded = False`, `ingestion_run_id`, `last_seen_at = now`
- `status == "dropped"` → UPDATE by pk: `processed_data = NULL`, `excluded = True`, `ingestion_run_id`
(`now = datetime.now(timezone.utc)` once per call.)

New `PluginStep` (replaces the `_NoOpStep` subclass entirely; constructor takes the shared registry dict):

```python
class PluginStep:
    name = "run_plugins"

    def __init__(self, registry: dict[str, Any] | None = None) -> None:
        self._registry = registry if registry is not None else {}

    async def execute(self, ctx: StepContext) -> StepResult:
        from copy import deepcopy

        bundle = ctx.run_state.config_bundle or {"instances": []}
        pks = ctx.run_state.product_pks
        survivors: list[dict[str, Any]] = []
        outcomes: list[PluginOutcome] = []
        processed = dropped = errored = 0

        for product in ctx.run_state.products:
            pid = product.get("id")
            current = product
            drop = error = False
            for instance in bundle.get("instances", []):
                plugin_obj = self._registry.get(instance["plugin"])
                if plugin_obj is None:
                    continue
                rctx = RunContext(
                    client_id=ctx.run_state.client_id or 0,
                    feed_source_id=ctx.feed_source_id,
                    run_id=ctx.ingestion_run_id,
                    logger=ctx.logger,
                    original_product=deepcopy(product),
                )
                try:
                    result = plugin_obj.process(
                        current,
                        instance["resolved_config"],
                        instance["resolved_data"],
                        rctx,
                    )
                except Exception as exc:
                    ctx.logger.warning(
                        "plugin %s errored on product %s: %s",
                        instance["plugin"], pid, exc,
                    )
                    errored += 1
                    error = True
                    break
                if result is None:
                    drop = True
                    break
                current = result
            if error:
                continue
            pk = pks.get(pid) if isinstance(pid, str) else None
            if drop:
                dropped += 1
                if pk is not None:
                    outcomes.append(PluginOutcome(pid, pk, "dropped", None))
                continue
            processed += 1
            survivors.append(current)
            if pk is not None:
                outcomes.append(PluginOutcome(str(pid), pk, "processed", current))

        await apply_plugin_outcomes(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            outcomes,
        )
        ctx.run_state.products = survivors
        return StepResult(
            processed_count=len(survivors),
            failed_count=errored,
            statistics={
                "plugins": {
                    "processed": processed,
                    "dropped": dropped,
                    "errored": errored,
                }
            },
        )
```

`default_steps` gains an optional third parameter and passes it through:

```python
def default_steps(
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any] | None = None,
) -> tuple[PipelineStep, ...]:
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(plugin_registry),
        QualityCheckStep(),
        ExportStep(),
    )
```

Apply the deferred main.py change (pass `app.state.plugin_registry`).

Semantics locked by the design (assert these in tests):
- Survivor of all instances → `processed_data` = final dict, `excluded = False`.
- Any None → chain aborts for that product, `processed_data = NULL`, `excluded = True` (reversible next passing run).
- Exception → chain aborts, NO staging write for that product, counted errored.
- `original_product` equals a deep copy of the product as it entered THIS step, even after earlier instances mutate `current` (test mutates in first instance, asserts `rctx.original_product` unchanged in second).
- Missing registry entry → instance skipped silently for that product (host has no registered plugin; logged skip acceptable).
- Products whose id lacks a staged pk still flow through but get no outcome write.

Testing:
- Migration test mirrors `test_m5_migration.py` (columns present head, absent at `20260826_0001`).
- Unit `test_plugin_step.py`: fake session-free? No — outcomes need DB; use the isolated-database pattern from `test_staging_step.py` (seed client/feed source/run, stage via `StagingStep` first, then run `PluginStep` with fake plugin objects). Cover: transform+persist, drop+persist-clear, exception leaves row untouched + failed_count, multi-instance ordering, original_product immutability, statistics shape, registry-miss skip.
- Full suite serial `-n0`: 366 passed + new tests (M5 acceptance asserts `captured == []` semantics stay intact because registry defaults empty → PluginStep is pass-through when nothing registered; verify `test_m3/m4/m5_acceptance` remain green).

Commits: `feat: processed-output store migration` (migration+models+its test), then `feat: PluginStep executes registered pipeline plugins` (runtime+persistence+wiring+tests).

---


### Task 6: Plugin API endpoints

**Files:**
- Create: `backend/app/routes/plugins.py`
- Create: `backend/app/schemas/plugins.py`
- Modify: `backend/app/routes/__init__.py` (export `plugins_router`), `backend/app/main.py` (`include_router(plugins_router)` + import)
- Test: `backend/tests/test_plugins_api.py`

**Interfaces:**
- Consumes: models `Plugin`, `PluginConfig`, `PluginData`, `Client`, `FeedSource`; `require_user`; `get_db_session`; `jsonschema`.
- Produces: `plugins_router` with:

| Route | Semantics |
|---|---|
| `GET /plugins` | ALL rows → `[{"id": <name column>, "name": manifest["name"], "version", "enabled", "manifest"}]` |
| `PUT /plugins/{plugin_id}/enabled` | Body `{"enabled": bool}`; 404 unknown; persists |
| `GET /plugins/{plugin_id}/config` | Query `client_id: int | None`, `feed_source_id: int | None`; returns stored flat payload for that scope or `{}` |
| `PUT /plugins/{plugin_id}/config` | Full replace after validation; 200 → `{"status": "ok"}` |
| `GET/PUT /plugins/{plugin_id}/data` | Same against `data_schema` |

Shared resolution helper (in the router module):

```python
async def _resolve_target(
    plugin_id: str,
    client_id: int | None,
    feed_source_id: int | None,
    db_session: AsyncSession,
    scope_kind: str,                     # "config_scope" | "data_scope"
) -> tuple[Plugin, str, int | None, int | None]:
```

Validation order (each its own status code):
1. `_require_db` → 503 when no session (existing pattern).
2. Plugin row by `name == plugin_id` → 404.
3. Both scope params present → 422 `{"errors": ["pass at most one of client_id, feed_source_id"]}` (JSONResponse, matching §8's error shape).
4. Requested scope must be in the manifest's declared `config_scope`/`data_scope` respectively → else 422 `{"errors": ["scope not declared for this plugin"]}`. Global (no params) is always allowed.
5. Ownership existence: `client_id` → `session.get(Client, ...)` else 404; same for feed source.

Storage convention (realizes M5's flat one-payload-per-scope decision on the keyed tables): host reads/writes exactly one row per (plugin, scope-owner) using `key = "default"`. GET: fetch row(s) for that owner, return first payload or `{}`. PUT: delete existing rows for that (plugin_id, scope, owner) then insert one with the validated payload — inside one transaction.

Payload validation: `jsonschema.validate(payload, schema)` catches `jsonschema.ValidationError` and `jsonschema.SchemaError` → 422 `{"errors": [<message>]}`.

Schemas file:

```python
class EnabledPut(BaseModel):
    enabled: bool
```

Auth: every route takes `_user: str = Depends(require_user)` and `db_session: AsyncSession | None = Depends(get_db_session)`.

**Tests** (mirror `test_field_mapping_api.py` patterns: engine from `isolated_database_url`, `create_app(settings=..., session_store=InMemorySessionStore..., db_session_factory=factory)`, login via `/auth/login`): list-all incl. disabled; toggle round-trip + 404; config PUT/GET per scope incl. global default `{}`; undeclared-scope 422; both-scopes 422; unknown client/feed-source 404; schema-violation PUT → 422 with `errors` key; data endpoints mirror one happy path + violation.

TDD; commit `feat: plugin management API endpoints`.

---

### Task 7: Contract checker + dummy fixture

**Files:**
- Create: `backend/app/plugins/contract.py`
- Create: `backend/tests/fixtures/example_plugin/plugin.json`
- Create: `backend/tests/fixtures/example_plugin/plugin.py`
- Create: `backend/tests/test_plugin_contract.py`

**Interfaces:**
- Consumes: `Candidate`, `discover`, `jsonschema`.
- Produces: `def contract_violations(candidate: Candidate) -> list[str]` — pure function returning human-readable violations (empty list = pass).

Checks implemented:
1. Meta-schema validity of `manifest.config_schema`/`data_schema` (`Draft202012Validator.check_schema`).
2. `process()` honors dict|None: call with `product={"id": "contract-check"}, config={}, data={}, ctx=None-tolerant` — build a real minimal `RunContext(client_id=0, feed_source_id=0, run_id=0, logger=logging.getLogger("contract"), original_product={...copy})`; any exception that is NOT a deliberate schema rejection counts as a violation unless it's raised for missing required config (plugins may require config to operate — treat `Exception` mentioning required keys as acceptable? NO: deterministic rule — if `validate_config({})` raises, skip the process-call checks 2–4 with reason "" (they are config-gated); otherwise they must pass).
3. `original_product` unmutated: deep-compare before/after the `process()` call.
4. `validate_config()` rejects missing required properties: for each name in `config_schema.get("required", [])`, assert `validate_config(payload_without_that_name)` raises.
5. Reserved sub-paths: inspect candidate router (via `collect_router`) — any path `/config…` or `/data…` is a violation.

Fixture `plugin.json`:

```json
{
  "id": "example_upper",
  "name": "Example Upper",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "example:UpperPlugin",
  "config_scope": ["global", "client"],
  "data_scope": [],
  "config_schema": {
    "type": "object",
    "properties": {"suffix": {"type": "string"}},
    "required": ["suffix"]
  },
  "data_schema": {"type": "object"}
}
```

Note `"data_scope": []` exercises the empty-declaration edge (all data access then 422s). Fixture `plugin.py`:

```python
class UpperPlugin:
    def validate_config(self, config):
        if not isinstance(config, dict) or "suffix" not in config:
            raise ValueError("suffix is required")

    def process(self, product, config, data, ctx):
        title = product.get("title")
        if product.get("id") == "drop-me":
            return None
        if isinstance(title, str):
            product["title"] = title.upper()
        product["title_suffix"] = config["suffix"]
        return product
```

Test wrapper `test_plugin_contract.py`: discover over `tests/fixtures` (a directory containing only `example_plugin` at top level — copy the fixture dir into `tmp_path` first so `discover()` sees exactly one candidate), assert `contract_violations(candidate) == []`; plus negative tests: mutate a copy of the fixture manifest to break each check (bad meta-schema, process returning `"str"`, mutating original_product, non-raising validate_config despite required, reserved-route contribution) and assert exactly one targeted violation.

TDD; commit `feat: plugin contract checker and example fixture`.

---

### Task 8: M6 acceptance gate

**Files:**
- Create: `backend/tests/test_m6_acceptance.py`
- Modify: `docs/decisions.md` (final verification entry)

**Interfaces:**
- Consumes: everything above; `discover_and_mount`, `contract_violations`, the fixture plugin, `PipelineRunner` with real steps.

Scenarios (each a test, following the M4/M5 acceptance patterns — engine/factory from `isolated_database_url`, manual lifespan-context invocation for discovery):

1. `test_dummy_plugin_passes_contract_without_core_changes` — copy `tests/fixtures/example_plugin` into a tmp plugins dir; `create_app(settings=..., db_session_factory=factory, plugins_dir=tmp)`; run lifespan context; assert one registered row (`enabled=False`, third-party default) and `contract_violations` empty.
2. `test_discovery_is_idempotent_across_restarts` — run discovery twice; single row; version updated when fixture version bumps in a copied manifest; `enabled=True` (manually flipped between runs) preserved.
3. `test_end_to_end_execution_through_runner` — seed client/feed source/run; stage two products via `IngestStep+MappingStep+StagingStep`; register the dummy instance in a registry dict passed through `default_steps(...)`; active pipeline seeded with a `ModuleInstance` pointing at the registered Plugin row; runner executes: product A transformed (staging row `processed_data` written, `excluded=False`, title uppercased + suffix), product B named `"drop-me"` → `processed_data NULL`, `excluded=True`; run statistics contain `plugins.processed == 1, dropped == 1`.
4. `test_error_isolation_preserves_last_known_good` — third product whose plugin raises for it specifically: staging row untouched from its previous state (seed a pre-existing `processed_data` value first), counted in `failed_count`/`errored`, run status still success.
5. `test_toggle_and_config_round_trip_via_api` — login → `GET /plugins` shows the disabled plugin → `PUT enabled` true → `PUT /plugins/example_upper/config?client_id=...` with valid payload → GET returns it; undeclared `feed_source_id` scope → 422.
6. `test_full_suite_serial_and_parallel_green` is the meta-gate: full backend suite under `-n0` and default `-n auto` both green; compileall clean; `git diff --check` clean.

Record an `### M6 final verification` entry in `docs/decisions.md` following the M1/M2 template: milestone complete statement, test counts, resolved dependency versions (jsonschema pin), deviations.

Commit: `feat: M6 acceptance gate — plugin host verified`.

---

## Self-Review Checklist (completed during planning)

- Spec coverage: §5.1 discovery/validation/registration + core-default-enabled (Tasks 4), §5.2 manifest incl. entry-point gap (Task 2), §5.3 wiring via existing scopes + API declaration checks (Task 6), §5.4 runtime contract incl. RunContext/original_product/drop/error semantics (Task 5), §5.10 contract suite + no-core-change proof (Tasks 7–8), §8 endpoints all present (Task 6), owner Option A processed store incl. migration + exception semantics (Task 5), GET /plugins all-plugins correction (Task 6).
- Placeholder scan: none — every task has concrete code, rules, or exact edit instructions; Task 2/3 tests are specified as enumerated case lists with exact inputs where values matter.
- Type consistency: `Candidate`, `RunContext`, `PluginOutcome`, `contract_violations(candidate)`, `PluginStep(registry)` names identical across definition and consumer tasks; `default_steps(fetcher, registry, plugin_registry=None)` matches main.py call-site change in Task 5.
- Ordering: Task 4 defers the `default_steps` call-site change to Task 5 to keep every commit green; Task 6's router import lands with the endpoints themselves.
