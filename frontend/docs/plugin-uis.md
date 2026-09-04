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
| `menu_item` | Yes | Sidebar label |
| `icon` | Yes | Tabler icon name (e.g., `tag`, `category`, `filter`) |
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
`/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId` (the nav shows
feed-scoped plugin links only inside a feed context), and `PluginPage` derives
the scope tier from route params (most-specific wins).

Follow-ups: full build-time discovery (Vite scan of `plugins/*/frontend/`
generating `pluginComponents.ts`, per ADR 0002 — third-party plugins currently
use schema-rendered forms) and error isolation via `PluginErrorBoundary`
(per ADR 0004, not yet implemented).

### Error Isolation (ADR-0004)
Planned follow-up — `PluginErrorBoundary` does not exist yet. When implemented,
every plugin component will render inside it:
```tsx
<PluginErrorBoundary pluginName={plugin.name} fallback={<PluginErrorFallback />}>
  <CustomComponent />
</PluginErrorBoundary>
```
- Will catch render errors, show fallback with "Reload plugin" button
- Will log error to console with plugin context
- Prevents dashboard crash

### Build-Time Contract Test
CI verifies:
1. `manifest.frontend.component` path exists
2. File exports a valid React component (default or named `Component`)
3. TypeScript compiles without errors
4. No restricted imports (e.g., direct DOM manipulation)

## Plugin Menu Integration

### Dynamic Menu (`src/app/AppShell.tsx`)
```typescript
const { data: plugins } = usePlugins();
const menuItems = plugins
  .filter(p => p.enabled)
  .map(p => ({
    label: p.manifest?.frontend?.menu_item ?? p.name,
    icon: p.manifest?.frontend?.icon ?? 'settings',
    href: p.manifest?.frontend?.component
      ? `/plugins/${p.id}`           // Custom component route
      : `/clients/${clientId}/plugins/${p.id}`,  // Schema form route
  }));
```

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
| Filter | Schema-rendered | Conjunctive scalar conditions |

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
- `src/app/AppShell.tsx` — Dynamic plugin menu construction
- `src/api/hooks.ts` — `usePluginConfig`, `useSavePluginConfig`, `usePluginData`, `useSavePluginData`
- `vite.config.ts` — Build config (vendor chunking, HTTPS proxy)
- `backend/tests/test_plugin_contract.py` — Contract test (includes reserved route check)