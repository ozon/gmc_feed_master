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
| `menu_item` | No | Legacy display name; not rendered (nav labels use `pluginNames.*` i18n with `plugin.name` as fallback) |
| `icon` | No | Tabler icon name (e.g., `tag`, `category`, `filter`); rendered in the Pipeline Editor plugin list |
| `component` | No | Relative path to TSX default export |
| `uischema` | No | Layout hints (field order, custom widgets) |

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

`PluginConfigPanel` (Pipeline Editor) selects the panel surface in this order:

1. **Setup embed**: if the plugin has an entry in the static registry `CONFIG_COMPONENTS` (`src/features/plugin/configComponents.ts`), the panel embeds its Setup component with a tier switcher (Feed / Client / Global) driven by the manifest's `config_scope`/`data_scope` ∩ route context. Switching tiers re-renders the component with the matching `PluginScope` (remounted via a `plugin_id`-tier key); the component itself is unchanged. When the manifest's `config_scope` excludes `feed_source` (e.g. `custom_labels`), the panel shows an actionable alert that switches to the highest editable tier. Setup embeds are wrapped in `PluginErrorBoundary`. Instance settings render alongside the embed.
2. **Plugin-page link**: if the plugin has no Setup component but does have a custom page component (`manifest.frontend.component`, resolved via `CUSTOM_COMPONENTS`), the panel shows a hint plus an "Open plugin page" link to the feed-tier plugin page, and no raw JSON-schema instance form.
3. **Instance form**: otherwise the panel renders generic JSON-schema instance settings (`JsonSchemaForm`) only.

For `custom_labels`, `CustomLabelsUI` splits its two surfaces via the additive `onlyTab` prop: `LabelizerSetup` (`onlyTab="rules"`) renders rules-only in the panel, while `LabelizerPage` (`onlyTab="ids"`) renders the bulk-IDs dashboard only on the plugin page. The plugin page is therefore data-only (bulk IDs) at every tier — it no longer hosts the slot-rules editor.

### First-Party Reference: Rules (`plugins/core/rules/frontend/component.tsx`)

The Rules module is the first core plugin with a custom UI. MVP wiring:
`PluginPage` statically imports the plugin stub and renders it when
`manifest.frontend.component === 'component.tsx'`, passing `{ pluginId, scope }`.

The stub is a one-line re-export of the real implementation
(`export { default } from '../../../../frontend/src/features/rules/RulesUI'` —
rule list, editor, dnd reordering, i18n). It exists because bare package imports
are unresolvable from `plugins/` (no `node_modules` above it); the stub is the
documented seam until full build-time discovery lands.

RulesUI owns its own save state (dirty check + `useBlocker` with `ConfirmModal`); it fetches and
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

### First-Party Reference: Category (`plugins/core/category/frontend/component.tsx`)

The Category module is the third core plugin with a custom UI. The stub follows
the same re-export pattern as Rules and Filter; the component receives
`{ pluginId, scope }` and the shell keeps page-level state (feedSourceId +
language) that it passes to all tabs.

- **Dashboard tab:** feed-source selector drawn from the dashboard summary for
  the route's client; 4-bucket progress (auto/manual/excluded/uncategorized) +
  total; as-of-last-run note; auto-selects the first feed source.
- **Rules tab:** dnd-kit ordered editor mirroring the pipeline page; global/client
  tier view with Inherited read-only badges; taxonomy autocomplete via
  `GET /plugins/category/taxonomy/search`; per-rule match badges + a
  matched-products modal (as-of-last-run); draft validation via
  `POST /plugins/category/validate` before save; dirty guard via `useBlocker` +
  ConfirmModal.
- **Manual Categorization tab:** product lookup via `GET /plugins/category/product`,
  assign/unassign via the generic scoped data endpoint, read-modify-write of the
  assignments map.
- **Taxonomy language selector:** en-US shipped; de-DE fetched via
  `POST /plugins/category/taxonomy/fetch`, persisted server-side as a gitignored
  CSV; one merged ID-keyed index.
- **Placeholders:** the AI and Uncategorized tabs and the Generate / Copy /
  Bulk-delete controls render as disabled-with-tooltip placeholders (spec v1 scope).

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

