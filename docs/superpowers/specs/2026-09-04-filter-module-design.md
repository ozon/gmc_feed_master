# Filter Module — Core Plugin `filter` Design

**Date:** 2026-09-04
**Status:** Approved (brainstorming session 2026-09-04)
**Depends on:** plugin system (`backend/docs/plugins.md`), rules module reference implementation (`plugins/core/rules/`, `frontend/src/features/rules/`), processed-stage products view (`backend/app/routes/products.py`)

## Purpose

Second core pipeline module: drop products that fail a conjunctive condition set.
Where Rules mutates product data, Filter decides **whether a product continues**
through the pipeline. Dropped products surface as `excluded=true` in the
processed products view.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Condition model | Docs-minimal: flat conjunctive list, 6 scalar ops, no groups/numerics/regex |
| UI | Custom component via the proven stub seam (not auto-form) |
| Granularity | Single filter set per feed source (no named sets, no list column) |
| Preview | Live pass-count via `POST /plugins/filter/preview` against staged data |

## 1. Architecture

```
plugins/core/filter/
├── plugin.json          # id 'filter'; scopes all three tiers; frontend.component stub
├── plugin.py            # FilterPlugin: validate_config() + process() + register_routes()
└── frontend/
    └── component.tsx    # one-line re-export: export { default } from '../../../../frontend/src/features/filter/FilterUI'
```

- **Extension point:** `pipeline_module`; core plugin → auto-enabled.
- **Scopes:** `config_scope = data_scope = ["global", "client", "feed_source"]` (docs-reserved row).
  MVP UI writes only the `feed_source` tier.
- **Storage:** `plugin_configs` JSONB, three-tier merge at run time. No migrations.
- **Pipeline position:** added on the Pipeline page like any module; order matters
  (filter after rules sees mutated values; filter before rules sees mapped values).

### Config Document

```jsonc
{
  "isActive": true,
  "conditions": [
    { "field": "brand", "op": "equals", "arg": "Acme", "caseSensitive": false },
    { "field": "description", "op": "not_contains", "arg": "refurbished" },
    { "field": "image_link", "op": "exists" }
  ]
}
```

### Operators

| Op | Arg | Semantics |
|---|---|---|
| `equals` / `not_equals` | string | string equality; `caseSensitive` flag (default `true`) |
| `contains` / `not_contains` | string | substring match; `caseSensitive` flag |
| `exists` | — | key present and value not null |
| `empty` | — | missing, null, or empty string |

- Text ops coerce non-string values via `str()` (same convention as Rules).
- Missing field: `equals`/`contains` → false; `not_equals`/`not_contains` → **true** (safe blacklist default).
- `isActive: false` → pass-through (config preserved, filter off).
- Empty `conditions` list → pass-all.

### Engine

`process(product, config, data, ctx)`:
1. `isActive` false or conditions empty → return `product` unchanged.
2. Evaluate each condition conjunctively against the current product (post-previous-modules).
3. All match → return `product` unchanged; any fails → return `None` (drop).

Self-contained evaluator (~60 lines) — deliberately not imported from the rules
plugin; plugins stay independently distributable, and the conjunctive scalar
subset is trivial. Never touches `ctx.original_product`. Unknown op at run time
(hand-edited config) → `FilterError(ValueError)` → product errored, run continues.

## 2. UI

`frontend/src/features/filter/FilterUI.tsx` + one-line stub. Single-pane editor:

- **Header:** `isActive` Switch; dirty-guard + `useBlocker` + Save/Reset (identical
  save flow to RulesUI: local state, `lastConfigRef` rehydration, `useSavePluginConfig`).
- **Condition rows:** `[Field Select][Operator Select][Value Input]`; value input
  hidden for `exists`/`empty`; `caseSensitive` Switch for text ops; per-row trash icon;
  "+ Add condition" button. Field options from `useFeedSourceFields`.
- **Preview card:** debounced (~400 ms) on any edit → `POST /plugins/filter/preview`
  body `{feed_source_id, conditions}` → renders "**137 of 308 products pass**".
  Incomplete rows (empty field/missing arg) show an "incomplete" hint instead of a count.
- **Nav:** feed-scoped, same feed-priority logic as rules (manifest scopes include `feed_source`).
- **i18n:** new `filter` namespace, en + de.

### Preview endpoint (`register_routes` on the plugin, mounted at `/plugins/filter/`)

`POST /plugins/filter/preview` (path `/preview` — not a reserved prefix):

```jsonc
// request
{ "feed_source_id": 13, "conditions": [ { "field": "brand", "op": "equals", "arg": "Acme" } ] }
// response
{ "total": 308, "pass": 137, "fail": 171 }
```

- Evaluates the condition set against every **active, non-excluded** staged product's
  canonical (mapped) state in-memory, using the same evaluator as `process()`.
- Accuracy note (documented): preview reflects the canonical product — identical to
  run-time input only when the filter is the first/only module; after a mutating
  module it is an approximation.
- Errors: unknown feed source → 404; invalid conditions → 422 with the message;
  unauthenticated → 401 (inherits `require_user` via the app).

## 3. Errors, Edge Cases, Testing, Docs

**validate_config:** `{}` and `{}`-ish configs pass (contract gate). Strict on real
documents: `conditions` non-list, unknown op, missing/empty `field`, missing `arg`
on arg-requiring ops → `ValueError`.

**Edge cases:** missing-field semantics per §1; `isActive=false` pass-through;
empty conditions pass-all; text coercion of numbers/bools; conditions evaluated
against post-previous-modules product state at run time.

**Testing:**

- `backend/tests/test_filter_plugin.py` — every op both directions, case-sensitivity,
  conjunctive failure on second condition, isActive pass-through, empty pass-all,
  None-drop, `original_product` untouched, validate_config matrix, missing-field behavior
  (incl. `not_*` true-on-missing).
- `backend/tests/test_filter_contract.py` — core discovery, scope tuples,
  `frontend.component == "component.tsx"`, contract pass (mirrors the rules contract test).
- `backend/tests/test_filter_preview.py` — exact counts against staged fixtures,
  404 unknown feed, 422 invalid conditions, 401 unauthenticated.
- `frontend/src/features/filter/__tests__/FilterUI.test.tsx` — add/edit/delete rows,
  active toggle, save flow, preview card renders count (stubbed fetch), router-wrapped
  harness (useBlocker needs a data router).

**Docs (same commits):**

- `backend/docs/plugins.md` — core-plugin table row → real MVP scope; config-shape subsection.
- `backend/docs/api.md` — preview endpoint (method, request/response, error codes).
- `frontend/docs/plugin-uis.md` — second first-party reference component (same stub seam).

## Out of Scope (follow-ups)

- Numeric/regex operators (Rules-parity upgrade) and negate-whole-filter switch.
- Multiple named filter sets.
- PluginErrorBoundary (ADR-0004) around custom plugin components.
- Rule-id/rule-name surfaced in engine error logs (spec §4) — same need here (`condition_id`).
