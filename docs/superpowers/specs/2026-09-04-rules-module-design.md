# Rules Module — Core Plugin `rules` Design

**Date:** 2026-09-04
**Status:** Approved (brainstorming session 2026-09-04)
**Depends on:** plugin system (`backend/docs/plugins.md`), plugin custom components (ADR 0002, 0004), three-tier scope merge (`app/staging/config_resolver.py`)

## Purpose

First core pipeline module: a visual, row-based rules engine for product data
transformation. Left column: ordered rule list with drag-and-drop. Right column:
low-code IF/THEN rule editor (AST-backed). One feed source = one ordered rule
set executed in pipeline position order.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Architecture | Core plugin `plugins/rules/` (no dedicated tables, no migrations) |
| Operator scope | Full suite (text + numeric + regex capture groups) |
| UI scope tiers | Feed-source scoped UI; data model supports all 3 tiers from day one |
| `isMasterRule` | Badge + list pinning only; engine ignores the flag |
| Test depth | Full pytest + contract + vitest |
| UI integration | Plugin custom component rendered by generic PluginPage |

## 1. Architecture

```
plugins/rules/
├── plugin.json          # manifest
├── plugin.py            # RulesPlugin: validate_config() + process()
└── frontend/
    ├── component.tsx    # default export RulesUI (rendered by PluginPage)
    ├── ast.ts           # pure AST types + helpers (normalize, deep-equal)
    ├── RuleList.tsx     # left column
    └── RuleEditor.tsx   # right column
```

- **Extension point:** `pipeline_module` (only MVP extension point).
- **Scopes:** `config_scope = data_scope = ["global", "client", "feed_source"]`
  (as reserved in `backend/docs/plugins.md` core-plugin table). MVP UI writes
  only the `feed_source` tier via `PUT /plugins/rules/config?feed_source_id=…`.
- **Storage:** rules live in `plugin_configs` JSONB under the resolved three-tier
  merge. No schema changes, no Alembic migration.
- **Pipeline position:** the plugin is added to a feed source's pipeline on the
  Pipeline page like any other module; rules execute at that position.

## 2. Config Document Shape

```jsonc
{
  "rules": [
    {
      "id": "r_9f3c…",          // crypto.randomUUID(), stable, client-generated
      "name": "Remove HTML",
      "isMasterRule": false,
      "isActive": true,
      "when": { "op": "all" }, // IF
      "then": [                 // THEN, ordered
        { "op": "set", "field": "condition", "value": "new" },
        { "op": "replace", "field": "title", "find": "<p>", "with": "" }
      ]
    }
  ]
}
```

### IF AST (`when`)

