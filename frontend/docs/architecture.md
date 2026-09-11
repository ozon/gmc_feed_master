# Frontend Architecture

## Stack
| Layer | Technology |
|-------|------------|
| Framework | React 19 + TypeScript |
| Build | Vite 8 (Rolldown bundler; vendor chunks via build.rolldownOptions.output.codeSplitting.groups) |
| UI Library | Mantine 9 |
| Server State | TanStack Query v5 |
| Tables | TanStack Table v9 |
| Forms | TanStack Form v1 (core) + custom JsonSchemaForm (plugin schemas) |
| Drag & Drop | dnd-kit |
| Routing | React Router v7 |
| i18n | i18next (HTTP backend, browser detector) |
| Testing | Vitest + React Testing Library |

## Server State Strategy (TanStack Query)

```mermaid
flowchart TD
    subgraph Client["Browser"]
        QC[QueryClient\nqueryClient.ts]
        QK[Query Keys\nqueryKeys.ts]
        HK[Hooks\nhooks.ts]
    end

    subgraph Server["Backend API"]
        API[FastAPI Endpoints]
    end

    QC -->|cache, dedupe, retry| HK
    HK -->|queryKey| QK
    HK -->|fetch| API
    API -->|JSON| HK
    HK -->|invalidate| QC
    QC -->|refetchInterval| HK
```

### Query Key Structure (`src/api/queryKeys.ts`)
```typescript
queryKeys = {
  session: ['session'],
  dashboardSummary: ['dashboard', 'summary'],
  clients: ['clients'],
  plugins: ['plugins'],
  registryAttributes: ['registry', 'attributes'],
  productDetail: (feedSourceId, productId) => ['feed-source', feedSourceId, 'products', 'detail', productId],
  feedSource: (id) => ({
    detail: ['feed-source', id],
    products: (params) => ['feed-source', id, 'products', params],
    pipeline: ['feed-source', id, 'pipeline'],
    runs: ['feed-source', id, 'runs'],
    findings: ['feed-source', id, 'findings'],
    exportHistory: ['feed-source', id, 'export-history'],
    exportDiff: (params | undefined) => ['feed-source', id, 'export-diff', params ?? { disabled: true }],
    fieldMapping: ['feed-source', id, 'field-mapping'],
    mapping: ['feed-source', id, 'field-mapping'],   // alias of fieldMapping
    fields: ['feed-source', id, 'fields'],
  }),
  pluginConfig: (pluginId, scope) => ['plugin-config', pluginId, scope ?? {}],
  pluginData: (pluginId, scope) => ['plugin-data', pluginId, scope ?? {}],
}
```

### Polling & Invalidation (`src/api/hooks.ts`)
| Hook | Polling | Invalidation Trigger |
|------|---------|---------------------|
| `useDashboardSummary` | 5s if any run `running`, else 30s | — |
| `useIngestionRuns` | 5s if `active=true` | Manual run, dry run |
| `useQualityFindings` | 5s if `active=true` | Pipeline completion |
| `useRunDryRun` | — | Invalidates `runs` + `findings` |
| `useRotateExportToken` | — | Invalidates `feedSource.detail` |
| `useSavePipeline` | — | Invalidates `feedSource.pipeline` |
| `usePatchPipelineInstance` | — | Invalidates `feedSource.pipeline` (on success and failure — failure refetches to roll back the optimistic toggle) |
| `useUpdatePluginEnabled` | — | Invalidates `plugins` (global registry toggle) |
| `useRollbackToVersion` | — | Invalidates `feedSource.exportHistory` + `export-diff` (prefix) |

**Rule**: All server state in TanStack Query. **No duplicate stores** (Zustand, Redux, Context for server data).

### Mutation Pattern
```typescript
export function useSavePipeline(feedSourceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (doc) => apiPut(`/feed-sources/${feedSourceId}/pipeline`, doc),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(feedSourceId).pipeline });
    },
  });
}
```

## Client State (React Built-ins Only)
- `useState` / `useReducer` for form drafts, UI toggles, pipeline builder workspace
- `Context` for: theme, notifications, i18n, session (auth state via TanStack Query)
- **No global store library** (Zustand, Redux, Jotai, etc.)

