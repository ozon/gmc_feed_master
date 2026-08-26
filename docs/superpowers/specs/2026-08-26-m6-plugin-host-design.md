# M6 Design: Plugin Host

**Date:** 2026-08-26
**Status:** Approved
**Builds on:** M5 (commit `3d912b4` on `main`, incl. pytest-optimization)
**Implements:** spec §5.1–§5.4 (discovery, manifest, three-level model wiring, runtime contract), §5.10 (frontend integration backend half + contract tests), §8 (`/plugins*` endpoints)

> Numbering note: this is the project's sixth built milestone (M6) and
> corresponds to the AGENTS.md milestone-table row labeled "M5" (plugin host).
> The four core plugins are the next milestone (AGENTS.md row "M6") and are
> explicitly out of scope here.

## Scope

The host makes third-party product-processing code a first-class citizen:
scan `plugins/` at startup, validate manifests, register plugins in the
database, load their Python modules, execute enabled pipeline instances per
product inside `PluginStep`, expose activation/config/data APIs, and enforce
the contract through a reusable test suite — proven by a dummy third-party
plugin that passes without any core change.

**In scope:**
- `app/plugins/` package: manifest model + validation, discovery scanner,
  module loader/registry, DB registration (upsert), route mounting
- `RunContext` and the `PipelineModulePlugin` protocol
- `PluginStep` execution replacing the NoOp, consuming the M5 config bundle
- API: `GET /plugins`, `PUT /plugins/{id}/enabled`,
  `GET/PUT /plugins/{id}/config|data` (scope-aware, schema-validated)
- Contract test suite + committed dummy third-party plugin fixture
- Acceptance gate `test_m6_acceptance.py`

**Out of scope:**
- The four core plugins (next milestone)
- Frontend areas: plugin overview page, dynamic menu items, Vite build-time
  component discovery (M10); `manifest.frontend` is stored but unused here
- `migrate_config` semantics beyond accepting its optional presence in the
  protocol and contract suite
- Supplemental extension points (`quality_rule`, `input_reader`) beyond the
  registry being extensible by string value
- File-watching/hot reload of plugins (startup-only discovery)

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Registration identity | One row per manifest `id`; rediscovery upserts `name`/`version`/`manifest` in place, preserving `enabled` | Keeps `ModuleInstance.plugin_id` FKs stable across restarts; §4 reprocessing on version bumps already works because M5's resolver reads `plugin.version` live into `config_hash` |
| Entry point | Manifest MAY declare `"entry_point": "module:ClassName"`; default convention `<plugin_dir>/plugin.py` with a module-level `Plugin` attribute satisfying the protocol | Spec §5.2's manifest has no entry-point field — contract gap closed minimally; zero-config for simple plugins |
| Load failures | Import errors or missing/invalid `Plugin` attribute reject the plugin exactly like invalid manifests (logged, startup continues) | §5.1's "invalid → rejected, continue" applies to the whole candidate lifecycle |
| Reserved sub-paths | A plugin whose contributed routes land on `/plugins/{id}/config…` or `/data…` is rejected entirely at registration | Fail early with logged reason instead of silently skipping routes; contract suite independently asserts it (§5.4/§5.10) |
| Scope payload shape | One flat JSON document per (plugin, scope) for config and data | Matches §8's full-replace PUTs and M5's recorded flat-resolution decision |
| Schema validation | `jsonschema` library, exact-pinned | Declarative validation against manifest-provided schemas; 422 `{"errors": [...]}` shape per §8 |
| Bundle reuse | `StagingStep` stashes the resolved config bundle (and original snapshots) on `RunState`; `PluginStep` consumes them | Identical resolution feeding both `config_hash` and execution — no second query pass, no drift |
| Core-plugin detection | Path prefix `plugins/core/` ⇒ registers `enabled=true`; all others default `false` | §5.1 verbatim; no manifest flag needed |

## Discovery & registration

At startup (lifespan, before scheduler start): scan `<repo>/plugins/`
(tolerant of a missing directory; path overridable via `Settings.plugins_dir`
for tests). Each immediate subdirectory containing `plugin.json` is a
candidate. Manifest validation requires: `id` (string matching
`^[a-z][a-z0-9_]*$` — safe as a Python module suffix and URL path segment),
`name`,
`version`, `extension_point == "pipeline_module"` (unknown extension points
rejected for MVP while the field stays extensible by design), `config_schema`
and `data_schema` objects valid against the JSON-Schema meta-schema, and
`config_scope`/`data_scope` subsets of `{global, client, feed_source}`.
Failures log a reason per plugin and never abort startup.