- `{ "op": "all" }` — matches every product (screenshot's "evaluates to all").
- `{ "op": "and" | "or", "children": [<node>…] }` — grouping; at least one child.
- Leaf: `{ "op": <operator>, "field": <string>, "arg": <string|number>, "arg2"?: <number> (between), "caseSensitive"?: <bool> }`.

**Condition operators:**

| Op | arg | Notes |
|---|---|---|
| `equals` | string | `caseSensitive` flag (default true) |
| `contains` | string | `caseSensitive` flag |
| `starts_with` / `ends_with` | string | `caseSensitive` flag |
| `regex` | pattern | compiled per evaluation failure → condition error (see §4) |
| `exists` | — | key present and value not null |
| `empty` | — | missing, null, or empty string |
| `gt` `lt` `gte` `lte` | number | non-numeric value → false, no crash |
| `between` | min (`arg`), max (`arg2`) | inclusive, numeric coercion as above |

### THEN operations

| Op | Required keys | Effect |
|---|---|---|
| `set` | `field`, `value` | assign |
| `replace` | `field`, `find`, `with`, `caseSensitive?` | substring or regex replace; regex capture groups via `$1` |
| `append` | `field`, `value` | string concat (value coerced to string) |
| `prepend` | `field`, `value` | string concat (coerced) |
| `remove` | `field` | delete key |
| `clear` | `field` | set to `""` |

`find` starting with `/` marks regex mode (e.g. `/<p>.*?<\/p>/`).

### Semantics

- **Order = priority.** Array order is execution order; the engine ignores
  `isMasterRule`.
- **`isMasterRule`**: badge + pinning in the list UI only (masters sort to top;
  drag cannot place a non-master above a master). Stored in config so tiers can
  inherit the flag.
- **`isActive: false`**: engine skips; retained in config.
- **`when.op = "all"`** requires no criteria and is the default for new rules.
- Evaluation runs against the *current* product state (post-previous-plugins),
  per the runtime contract. `ctx.original_product` is never touched.

## 3. UI Design

PluginPage renders `plugins/rules/frontend/component.tsx` at
`/clients/:clientId/feeds/:feedSourceId/plugins/rules` (nav entry via
`manifest.frontend.menu_item`; AppShell's client-scoped plugin link logic
applies). Field dropdowns use `useFeedSourceFields` (same hook as products page).

### Left column — RuleList

- dnd-kit vertical sortable (PointerSensor, distance 4 — same as PipelinePage).
- **Header:** "+ Create rule" button; search/filter ActionIcon toggling a
  TextInput (case-insensitive name match).
- **Bulk select-all Checkbox** toggles selection of all rows; selection powers
  kebab bulk actions (activate/deactivate, delete).
- **Rows** (draggable): selection Checkbox, name label, orange `Badge` when
  `isMasterRule`, kebab `Menu` (Edit, Rename, Duplicate, Toggle active, Toggle
  master, Delete). Selected row highlighted blue (`variant="light"`), populates
  the editor.
- **Pinning invariant:** masters always render before non-masters; dnd enforces
  (non-master dropped above master region → lands below last master).

### Right column — RuleEditor

- **Header:** inline-editable rule name, master Badge, gear `Menu` (Rename,
  Toggle master, Toggle active, Delete rule).
- **IF block:** condition-type Select — `all` | `where`. In `where` mode:
  rows of `[Field Select][Operator Select][Value Input]`, AND/OR combiner
  Select between rows, per-row delete/clone/+ ActionIcons; "+ Add section"
  appends a root-level branch.
- **THEN block:** rows of `take [Field Select] and [Operation Select] …`:
  - `set`/`append`/`prepend` → single value TextInput
  - `replace` → find + with TextInputs (+ `caseSensitive` Switch)
  - regex-exposing ops → `caseSensitive` Switch
  - per-row ActionIcons: trash, copy (clone), plus (append row)
- **Footer:** "+ Add section" appends a THEN row (or root-level branch in
  `where` mode).

### State & save

Local draft in the component, hydrating once from server config (PluginPage
seeding pattern). Dirty-check via deep compare; `useBlocker` unsaved-changes
guard with `window.confirm` (PipelinePage pattern). Save =
`useSavePluginConfig('rules', { feedSourceId })`. Reset button re-hydrates.
Delete rules confirm via `modals.confirm`. i18n: new `rules` namespace (en + ru).

## 4. Error Handling & Edge Cases

- **`validate_config`:** rejects non-list `rules`, unknown op codes, missing
  required keys per op (`set` → field+value; `between` → arg+arg2; `replace` →
  field+find+with; etc.), group nodes with no children. Backend save re-validates;
  frontend surfaces 422 via `mapFieldErrors`.
- **Engine:** exception in a rule → product errored for that rule (logged
  `plugin_id: rules`, `rule_id`), run continues; invalid regex → that rule
  errors for that product, never a run crash; empty `then` list → no-op;
  `isActive: false` → silent skip.
- **Edge cases:** missing field → `exists` false / `empty` true; text ops
  coerce non-string values; numeric ops on non-numbers → condition false; dot
  paths (`a.b.c`) resolve against nested `raw_data` per spec §5.7 grammar
  (documented; deep-path write support limited to top-level virtual fields in
  MVP, nested write documented as follow-up).

## 5. Testing

- **Backend** (`backend/tests/test_rules_plugin.py`): every condition operator
  (true + false), AND/OR grouping, numeric comparisons, regex with capture
  groups, action ordering, master flag has no engine effect, inactive skip,
  `validate_config` rejection matrix, `original_product` immutability.
- **Contract:** `backend/tests/test_plugin_contract.py` auto-covers manifest,
  process contract, config validation, reserved routes, frontend component
  presence.
- **Frontend vitest:** `ast.ts` pure-function tests (normalize/deep-equal);
  RuleEditor state-shape tests (add/clone/delete rows, pinning invariant);
  RulesUI render smoke test within a PluginPage-style harness.

## 6. Documentation (same commit)

- `backend/docs/plugins.md` — core-plugin table row updated to real MVP scope.
- `frontend/docs/plugin-uis.md` — first-party core plugin as reference custom
  component.
- No spec (`gmc-feed-engine-spec.md`) changes required; §5.7 field-path grammar
  referenced.

## Out of Scope (follow-ups)

- Global/client tier editor UI (scope switcher) — data model already supports.
- Bulk CSV import/export of rules.
- Rule execution statistics per run (hit counts) — needs plugin data tier.
- Nested-path writes into `raw_data` (reads supported, writes follow-up).