## Routing (`src/app/router.tsx`)

```
/
├── /login
└── (RequireSession) → AppShell
    ├── /                                    → DashboardPage
    ├── /clients/:clientId/feeds/:feedSourceId/setup          → SetupPage
    ├── /clients/:clientId/feeds/:feedSourceId/products       → ProductsPage
    ├── /clients/:clientId/feeds/:feedSourceId/pipeline       → PipelinePage
    ├── /clients/:clientId/feeds/:feedSourceId/monitoring/
    │   ├── /runs                           → MonitoringRunsPage
    │   ├── /findings                       → MonitoringFindingsPage
    │   └── /dry-run                        → MonitoringDryRunPage
    ├── /clients/:clientId/feeds/:feedSourceId/export         → ExportPage
    ├── /clients/:clientId/feeds/:feedSourceId/plugins/:pluginId  → PluginPage (feed scope)
    ├── /clients/:clientId/plugins/:pluginId                  → PluginPage (client scope)
    ├── /plugins/:pluginId                                    → PluginPage (global scope)
    ├── /admin                           → AdminPage (Users tab, RequireAdmin)
    │   ├── /admin/users                 → AdminPage (Users tab)
    │   ├── /admin/clients               → AdminPage (Clients tab)
    │   └── /admin/settings              → AdminPage (Settings tab)
    └── *                                 → NotFoundPage
```

- **Lazy loading** for all feature pages (`React.lazy` + `Suspense`)
- **Session guard**: `RequireSession` redirects to `/login` on 401
- **Admin guard**: `RequireAdmin` redirects non-admins (session `role !== 'admin'`) away from `/admin/*`
- **Unauthorized handler**: Clears session queries, redirects with `from` state

## Admin Area & Role-aware UI

