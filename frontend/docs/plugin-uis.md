# Frontend Plugin UIs

## Build-Time Discovery

Plugins with custom UIs declare `manifest.frontend.component` (e.g., `"Editor.tsx"`). At build time, Vite scans `plugins/*/frontend/` and registers components — **no runtime module federation**, single build pipeline.

### Discovery Flow
```
Vite build
    │
    ▼
Scan plugins/*/frontend/ for .tsx files
    │
    ▼
Generate virtual module: pluginComponents.ts
    │
    ▼
Import in PluginPage → render via dynamic import
```

### Manifest Frontend Field
```json
{
  "frontend": {
    "menu_item": "Labelizer",
    "icon": "tag",
    "component": "Editor.tsx",
    "uischema": { "order": ["dimensions"], "dimensions": { "ui:widget": "dimension-editor" } }
  }
}
```
| Property | Required | Description |
|----------|----------|-------------|
| `menu_item` | No | Legacy display name; no longer rendered (sidebar Plugins section removed, ADR-0006) |
| `icon` | No | Tabler icon name (e.g., `tag`, `category`, `filter`); rendered in the Pipeline Editor plugin list |
| `component` | No | Relative path to TSX default export |
| `uischema` | No | Layout hints for RJSF (field order, custom widgets) |

## Schema-Rendered Forms (Default)

When no `component` is declared, config/data UIs are auto-rendered from JSON Schema using `JsonSchemaForm` (`src/components/JsonSchemaForm.tsx`).

### Supported Schema Features
| JSON Schema | Mantine Component |
|-------------|-------------------|
| `type: "string"` | `TextInput` |
| `type: "string", enum: [...]` | `Select` |
| `type: "number" / "integer"` | `NumberInput` |
| `type: "boolean"` | `Switch` |
| `type: "object"` | Nested `Stack` of properties |
| `type: "array"` | Repeatable group + add/remove buttons |
| `required: [...]` | Visual indicator (Mantine `required` prop) |
| `description` | `description` prop on field |

### Validation
- **Client-side**: `JsonSchemaForm` validates on change (required, type, enum)
- **Server-side**: Backend returns 422 `{"errors":[...]}` → `notifyApiError` → `mapFieldErrors` surfaces per-field
- **AJV** (for RJSF): Configured for JSON Schema draft 2020-12 (Pydantic v2 output)

## Custom Plugin Components

### Component Contract
- Receives `{ pluginId, scope }` as props from `PluginPage` (resolved from route params)
- Uses `usePluginConfig` / `useSavePluginConfig` hooks (scope-aware)
- Full access to Mantine, TanStack, React APIs
- Custom components own their save UX: `PluginPage` hides its generic Save button
  when rendering a custom component
- Custom components fetch their own config/data; `PluginPage` skips its generic
  config fetch whenever `manifest.frontend.component` is set (the fetch is also
  gated on the plugins list resolving, so it cannot race ahead of the hint).
  This keeps asymmetric-scope plugins (e.g. `custom_labels`: config at
  global/client, data at client/feed_source) from 422ing on URL tiers the
  manifest does not declare for that payload kind.

### Scope-Aware Fetching (asymmetric scopes)

Plugins may declare different tiers per payload kind (`config_scope` vs
`data_scope`). A component rendering at a URL tier the manifest does not
declare for a kind must resolve a declared fallback tier instead of sending
the request (the backend's `_resolve_target` answers undeclared scopes with
422). `CustomLabelsUI` implements the reference pattern
(`resolveKindScope` in `frontend/src/features/customLabels/CustomLabelsUI.tsx`):

- URL tier declared → fetch at the URL tier
- URL tier not declared → fall back to the most-specific declared tier
  reachable from the route (feed-source URL + config → client tier; the
  affected tab is rendered read-only with a hint)
- No declared tier reachable (global URL + data for `custom_labels`) →
  the request is not sent; the tab is disabled with a hint and the other
  tab becomes the default

### Custom Component Registry

`frontend/src/features/plugin/customComponents.ts` maps plugin IDs to statically imported components (`rules` → RulesUI, `filter` → FilterUI, `custom_labels` → CustomLabelsUI); `PluginPage` resolves `CUSTOM_COMPONENTS[plugin.id]` when `manifest.frontend.component` is set. Add new custom components to that map until build-time discovery lands.

### Pipeline Editor embedding

