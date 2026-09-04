# Backend Plugin System

## Manifest (`plugin.json`)

```json
{
  "id": "labelizer",
  "name": "Labelizer",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "plugin:LabelizerPlugin",
  "config_schema": { ... },
  "config_scope": ["global", "client"],
  "data_schema": { ... },
  "data_scope": "client",
  "frontend": {
    "menu_item": "Labelizer",
    "icon": "tag",
    "component": "Editor.tsx",
    "uischema": { ... }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier, `^[a-z][a-z0-9_]*$` |
| `name` | Yes | Display name |
| `version` | Yes | Semantic version |
| `extension_point` | Yes | MVP: only `pipeline_module` |
| `entry_point` | Yes | `module:ClassName` (Python) |
| `config_schema` | Yes | JSON Schema 2020-12 (Pydantic v2 output) |
| `config_scope` | No | Subset of `["global", "client", "feed_source"]`, default `["global"]` |
| `data_schema` | Yes | JSON Schema 2020-12 |
| `data_scope` | No | Subset of `["global", "client", "feed_source"]`, default `["global"]` |
| `frontend` | No | UI integration: `menu_item`, `icon`, optional `component` (TSX path), optional `uischema` |

## Discovery & Registration (`app/plugins/discovery.py`)

1. **Scan** `plugins/` directory at startup
2. **Core plugins**: `plugins/core/` (enabled by default)
3. **Third-party**: `plugins/<id>/` (disabled by default)
4. **Validate** manifest via `parse_manifest()` (checks schema validity, scope values, required fields)
5. **Load** Python class via `load_plugin_class()` (imports `entry_point`)
6. **Collect** optional router via `register_routes()` (validates no reserved paths)
7. **Register** in `Plugin` table (upsert by `name` + `version`)
8. **Mount** router at `/plugins/{id}/` if present
9. **Store** instance in `app.state.plugin_registry[manifest.id]` for pipeline runner

Invalid manifest → rejected, logged, startup continues.

## Three-Tier Scope Merge (`app/staging/config_resolver.py`)

### Resolution Order
```
global → client → feed_source  (per-key dict merge)
```

### Algorithm
```python
def merge_scopes(global_payload, client_payload, feed_source_payload):
    resolved = dict(global_payload)
    if client_payload:     resolved = _merge_dicts(resolved, client_payload)
    if feed_source_payload: resolved = _merge_dicts(resolved, feed_source_payload)
    return resolved

def _merge_dicts(base, overlay):
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value  # overlay wins wholesale
    return merged
```

### Per-Plugin Scope Declaration
| Plugin | `config_scope` | `data_scope` | Rationale |
|--------|----------------|--------------|-----------|
| Labelizer | `["global", "client"]` | `["client"]` | Dimensions shared across markets; per-market out of MVP |
| Category | `["global", "client"]` | `["client"]` | Taxonomy shared; per-market out of MVP |
| Rules | `["global", "client", "feed_source"]` | `["global", "client", "feed_source"]` | Full flexibility |
| Filter | `["global", "client", "feed_source"]` | `["global", "client", "feed_source"]` | Full flexibility |

**Key behavior**: Generic merge replaces non-dict values per key. Plugins needing finer-grained list merging (e.g., Labelizer dimension ordering) implement custom logic in their `process()` or config resolution.

## Runtime Contract (`app/plugins/runtime.py`)

```python
@dataclass(frozen=True)
class RunContext:
    client_id: int
    feed_source_id: int
    run_id: int
    logger: logging.Logger
    original_product: dict[str, Any]  # read-only deep copy
```

### Plugin Class Methods
```python
class PipelineModulePlugin(Protocol):
    def validate_config(self, config: dict) -> None: ...
    def process(self, product: dict, config: dict, data: dict, ctx: RunContext) -> dict | None: ...
    def migrate_config(self, old_version: str, config: dict) -> dict: ...  # optional
    def register_routes(self, router: APIRouter) -> None: ...  # optional