### Sidebar plugin entries and the two-surface model (ADR-0007)
Each plugin has two user-facing surfaces. Its **Setup surface** lives in the Pipeline Editor: `PluginConfigPanel` embeds the plugin's registered Setup component from `CONFIG_COMPONENTS` inside a tier switcher (Feed / Client / Global), so users configure plugins without leaving the pipeline. Its **Plugin Page** (the working dashboard/tool) is reached from the sidebar: in feed context, enabled plugins with `manifest.frontend.component` get a nav entry between Setup and Products, labelled via `pluginNames.*` i18n with `plugin.name` as fallback. Plugin routes remain as deep links:
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
| Category | Custom (`component.tsx` stub → `frontend/src/features/category/CategoryUI`) | 4-bucket dashboard (auto/manual/excluded/uncategorized), drag-drop rule editor, taxonomy autocomplete, match counts, matched-products modal, dirty-state guard |
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
- `src/app/AppShell.tsx` — App shell with navigation (Dashboard, Setup, plugin entries, Products, Pipeline, Monitoring, Export); plugin routes are both nav entries (feed context) and deep links
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
- **Deep links for multi-scope plugins:** sidebar plugin entries exist in feed
  context for enabled custom-UI plugins (ADR-0007); each tier's page is
  reached from the sidebar entry, by direct URL — feed-scoped
  `` ${feedBase}/plugins/{id} ``, client-scoped `/clients/:c/plugins/:id`,
  otherwise `/plugins/{id}` — and via ScopeContextBar tier badges. Page titles
  resolve through `pluginNames.*` i18n with `plugin.name` as fallback.

### Live matching and slot-grouped bulk values

- **Preview:** the feed-page bulk tab debounce-posts the current DRAFT
  (rules + values, unsaved edits included) to the plugin-local
  `POST /plugins/custom_labels/preview` and renders a header coverage
  dashboard over ALL slots: "X / N staged products labeled" (products
  labeled in at least one slot), a green/gray progress bar, and quick
  stats (total, labeled, unlabeled, active rules). Each rule card header
  carries an "N matched" badge (tooltip explains matched-but-never-applied
  rules). Distinct "no staged products yet" and preview-error states;
  client/global pages render no stats and send no request.
- **Slot-selected view:** a top SegmentedControl picks one of
  `custom_label_0..4` (default: first slot with active rules; items are
  numbered `#1..#5`). Only that
  slot's active rules render, as collapsible `Accordion` rule cards in
  evaluation order, each header leading with a dimmed `#N` before the
  rule name. Collapsed headers show
  rule name, priority, inherited-from tier, matched count, and an
  "N overridden" badge when a higher-priority rule of the same slot
  claims values from this rule's list (client-side syntactic analysis;
  an `all`-mode rule shadows everything below it). Expanded panels hold
  the fixed 10-row monospace value-list textarea (no soft-wrap) with the unique-ID
  counter BELOW the input (no bottomSection overlap), per-rule clear
  button, and a shadow list rendering each overridden value struck
  through with a tooltip naming the claiming rule. Empty slots show a
  notice when selected.
- **Synchronized product preview:** at feed tier each expanded rule card
  splits its value editor 35/65: the monospace value textarea (fixed
  10-row height, no soft-wrap) beside a windowed preview column whose row
  i mirrors parsed entry i. Scrolling either side drives the other
  (bidirectional scrollTop sync). Rows come from
  `POST /feed-sources/{id}/products/lookup` (300 ms debounced, TanStack
  Query cached per value-set): per value it shows the sample product's
  title (truncated + tooltip), brand, availability badge
  (in_stock/out_of_stock), a gray "N products" badge when a value matches
  several products, dimmed removed/excluded badges, and a red
  "ID not found in feed" / "No match in feed" badge for dead values. A
  per-card MultiSelect adds extra raw-data fields inline (options from
  the feed's field list minus title/brand/availability; selection is
  session-local and survives collapse). Lookups are status-agnostic and
  match by the rule's match field, mirroring run-time semantics. Slot
  selector items are numbered `#1..#5`, and rule card headers show a
  compact `#N` before the rule name (evaluation order).
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