Valid candidates are loaded (importlib, unique module name
`gmc_plugin_<id>`), then registered: upsert into `plugins`, mount any
contributed router under `/plugins/{id}/` after the reserved-path check, and
log a one-line summary (registered/rejected counts). Discovery is idempotent
across restarts.

## Runtime contract

```python
@dataclass(frozen=True)
class RunContext:
    client_id: int
    feed_source_id: int
    run_id: int
    logger: logging.Logger
    original_product: dict[str, Any]   # deep copy taken pre-pipeline


class PipelineModulePlugin(Protocol):
    def validate_config(self, config: dict) -> None: ...          # raise on invalid
    def process(self, product: dict, config: dict,
                data: dict, ctx: RunContext) -> dict | None: ...
    # optional: migrate_config(old_version, config) -> dict
    # optional: register_routes(router) -> None
```

`PluginStep` replaces its NoOp body: per product in `run_state.products`, walk
the active pipeline's instances in position order. For each instance, resolve
`(resolved_config, resolved_data)` from the stashed M5 bundle, build a fresh
`RunContext`, call `process`. Semantics per §5.4:

- Return `None` → product dropped from the pipeline; logged at INFO with
  plugin id and instance position.
- Exception → that product is marked errored (counted in the step's
  `failed_count`, logged with traceback to the run statistics/error fields);
  remaining products continue.
- Returned dict replaces the in-flight product for subsequent instances;
  survivors flow onward for QC/writer milestones.

Step statistics: `{"plugins": {"processed": n, "dropped": n, "errored": n}}`.

Plugins may create any registry-known attribute regardless of input schema
(virtual fields, §5.7) — nothing in the host restricts output keys; QC and the
writer own downstream validation.

## API

All session-authenticated, following the existing router patterns:

| Endpoint | Behavior |
|---|---|
| `GET /plugins` | Enabled plugins: `{id, name, version, enabled, manifest}` list |
| `PUT /plugins/{id}/enabled` | Body `{"enabled": bool}`; 404 unknown id |
| `GET /plugins/{id}/config?client_id=|feed_source_id=` | Stored payload for that scope; `{}` default; omitted params = global; 404 unknown plugin id. Readable regardless of `enabled` state — activation gates pipeline execution, not management |
| `PUT /plugins/{id}/config…` | Full replace; validated against `config_schema`; 422 `{"errors": [...]}` on violation; writes flow into `config_hash` via M5 |
| `GET/PUT /plugins/{id}/data…` | Same semantics against `data_schema` |

Scope-parameter validation: `client_id`/`feed_source_id` must reference
existing rows (404 otherwise); declaring both simultaneously → 422.

## Contract test suite

Reusable pytest suite in `backend/tests/contract/`, parametrized over a
plugins directory (default: the repo `plugins/`; fixtures use tmp dirs).
Per plugin checks:

1. Manifest passes the host validator.
2. `config_schema`/`data_schema` validate against the JSON-Schema meta-schema.
3. `process()` returns a dict or None for a representative minimal input.
4. `original_product` is not mutated by `process()` (deep-compare before/after).
5. `validate_config()` raises when required properties from `config_schema`
   are absent (only asserted when the schema declares required fields).
6. No contributed route resolves to a reserved sub-path.

An empty plugins directory skips gracefully. The committed dummy third-party
plugin lives in `tests/fixtures/example_plugin/` and is copied into a tmp
plugins dir by the acceptance test — proving §5.10's "no core change" done
criterion end-to-end.

## Testing strategy

**Unit:** manifest-validation matrix (each failure reason); loader (default
convention, explicit `entry_point`, import error, bad attribute);
upsert-in-place (version bump updates row, enabled preserved, FK stability);
reserved-route rejection; `PluginStep` success/drop/error flows with fake
plugins; endpoint shapes (404s, dual-scope 422, schema-violation 422 body).

**Integration (PostgreSQL):** startup discovery populates `plugins` and is
idempotent across restarts; toggle persists; config/data PUT→GET round-trips
per scope; full `PipelineRunner` run where a registered fake plugin transforms
one product and drops another, with statistics and drop logs asserted.

**Acceptance:** `test_m6_acceptance.py` — dummy third-party plugin passes the
contract suite and executes end-to-end through the runner (transform + drop +
error isolation) without core changes; full backend suite green; compileall
clean.