`PluginConfigPanel` (Pipeline Editor) renders a registered custom component
inside a tier switcher (Feed / Client / Global) driven by the manifest's
`config_scope`/`data_scope` ∩ route context. Switching tiers re-renders the
component with the matching `PluginScope`; the component itself is
unchanged. When the manifest's `config_scope` excludes `feed_source`
(e.g. `custom_labels`), the panel shows an actionable alert that switches to
the highest editable tier.

### First-Party Reference: Rules (`plugins/core/rules/frontend/component.tsx`)

The Rules module is the first core plugin with a custom UI. MVP wiring:
`PluginPage` statically imports the plugin stub and renders it when
`manifest.frontend.component === 'component.tsx'`, passing `{ pluginId, scope }`.

The stub is a one-line re-export of the real implementation
(`export { default } from '../../../../frontend/src/features/rules/RulesUI'` —
rule list, editor, dnd reordering, i18n). It exists because bare package imports
are unresolvable from `plugins/` (no `node_modules` above it); the stub is the
documented seam until full build-time discovery lands.

RulesUI owns its own save state (dirty check + `useBlocker`); it fetches and
saves via the scope-aware plugin config hooks.

The rules UI is reachable at the feed-scoped route
`/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId`, and `PluginPage` derives
the scope tier from route params (most-specific wins).

### First-Party Reference: Filter (`plugins/core/filter/frontend/component.tsx`)

The Filter module is the second core plugin with a custom UI. FilterUI is a
single-pane condition editor with live preview via `POST /plugins/filter/preview`.
It renders a conjunctive set of scalar conditions (equals, not_equals, contains,
not_contains, exists, empty) and shows pass/fail counts against staged products.

The stub re-exports `frontend/src/features/filter/FilterUI`. FilterUI owns its
own save state and uses the scope-aware plugin config hooks.

Follow-up: full build-time discovery (Vite scan of `plugins/*/frontend/`
generating `pluginComponents.ts`, per ADR 0002 — third-party plugins currently
use schema-rendered forms). Error isolation via `PluginErrorBoundary` is now
implemented (see below).

### Error Isolation (ADR-0004)
Error isolation via `PluginErrorBoundary` (`src/features/plugin/PluginErrorBoundary.tsx`):
custom plugin components are wrapped with it in both `PluginPage` and the
Pipeline Editor's `PluginConfigPanel`, so a crashing plugin UI shows a retry
fallback instead of taking the page down (ADR 0004).

### Build-Time Contract Test
CI verifies:
1. `manifest.frontend.component` path exists
2. File exports a valid React component (default or named `Component`)
3. TypeScript compiles without errors
4. No restricted imports (e.g., direct DOM manipulation)

## Plugin Routes and Deep Links

### Sidebar Removal (ADR-0006)
The sidebar "Plugins" menu has been removed; the Pipeline Editor is the hub for
plugin configuration. `PluginConfigPanel` embeds a registered custom component
inside a tier switcher (Feed / Client / Global), so users configure plugins
without leaving the pipeline. Plugin routes remain as deep links:
`/plugins/:id`, `/clients/:c/plugins/:id`,
`/clients/:c/feeds/:f/plugins/:id` — reachable via ScopeContextBar tier
badges and bookmarks.

### Route Mapping
| Manifest | Route | Rendered By |
|----------|-------|-------------|
| `frontend.component` present | `/plugins/:pluginId` or `/clients/:clientId/plugins/:pluginId` | Custom component |
| No component | `/clients/:clientId/plugins/:pluginId` | `PluginPage` → `JsonSchemaForm` |

## Core Plugin UIs (MVP)

| Plugin | UI Type | Key Features |
|--------|---------|--------------|
| Labelizer | Custom (`Editor.tsx`) | Dimension editor with global/client scope switch, ID lists per dimension |
| Rules | Custom (`component.tsx` stub → `frontend/src/features/rules/RulesUI`) | Ordered rule list (IF/THEN AST) with dnd reordering, active/master toggles, per-rule editor, dirty-save guard |
| Category | Custom (`Editor.tsx`) | 4-bucket dashboard (auto/manual/excluded/uncategorized), drag-drop rule editor, taxonomy autocomplete, match counts, matched-products modal, dirty-state guard |
| Filter | Custom (`component.tsx` stub → `frontend/src/features/filter/FilterUI`) | Conjunctive scalar condition editor with live preview |