```

### `process()` Rules
- **Input `product`**: Mutable current state (post-previous-plugins)
- **`config`**: Resolved three-tier merge for this feed source
- **`data`**: Resolved three-tier merge for this feed source
- **`ctx.original_product`**: Read-only snapshot (post-mapping, pre-pipeline). **Never mutate.**
- **Return `dict`**: Modified product continues pipeline
- **Return `None`**: Drop product (logged with `plugin_id` + reason)
- **Raise exception**: Product marked errored, run continues, logged to `IngestionRun`

### `prepare_run(config, data, ctx) -> state` (optional)
Called once per plugin instance per pipeline run, before the first product. Plugins may return any run-scoped state (parsed ID sets, compiled templates). The state is passed to every `process(product, config, data, ctx, state=...)` call of that instance for the run, but only if `process` declares a `state` parameter. Plugins without `prepare_run` are unaffected. Use this instead of caching per-run data on `self` — plugin instances are singletons and runs of different feed sources execute concurrently.

### Virtual Fields
Plugins may create **any registry-known attribute** on the product, regardless of input feed schema. Path grammar (§5.7 spec) addresses nested/repeated fields.

## Pipeline Integration (`app/pipeline/steps.py:PluginStep`)

1. Load `config_bundle` via `resolve_config_bundle()` (includes ordered instances + resolved config/data)
2. For each product in `delta.enqueue`:
   - `original = deepcopy(product)`
   - For each `instance` in pipeline order:
     - Get plugin instance from `app.state.plugin_registry`
     - Call `plugin.process(current, instance.resolved_config, instance.resolved_data, rctx)`
     - If `None` → drop, break
     - If exception → error, break
     - Else `current = result`
   - Persist outcome via `apply_plugin_outcomes()`

## Contract Test Suite (`app/plugins/contract.py`)

Run: `uv run pytest backend/tests/test_plugin_contract.py`

Checks:
1. **Meta-schema validity** — `config_schema` & `data_schema` are valid JSON Schema 2020-12
2. **`process()` contract** — returns `dict` or `None`; no exception; **does not mutate `original_product`**
3. **`validate_config()`** — rejects missing required properties (if any declared)
4. **Reserved routes** — no plugin route under `/config` or `/data` prefixes

## Frontend Integration

### Manifest → Frontend
- `GET /plugins` returns enabled plugins' manifests
- Frontend builds menu entries dynamically from `manifest.frontend.menu_item` + `icon`

### UI Rendering
- **Default**: Auto-rendered from `config_schema` / `data_schema` via Mantine-themed `JsonSchemaForm` (RJSF)
- **Custom**: `manifest.frontend.component` path → build-time Vite discovery → imported as React component

### Build-Time Discovery
- Vite scans `plugins/*/frontend/` at build time
- Components registered in single build pipeline (no runtime module federation)
- Contract test asserts component path exists and exports valid React component

## Core Plugins (MVP Rudimentary)

| Plugin | Manifest ID | Scope | MVP Scope |
|--------|-------------|-------|-----------|
| Labelizer | `labelizer` | `config: [global, client]`, `data: [client]` | `id_in_list` condition only |
| Rules | `rules` | `config: [global, client, feed_source]`, `data: [global, client, feed_source]` | Ordered rule list (IF/THEN AST): text/numeric/regex conditions; set/replace/append/prepend/remove/clear actions; master flag = UI pinning; `plugins/core/rules/` |
| Category | `category` | `config: [global, client]`, `data: [client]` | Rules + manual assignments + taxonomy autocomplete |
| Filter | `filter` | `config: [global, client, feed_source]`, `data: [global, client, feed_source]` | Single conjunctive condition set (6 scalar ops); drops non-matching products; live preview endpoint; `plugins/core/filter/` |
| Custom Labels | `custom_labels` | `config: [global, client]`, `data: [client, feed_source]` | Bulk-ID slot rules: `slotRules` (global/client) config; `slotIds` keyed by rule id (client/feed_source) data; matching = registry attribute path membership in a trimmed/deduped set; first-match-wins per slot; empty token skips rule; per-slot fallback from first rule when rule matched but template empty; `plugins/core/custom_labels/` |

### Rules Plugin (`plugins/core/rules/`)

Config document: `{"rules": [{id, name, isMasterRule, isActive, when, then}]}`.
- `when`: condition AST — `all` | `and`/`or` groups | leaf ops
  (`equals, contains, starts_with, ends_with, regex, exists, empty, gt, lt, gte, lte, between`);
  `caseSensitive` defaults `true`. Missing `arg` on a numeric op (`gt/lt/gte/lte/between`)
  raises `ConditionError` at evaluation; a non-numeric field *value* evaluates `False`.
- `then`: ordered actions (`set, replace, append, prepend, remove, clear`);
  `replace` supports regex mode when `find` starts with `/pattern/` (trailing slash
  stripped, JS-style; capture groups via `$1`, backslashes in the replacement are
  literal); empty-string `find` is rejected by `validate_config`.
- `isMasterRule` is UI-only (badge + list pinning); engine order = array order.
- `isActive: false` skips the rule at run time.
- `validate_config` strictly validates the document on save (`{}` and `{"rules": []}`
  pass; unknown ops, missing required keys, empty `and`/`or` children and missing
  numeric args raise `ValueError`); `process` evaluates conditions against the current
  product state (post-previous-plugins) and applies actions in order (copy-on-write);
  never mutates `ctx.original_product`.

### Filter Plugin (`plugins/core/filter/`)

Config document: `{"isActive": true, "conditions": [{field, op, arg?, caseSensitive?}]}`.
- Ops: `equals`, `not_equals`, `contains`, `not_contains` (text, `caseSensitive` default
  `true`), `exists`, `empty`. Conjunctive — all conditions must match.
- Missing field: `equals`/`contains` → false; `not_equals`/`not_contains` → true;
  `exists` → false; `empty` → true.
- `isActive: false` → pass-through; empty `conditions` → pass-all.
- Non-matching product → `process()` returns `None` → dropped (`excluded=true`).
- `POST /plugins/filter/preview` — `{feed_source_id, conditions}` →
  `{total, pass, fail}` against active, non-excluded staged products (canonical
  mapped state; approximation when mutating modules run before the filter).

### Custom Labels Plugin (`plugins/core/custom_labels/`)

Config document: `{"slotRules": [{id, name, isActive, targetSlot, matchField, valueTemplate, fallbackTemplate?}]}`.
- `targetSlot`: one of `custom_label_0` through `custom_label_4`.
- `matchField`: any registry-known attribute path (e.g. `id`, `brand`, `price.value`).
- `valueTemplate`: compiled template with `{attr}` / `{attr.subfield}` tokens.
- First-match-wins per slot; empty token in a matched rule skips to the next rule.
- `fallbackTemplate`: applied only when a rule matched but the template resolved
  empty (token skip). One fallback per slot (first rule declares it).
- `isActive: false` skips the rule.
- Data document: `{"slotIds": {"<rule_id>": "<newline/comma-separated IDs>"}}`.
- `validate_config` strictly validates on save (empty config passes; unknown
  targetSlot, empty matchField/valueTemplate, non-registry matchField, unknown
  token paths, duplicate ids, duplicate fallback per slot raise `ValueError`).

## Example Plugin (`plugins/example_upper/`)

**plugin.json:**
```json
{
  "id": "example_upper",
  "name": "Example Upper",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "plugin:UpperPlugin",
  "config_scope": ["global", "client"],
  "data_scope": ["global"],
  "config_schema": {"type": "object", "properties": {"suffix": {"type": "string"}}, "required": ["suffix"]},
  "data_schema": {"type": "object"},
  "frontend": {"menu_item": "Example Upper", "icon": "letter-e"}
}
```

**plugin.py:**
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

## Key Files
- `app/plugins/manifest.py` — `parse_manifest()`, `PluginManifest` dataclass
- `app/plugins/discovery.py` — `discover()`, `discover_and_mount()`, `collect_router()`
- `app/plugins/loader.py` — `load_plugin_class()` dynamic import
- `app/plugins/runtime.py` — `RunContext` dataclass
- `app/plugins/contract.py` — `contract_violations()` checker
- `app/staging/config_resolver.py` — `merge_scopes()`, `resolve_config_bundle()`
- `backend/tests/test_plugin_contract.py` — Contract test suite