- Session shape (`GET /auth/me`): `{username, role: 'admin' | 'user', client_ids: number[] | null}` (`null` = admin/unrestricted). Server state via `useSession` only (ADR-0001).
- Single "Admin" NavLink in `AppShell` renders only for admins and links to `/admin`; `AdminPage` is one page with URL-driven Mantine tabs (Users, Clients, Settings; `keepMounted={false}`, so only the active tab's queries fire). The sub-paths `/admin/users|clients|settings` preselect the tab. Dashboard shows a "Manage clients" link for admins instead of inline client CRUD.
- `AdminClientsPage` — Clients tab panel: client CRUD moved here from the dashboard (now read-only listing for everyone); the dashboard's `ClientModal`/`DeleteClientModal` components are reused there.
- `AdminUsersPage` — Users tab panel: user table (role badge, assigned-client count, active switch), create/edit modal with role select + client multi-select, reset-password modal.
- `AdminSettingsPage` — Settings tab panel: editable retention days (`/admin/settings`), scheduler job overview (`/admin/scheduler`), plugin enable/disable toggles (reuses `useUpdatePluginEnabled`).
- Backend enforces the same rules (404 for unassigned client/feed-source access, 403 for admin-only operations, `/admin/*` admin-only) — the frontend guard is UX only.

## State Boundaries

| Data | Location | Mutation |
|------|----------|----------|
| User session | TanStack Query (`useSession`) | `login`/`logout`/`password` mutations |
| Clients, feed sources | TanStack Query | `create`/`update`/`delete` mutations |
| Pipeline definition | TanStack Query (`useFeedSourcePipeline`) | `useSavePipeline` (Save), `usePatchPipelineInstance` (per-instance enable) |
| Field mapping | TanStack Query (`useFieldMapping`) | `useSaveFieldMapping` / `useAutoMap` |
| Plugin config/data | TanStack Query (`usePluginConfig`) | `useSavePluginConfig` / `useSavePluginData` |
| Products (paginated) | TanStack Query (`useProductList`) | — (read-only from staging) |
| Quality findings | TanStack Query (`useQualityFindings`) | — (read-only from QC) |
| Export history | TanStack Query (`useExportHistory`) | `useRollbackToVersion` |
| Pipeline builder workspace | **Local React state** (`PipelinePage` `LocalInstance[]`) | Drag/drop reorder, add/remove instances, config edits, toggles on unsaved instances (saved instances persist via PATCH immediately) |
| Form drafts (plugin UIs) | **Local React state** (`PluginPage`) | `onChange` → local, `onSubmit` → mutation |
| Notifications | `src/app/notifications.ts` (Mantine `Notifications` provider) | `notifySuccess` / `notifyApiError` |

## Key Components

### Pipeline Builder (`src/features/pipeline/`) — master-detail layout
- `PipelinePage` — container; local instance state (`LocalInstance` = `PipelineInstance` + position-based `clientId`), dirty tracking (`isInstancesEqual` vs server snapshot), `useBlocker` navigation guard with `ConfirmModal`
  - Layout: `PipelineOverviewStrip` on top, `PluginList` left (`Grid.Col span={4}`), `PluginConfigPanel` right (`Grid.Col span={8}`)
  - Save (PUT) persists the full local array — reorder, add, remove, and config edits in one request; Reset restores the server snapshot; unsaved-instance toggles also flush on Save
  - **Per-instance enable is immediate-persist**: the Switch PATCHes `enabled` for saved instances (optimistic; on failure rolls back the whole local array snapshot and invalidates the pipeline query to refetch); unsaved instances (no `id` yet) flip locally and persist with Save
- `PipelineOverviewStrip` — total/enabled/disabled counters + dirty badge
- `PluginList` — master list; owns the dnd-kit `DndContext`/`SortableContext` (row reorder via drag handles), per-instance enable switches (`plugin-toggle-*`), add-from-registry (`add-plugin-*`), global registry toggles (registry section, `registry-toggle-*` → `useUpdatePluginEnabled`)
- `PluginConfigPanel` — detail panel; embeds the plugin's registered custom UI inside a tier switcher (Feed / Client / Global) when the plugin has a custom component, plus the JSON-schema instance-settings form for the selected instance (internal draft, keyed remount on selection change), remove button
- `dndUtils` — pure helpers: `addInstance` / `reorderInstances` / `applyDragEnd` / `removeInstance` / `isInstancesEqual`

### Plugin System (`src/features/plugin/`)
- `PluginPage` — renders plugin config/data form
  - Schema from `plugin.manifest.config_schema`
  - Auto-rendered via `JsonSchemaForm` (custom Mantine renderer)
  - Custom component via `manifest.frontend.component` (build-time import)
  - Registry map in `src/features/plugin/customComponents.ts` — keyed by plugin id (currently `rules` → `RulesUI`, `filter` → `FilterUI`, `custom_labels` → `CustomLabelsUI`)
  - Fallback: if plugin id has no registry entry, renders schema form
- **Navigation**: The sidebar shows Dashboard plus the feed-scoped areas in this order: Setup, plugin entries (enabled plugins with `manifest.frontend.component`), Products, Pipeline, Monitoring, Export. Plugin entries appear only in feed context and are labeled via `pluginNames.*` i18n keys with `plugin.name` as fallback, with icons resolved via `getPluginIcon`. Each plugin has two surfaces (ADR-0007): its Plugin Page (dashboard/tool) and its Setup surface embedded in the Pipeline Editor — `PluginConfigPanel` embeds the plugin's registered Setup component from `CONFIG_COMPONENTS` (`src/features/plugin/configComponents.ts`) with a tier switcher (Feed / Client / Global); plugins with only a custom page component show a hint and an "Open plugin page" link in the panel. Plugin routes (`/plugins/:id`, `/clients/:c/plugins/:id`, `/clients/:c/feeds/:f/plugins/:id`) remain as deep links (ScopeContextBar tier hrefs, bookmarks).
- **Plugin UIs with custom components**:
  - `rules` → `RulesUI` (`src/features/rules/`) — ordered rule list with dnd reordering, master pinning, i18n (`rules` namespace)
  - `filter` → `FilterUI` (`src/features/filter/`) — conjunctive scalar condition editor with live preview, dirty-guard + useBlocker, i18n (`filter` namespace)
  - `custom_labels` → `CustomLabelsUI` (`src/features/customLabels/`, UI name "Labelizer") — merged Global/Client/Feed tier view (union-by-id mirroring the runtime `config_merge`); the bulk tab is slot-selected via a top SegmentedControl (custom_label_0..4) with a coverage dashboard (any-slot labeled/total, progress bar, quick stats) and collapsible priority-ordered rule cards (matched + overridden badges, shadowed-value list with attribution tooltips), debounced draft preview via `POST /plugins/custom_labels/preview`; rule duplicate/delete, override-at-client-level, clickable tier navigation, help drawer; expanded rule cards at feed tier add a synchronized, windowed product preview column beside the value list (batch lookup via `POST /feed-sources/{id}/products/lookup`), i18n (`customLabels` namespace)
- All three custom components share the pattern: dirty-guard + `useBlocker` navigation guard with `ConfirmModal`, `useSavePluginConfig` mutation for editable-tier writes

### Quality Dashboard (`src/features/monitoring/`)
- `MonitoringRunsPage` — `IngestionRunsTable` with polling
- `MonitoringFindingsPage` — `FindingsTable` grouped by severity/rule
- `MonitoringDryRunPage` — trigger dry run, show `DryRunResults`

### Export (`src/features/export/`)
- `ExportPage` — `ExportVersionList` + `ExportVersionDiff` + `RollbackConfirmModal`

### Setup (`src/features/setup/`)
- `SetupPage` — tabs: Feed Settings, Field Mapping, Export URL
- `MappingTab` — `MappingTable` (TanStack Table; observed rows + custom rows with add/remove, shadow indicator for observed/custom overlap) + auto-map button (the only automap trigger — pipeline runs and dry-runs never auto-match; custom source fields are dormant until the feed supplies the key)

## Development Setup
```bash
# Generate certs (once)
mkdir -p local-certs
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout local-certs/localhost-key.pem \
  -out local-certs/localhost-cert.pem \
  -days 365 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# .env.local
VITE_HTTPS_CERT=local-certs/localhost-cert.pem
VITE_HTTPS_KEY=local-certs/localhost-key.pem

# Dev servers
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
cd frontend && npm run dev
# Open https://localhost:5173
```

- Vite proxies `/auth/*`, `/health`, `/admin`, `/clients`, `/feed-sources`, `/dashboard`, `/plugins`, `/registry`, `/export` to `http://127.0.0.1:8000` (production Caddyfiles mirror this list, including `/admin/*`)
- HTTPS required for `Secure` session cookie

## Key Files
- `src/main.tsx` — App entry, providers
- `src/App.tsx` — MantineProvider, LocaleProvider, Suspense
- `src/app/router.tsx` — Routes, session guard, lazy loading
- `src/api/queryClient.ts` — QueryClient config (no retry, no background refetch)
- `src/api/queryKeys.ts` — Hierarchical query key factory
- `src/api/hooks.ts` — All data fetching + mutation hooks
- `src/api/client.ts` — `apiGet`/`apiPost`/`apiPut`/`apiPatch`/`apiDelete` with cookie handling
- `src/api/fieldOptions.ts` — Single option-building authority: `FieldDescriptor` adapters (`fromSourceFields`, `fromRegistryAttributes`), `buildFieldOptions` (grouped + 1-based indexed expansion for `repeated_*` kinds), `INDEXED_PATH_REGEX` (client-side free-text validation, operator directive 4)
- `src/components/FieldSelect.tsx` — Shared field picker (Mantine Combobox + InputBase; grouped options, free-text entry with 1-based validation, clearable). All four pickers (MappingTable, MatchFieldCombobox, RulesUI/RuleEditor, FilterUI) consume it over registry-with-feed-context (`useRegistryAttributes(scope.feedSourceId)`) so their lists are identical; run-triggering mutations (`useTriggerRun`, `useRunDryRun`) invalidate the `['registry', 'attributes']` query-key prefix (operator directive 3)
- `src/components/JsonSchemaForm.tsx` — Mantine-themed schema form renderer
- `src/components/StateViews.tsx` — `LoadingState`, `ErrorState`, `EmptyState`