## Adding a Plugin UI

1. **Create frontend dir**: `plugins/my_plugin/frontend/Editor.tsx`
2. **Update manifest**: Add `frontend` section with `component: "Editor.tsx"`
3. **Implement component**: Use `usePluginConfig`/`useSavePluginConfig` hooks
4. **Run contract test**: `uv run pytest backend/tests/test_plugin_contract.py`
5. **Build frontend**: `npm run build` (verifies TypeScript + component export)
6. **Test in dev**: `npm run dev` → navigate to plugin page

## Key Files
- `src/features/plugin/PluginPage.tsx` — Schema form page (config/data)
- `src/components/JsonSchemaForm.tsx` — Recursive Mantine form renderer
- `src/app/AppShell.tsx` — App shell with navigation (Dashboard + feed-scoped areas); plugin routes accessed via deep links
- `src/api/hooks.ts` — `usePluginConfig`, `useSavePluginConfig`, `usePluginData`, `useSavePluginData`
- `vite.config.ts` — Build config (vendor chunking, HTTPS proxy)
- `backend/tests/test_plugin_contract.py` — Contract test (includes reserved route check)

## Custom component scope behavior (custom_labels / "Labelizer")

- **Merged tier view:** `CustomLabelsUI` fetches every declared config tier
  reachable from the URL (global always, client when known) and merges
  `slotRules` union-by-id — identical to the run-time merge declared via the
  manifest's `config_merge` (see ADR-0005). Inherited rules render with a
  ScopeBadge and are read-only; saving writes only the editable tier's rules.
- **Bulk values:** data tiers merge per rule id; inherited values are badged.
  Saving pins the merged dict to the current tier (ADR-0005).
- **Rule modes:** `matchMode: "values"` (explicit value list, textarea relabels
  to the match field) or `"all"` (every product matches; the bulk tab shows a
  "controlled by rule" summary).
- **Help UI:** inline description and a user-guide drawer (opened via the "?"
  action icon) per plugin page.
- **Deep links for multi-scope plugins:** sidebar plugin entries have been
  removed (ADR-0006); each tier's page is reached by direct URL — feed-scoped
  `` ${feedBase}/plugins/{id} ``, client-scoped `/clients/:c/plugins/:id`,
  otherwise `/plugins/{id}` — and via ScopeContextBar tier badges. Page titles
  resolve through `pluginNames.*` i18n with `plugin.name` as fallback.
### Live matching and slot-grouped bulk values

- **Preview:** the feed-page bulk tab debounce-posts the current DRAFT
  (rules + values, unsaved edits included) to the plugin-local
  `POST /plugins/custom_labels/preview` and renders a compact stats header per
  slot: "X of N staged products labeled" with a coverage progress bar, plus an
  "N matched" badge on each rule input block (the badge tooltip explains
  shadowed "never applied" rules). Distinct "no staged products yet" and
  preview-error states; client/global pages render no stats and send no
  request. Sample product deep-links were removed.
- **Grouped by slot:** the bulk tab renders full-width slot cards stacked
  vertically (one per `custom_label_0..4` with active rules, registry
  order). Each card header carries the slot badge (orange dot while the slot
  has unsaved value edits), slot explanation, active-rule count, and live
  stats; the slot's rule editors sit side-by-side in a responsive inner grid
  (1 column on mobile, 2 from `sm`, 5 per row from `lg`) —
  400px-capped monospace value-list textareas with inline ID counters and
  per-rule clear buttons. Slots without active rules collapse into a single
  summary row of badges.
- **Rule actions:** the rule editor offers Duplicate (fresh id, "(copy)" name)
  and Delete (ConfirmModal; global-origin deletes warn about the inheritance
  blast radius) — editable-origin rules only.
- **Override at client level:** on the client page, an inherited global rule
  offers "Override at client level" — flips the rule to client-origin with the
  SAME id (union-by-id makes client content win at run time), editable
  immediately, saved to the client tier on Save.
- **Tier navigation:** ScopeContextBar badges for non-current tiers link to
  their pages (Global → `/plugins/{id}`, Client → `/clients/:c/plugins/{id}`),
  making the global page reachable from client/feed contexts.
- **Read-only hint:** "Slot rules are read-only here — they live at Global or
  Client level." plus the manage-at-client link.
