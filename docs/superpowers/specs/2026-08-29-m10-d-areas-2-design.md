# M10-d Frontend Design — Areas II + Plugin Infrastructure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the M10-d areas on top of the M10-b foundation and M10-c areas — Pipeline Editor (§4.5), Monitoring (§4.6), Export (§4.7), and plugin infrastructure (§3) — replacing the M10-c placeholders for these routes, so M10 ships end-to-end.

**Status:** Spec design phase. Backend (M10-a), foundation (M10-b), and areas I (M10-c) are complete. This design is the source of truth for the M10-d frontend implementation plan.

---

## 0. Context & resolved questions

### 0.1 What's already in place

- **Backend (M10-a, merged):** `GET /plugins`, `GET /feed-sources/{id}/pipeline`, `PUT /feed-sources/{id}/pipeline`, `GET /feed-sources/{id}/export-history`, `GET /feed-sources/{id}/export-history/{version}/diff?against=N`, `POST /feed-sources/{id}/export-history/{version}/rollback`, `GET/PUT /plugins/{id}/config|data`, `PUT /plugins/{id}/enabled`. Demo plugin `plugins/example_upper/` already copied. All 422 errors return `{"errors": [...]}`.
- **Foundation (M10-b, merged):** Mantine v9.5.2, TanStack Form/Table/Query pinned, i18n (en+de, 11 namespaces), theme, router + guard, AppShell with **dynamic plugin nav already wired** (renders `usePlugins().data` items as nav), shared `LoadingState`/`EmptyState`/`ErrorState`, `ConfirmModal` with `typeToConfirm` (M10-c), `CopyField`, `JsonSchemaForm` (Mantine-themed JSON Schema renderer), `withLoadingNotification`.
- **Areas I (M10-c, merged):** Login (autofocus), Dashboard, Setup (settings + mapping tabs), Products. Router already routes `pipeline`/`monitoring`/`export`/`plugins/:id` to placeholders. Those placeholders are removed in Task 4.
- **Carried-forward minors disposition:** M10-c plan §329 noted: guard-redirects-on-any-error, plugin nav scope routing, `PLUGIN_ICONS` registry, logout onError, 401 handler session reset, PluginPlaceholder literal, `useRunTransitionNotifier` single-mount, >500 kB chunk, node types. Of these, the M10-d design addresses: **plugin nav scope routing** (§3 below), **plugin icons** (§3), **logout onError** (TBD, M10-d or later), **chunk size** (M10-d adds three areas, no new heavy deps; existing chunk split acceptable).

### 0.2 Decisions made during brainstorming (2026-08-29)

1. **Scope:** Single plan, 4 tasks (infra → pipeline → monitoring → export+integration).
2. **Plugin pages:** Auto-rendered `JsonSchemaForm` only. No build-time `import.meta.glob` registry (deferred until a plugin ships a custom component).
3. **Pipeline Editor UX:** Palette (left) + dnd-kit sortable workspace (right) + collapsible registry panel.
4. **Monitoring:** 3 separate routes (`/monitoring/runs`, `/monitoring/findings`, `/monitoring/dry-run`) with a default redirect from `/monitoring`.
5. **Export:** Single page with inline diff (two Selects, field-based table grouped by product).
6. **Plugin enable toggle:** Lives in the Pipeline Editor registry panel (not a separate `/plugins` page).
7. **Demo plugin:** `plugins/example_upper/` shipped in Task 1 (already exists; just needs `frontend` manifest key verified).

### 0.3 Open questions (not blocking; resolve during implementation)

- Should the Pipeline Editor show a "schema preview" before adding an instance? — Defer to Task 2; if trivial, ship; else skip.
- Should the Dry Run form have a "save as preset" feature? — No, MVP only.
- Should Export history pagination be added? — No, MVP assumes fits on one page (small N for MVP).

---

## 1. Backend endpoints (verified, M10-a, no new work)

All endpoints below are already implemented per M10-a. M10-d consumes them only.

### 1.1 Plugins

- `GET /plugins` → `[{id, name, version, enabled, manifest: {...}, used_by_feed_sources: N}]`
  - `manifest.config_schema` is a JSON Schema object; `manifest.data_schema` for data-scope plugins.
  - `manifest.frontend` (optional): `{menu_item: string, icon: string}` — icon is a tabler icon name.
  - `manifest.extension_point` ∈ `pipeline_module` | `data` | `config` | etc.
  - `manifest.config_scope` / `data_scope` (optional): `'client'` | `'feed_source'` | `'global'` | list of those; missing means `'global'`.
- `GET /plugins/{id}/config?client_id=&feed_source_id=` → `Record<string, any>` (current config or `{}`).
- `PUT /plugins/{id}/config?client_id=&feed_source_id=` body=`config` → updated config; 422 `{"errors": [...]}`.
- `PUT /plugins/{id}/enabled` body=`{enabled: bool}` → updated plugin row; 409 when disabling an in-use plugin (or returns the row + the frontend does the confirm; **verify in M10-a route**).
- (Same for `/data` instead of `/config` for data-scope plugins.)

### 1.2 Pipeline (M10-a, spec §8)

- `GET /feed-sources/{id}/pipeline` → `{"instances": [{"position": int, "plugin_id": str, "name": str, "configuration": object}]}`
- `PUT /feed-sources/{id}/pipeline` body=`{instances: [{plugin_id, name, configuration}]}` → full-replace; 422 `{"errors": [...]}` on unknown/disabled/non-pipeline plugin, or invalid `configuration` against `validate_config`.

### 1.3 Export (M10-a)

- `GET /feed-sources/{id}/export-history` → `[ExportVersionOut]` with per-version `findings: {critical, warning, info}` (or `0` for rollback-source versions — **verify M10-a behavior**), `source: "scheduled"|"manual"|"rollback"`.
- `GET /feed-sources/{id}/export-history/{version}/diff?against=N` → `DiffOut {version, against, added: [product_id], removed: [product_id], changed: [DiffProductOut{product_id, fields: [DiffFieldOut{field, old, new}]}]}`. Always field-based, never line-based.
- `POST /feed-sources/{id}/export-history/{version}/rollback` → 204; creates a new version with `source="rollback"`.

### 1.4 Monitoring (M10-a)

- `GET /feed-sources/{id}/ingestion-runs?limit&offset` → `IngestionRunOut[]`
- `GET /feed-sources/{id}/quality-findings?run_id=` (optional) → `{ingestion_run_id, counts, findings}`
- `POST /feed-sources/{id}/dry-run` body=`{limit?: int}` → run results (per M10-a D4)

---

## 2. Plugin infrastructure (frontend)

### 2.1 Scope

The foundation already provides dynamic plugin nav (M10-b) and the `JsonSchemaForm` component. M10-d adds the plugin page itself, the config/data hooks, the enable/disable mutation, and ships the demo plugin manifest `frontend` block.

### 2.2 New hooks (`src/api/hooks.ts`)

```ts
usePlugins() // exists from M10-c (used by AppShell nav)

useUpdatePluginEnabled(): UseMutationResult<PluginInfo, ApiError, { id: string; enabled: boolean }>
// invalidates: queryKeys.plugins

usePluginConfig(pluginId: string, scope: { clientId?: number; feedSourceId?: number }): UseQueryResult<Record<string, unknown>>
// queryKey: ['plugin-config', pluginId, scope] (new)
// enabled: !!pluginId

useSavePluginConfig(pluginId: string, scope): UseMutationResult<Record<string, unknown>, ApiError, Record<string, unknown>>
// PUT /plugins/{id}/config?client_id=&feed_source_id=
// invalidates: ['plugin-config', pluginId, scope]
```

### 2.3 New query keys (`src/api/queryKeys.ts`)

```ts
pluginConfig: (pluginId, scope) => ['plugin-config', pluginId, scope ?? {}] as const
```

### 2.4 Route → component wiring

- `/plugins/:pluginId` → `<PluginPage pluginId scope={{}} />` (global)
- `/clients/:clientId/plugins/:pluginId` → `<PluginPage pluginId scope={{clientId}} />`

The page reads `useParams` to get `pluginId`, `clientId`, and derives `scope`:
```ts
const scope = useMemo(() => {
  if (clientId) return { clientId: Number(clientId) };
  return {};
}, [clientId]);
```

When the route also includes a feedSourceId, the scope expands:
```ts
if (feedSourceId) scope.feedSourceId = Number(feedSourceId);
```

(The spec routes plugins only to global + client; the `feed_source_id` extension is a small forward-compat hook — no feed-source-scoped plugins exist today, but the API supports it.)

### 2.5 `PluginPage` component

- Loads the plugin manifest via existing `usePlugins()` (no extra fetch).
- Loads the current config via `usePluginConfig(pluginId, scope)`.
- Renders a `<Title order={3}>{manifest.name}</Title>`, a short description from `manifest.description` (if present), and a `JsonSchemaForm` bound to:
  - `schema`: `manifest.config_schema` (or `manifest.data_schema` for data-scope — **decide based on `extension_point`**)
  - `defaultValues`: query data or `{}`
  - `onSubmit`: `useSavePluginConfig.mutate(values)`
- States: `LoadingState` while query pending, `EmptyState` if no schema, `ErrorState` + retry on error.
- 422 `errors` rendered per-field by `JsonSchemaForm` (already supported in M10-b).
- Success → `notifySuccess(t('plugin.configSaved'))` and query invalidation.
- Error → `notifyMutationError(error, t('plugin.saveFailed'))`.

### 2.6 AppShell dynamic nav (already in M10-b; verified in M10-d)

The M10-b AppShell already renders plugin nav items from `usePlugins().data` filtered by `enabled` and `manifest.frontend.menu_item`. Task 1 verifies the wiring still works with the demo plugin's `frontend` manifest key and fixes anything broken.

### 2.7 Demo plugin manifest update (Task 1)

Verify `plugins/example_upper/manifest.json` (or equivalent) includes:
```json
"frontend": {"menu_item": "Example Upper", "icon": "letter-e"}
```
If not present, add it. (The M10-a plan §40 says to add this; the M10-d Task 1 implementation verifies and adds if missing.)

### 2.8 i18n additions

- `en/plugins.json` + `de/plugins.json` new keys: `title`, `configSaved`, `saveFailed`, `noSchema` (used by `PluginPage`).
- `en/common.json` + `de/common.json`: add any new shared strings (none expected).

---

## 3. Pipeline Editor (§4.5)

### 3.1 Scope

Pipeline Editor per feed source. Three sub-views on one page: **palette**, **workspace** (dnd-kit sortable), **registry panel** (plugin enable/disable).

### 3.2 New hooks

```ts
useFeedSourcePipeline(feedSourceId: number | string): UseQueryResult<{ instances: PipelineInstanceOut[] }>
// queryKey: queryKeys.feedSource(feedSourceId).pipeline (new)
useSavePipeline(feedSourceId): UseMutationResult<... , ApiError, { instances: PipelineInstanceIn[] }>
// invalidates: feedSource(feedSourceId).pipeline, plus export-related keys if config_hash changes (handled by backend next-run, not frontend)
```

### 3.3 Pipeline state management

- **Server snapshot** held in `useFeedSourcePipeline`. On `data`, populate local state.
- **Local state**: `{ instances: LocalInstance[] }` where `LocalInstance = { clientId: string; plugin_id: string; name: string; configuration: object }`. The `clientId` is a stable id (e.g. `useId()` or a `crypto.randomUUID()`) for dnd-kit keys.
- **Dirty**: deep-equal of local vs server. (Use a small `isEqual` helper; `JSON.stringify` is acceptable for MVP given the small N — N is bounded by the number of enabled pipeline modules, typically <20.)
- **Save**: `useSavePipeline.mutate({ instances: local.map(toServerInstance) })`.
- **Reset**: `setLocal(serverData.instances.map(toLocal))`.
- **Navigation warning**: `useBlocker` from `react-router` (v7) when dirty. Block: "You have unsaved pipeline changes. Leave anyway?"

### 3.4 `PipelinePage` layout

```
<Stack>
  <Group justify="space-between">
    <Title>{t('pipeline.title')}</Title>
    <Group>
      <Button variant="default" onClick={onReset} disabled={!dirty}>{tCommon('actions.cancel')}</Button>
      <Button onClick={onSave} loading={saving} disabled={!dirty}>{tCommon('actions.save')}</Button>
    </Group>
  </Group>
  <DndContext onDragEnd={onDragEnd}>
    <Grid>
      <Grid.Col span={3}><PluginPalette plugins={enabledPipelineModules} /></Grid.Col>
      <Grid.Col span={9}><PipelineWorkspace instances={local} /></Grid.Col>
    </Grid>
    <PluginRegistryPanel plugins={all} onToggle={onToggleEnabled} />
  </DndContext>
</Stack>
```

### 3.5 `PluginPalette`

- Lists enabled plugins with `extension_point === 'pipeline_module'` (filtered from `usePlugins()`).
- Each item: drag handle (or click to add) → adds to workspace.
- Each card: icon + name + "drag to add" hint.

### 3.6 `PipelineWorkspace`

- `SortableContext` with `verticalListSortingStrategy`.
- Each `PipelineInstanceCard` is a `useSortable` item.
- Empty state: "Drag a plugin from the palette to add it."
- When a card is added, expanded by default (user can collapse via Accordion).

### 3.7 `PipelineInstanceCard`

- `Accordion.Item` per instance: title = plugin name + position, panel = `JsonSchemaForm` bound to `instance.configuration` with `defaultValues = instance.configuration`.
- Delete button (with `ConfirmModal` — destructive style, no type-to-confirm).
- Drag handle: `IconGripVertical` from `@tabler/icons-react`.

### 3.8 `PluginRegistryPanel`

- `Accordion` (collapsed by default after first use, persisted via localStorage `pipeline.registryPanelOpen`).
- Lists ALL plugins (not just pipeline_module) with:
  - Icon + name + version
  - `Switch` bound to `enabled` → `useUpdatePluginEnabled`
  - If `used_by_feed_sources > 0` and user tries to disable → `ConfirmModal` with `typeToConfirm={String(used_by_feed_sources)}` to require typing the number.
  - Help text: "Disabling a plugin affects every client and feed source."

### 3.9 dnd-kit specifics

- `@dnd-kit/core@6.3.1` + `@dnd-kit/sortable@10.0.0` (already in M10-b deps).
- Palette → workspace: drop on workspace adds a new instance with default config (`{}`).
- Workspace reorder: dnd-kit sortable reorder.
- Cross-list drag (palette → workspace) uses `DndContext` with custom collision detection or a simple "if over.id === 'workspace', add".

### 3.10 i18n additions

- `en/pipeline.json` + `de/pipeline.json`: `title`, `palette`, `workspace`, `emptyWorkspace`, `addToWorkspace`, `instanceName`, `remove`, `unsavedChanges`, `registryPanel`, `registryHelp`, `disableWarning` (with `count` interpolation), `disableConfirm` (with `name` interpolation), `saved`, `saveFailed`.
- The `common.actions.save/cancel` are reused from M10-b.

### 3.11 Tests (Task 2)

- `PipelinePage.test.tsx`:
  - Renders title + palette + workspace + registry.
  - Drag from palette to workspace adds an instance (use dnd-kit test setup with `DndContext` + `dispatchEvent`).
  - Reorder updates `instances` array.
  - Per-instance `JsonSchemaForm` edit calls `onChange` on local state.
  - Save PUTs with full instance list; disabled when not dirty.
  - Reset restores server values.
  - Disable plugin in use (`used_by_feed_sources > 0`) → confirm modal with typeToConfirm.
  - Disable plugin NOT in use → direct toggle, no confirm.
  - Navigation blocker when dirty (mock `useBlocker`).
- `PluginRegistryPanel.test.tsx`: see above; also tests localStorage persistence of open/closed state.

---

## 4. Monitoring (§4.6)

### 4.1 Scope

Three independent routes (per §0.2 decision):
- `/clients/:clientId/feeds/:feedSourceId/monitoring` → `Navigate` to `/monitoring/runs` (default).
- `/clients/:clientId/feeds/:feedSourceId/monitoring/runs` → `<MonitoringRunsPage>`.
- `/clients/:clientId/feeds/:feedSourceId/monitoring/findings` → `<MonitoringFindingsPage>`.
- `/clients/:clientId/feeds/:feedSourceId/monitoring/dry-run` → `<MonitoringDryRunPage>`.

### 4.2 Hooks (already in M10-c; verified for M10-d)

- `useIngestionRuns(feedSourceId, { limit, offset })` (M10-c, exists).
- `useQualityFindings(feedSourceId)` (M10-c, exists).
- `useRunDryRun(feedSourceId)` (M10-c, exists).

### 4.3 `MonitoringRunsPage`

- Uses `useIngestionRuns` (default limit 50).
- `IngestionRunsTable`:
  - Columns: `started_at` (dayjs), `status` (Badge with color per status), `processed_count` (Intl), `failed_count` (Intl, red when > 0), `error_message` (truncated, expandable to full message + stack trace).
  - Expandable row: shows `error_message` + `statistics` JSON in a `Code` block.
  - Empty state: "No runs yet" with optional "Trigger run" button (M10-d: button is disabled in MVP — manual trigger is in M9, but no UI hook; do not add here).
  - Error state: retry.

### 4.4 `MonitoringFindingsPage`

- `useQualityFindings` (latest run by default; future: filter by run_id via `?run_id=` param — **deferred**).
- `FindingsTable`:
  - Columns: `severity` (Badge: critical=red, warning=yellow, info=blue), `code`, `field`, `message`, `product_id` (clickable → opens Products drawer? **deferred to M11**; M10-d just shows as text).
  - Filters: severity multiselect (All/critical/warning/info), rule (code) multiselect.
  - Aggregated by rule: optional collapse that groups by `code` with count + click to expand. **MVP: render flat; aggregation is a stretch goal in M10-d, may defer.**
  - Empty state: "No findings — all products pass quality checks."
  - Error state: retry.

### 4.5 `MonitoringDryRunPage`

- `DryRunForm`:
  - `NumberInput` for `limit` (prefill 100, min 1, max 1000 — backend caps at 50 per spec §1.3; UI cap at 1000 is misleading — **match backend cap at 50, prefill 100 → change prefill to 50 to match**, or document the prefill=100 as "request up to 100; backend may return fewer"). Per spec §0.6: "Dry-run full-pass latency accepted for MVP; UI prefills `limit=100`". Keep prefill=100, add help text "Backend may return fewer if a sample cap is reached." **Keep as-is per spec.**
  - Submit → `useRunDryRun.mutate({ limit })` → `withLoadingNotification` wrapper.
- `DryRunResults`:
  - Renders the run result: counts (passed/dropped with `plugin_id`), findings table (reuse `FindingsTable`).
  - Read-only.
  - Empty state: "Trigger a dry run to see results."

### 4.6 i18n additions

- `en/monitoring.json` + `de/monitoring.json`: keys for tabs (`runs`, `findings`, `dryRun`), column headers, severity labels, empty states, dry-run form labels and help text, error states.

### 4.7 Tests (Task 3)

- `MonitoringRunsPage.test.tsx`:
  - Renders rows from fixture.
  - Status badge color per status.
  - Expandable row reveals error_message.
  - Empty state, error state, loading state.
- `MonitoringFindingsPage.test.tsx`:
  - Renders findings with severity badges.
  - Severity filter narrows results.
  - Empty state, error state.
- `MonitoringDryRunPage.test.tsx`:
  - Form renders with `limit=100` default.
  - Submit calls POST with body `{limit: 100}` (or value entered).
  - Results render after successful response.
  - Loading notification shown during run.
  - 422 error surfaces (findings source failure or no observations).

---

## 5. Export (§4.7)

### 5.1 Scope

Single page (`/clients/:clientId/feeds/:feedSourceId/export`) with inline diff. Lists versions, then below shows the diff between two selected versions.

### 5.2 Hooks

- `useExportHistory(feedSourceId)` (M10-c, exists).
- `useExportVersionDiff(feedSourceId, version, against?)` (new in M10-d):
  - `queryKey: queryKeys.feedSource(feedSourceId).exportDiff({version, against})`
  - `enabled: version !== undefined && against !== undefined`
- `useRollbackToVersion(feedSourceId)` (new in M10-d):
  - `POST /feed-sources/{id}/export-history/{version}/rollback`
  - Invalidates: `useExportHistory` key.

### 5.3 `ExportPage` layout

```
<Stack>
  <Title>{t('export.title')}</Title>

  <ExportUrlBlock ... />  // already from M10-c; reused

  <ExportVersionList
    versions={history}
    selectedA={versionA}
    selectedB={versionB}
    onSelectA={setA}
    onSelectB={setB}
    onRollback={setRollbackTarget}
  />

  <ExportVersionDiff
    versionA={versionA}
    versionB={versionB}
    diff={diff}
    loading={diffLoading}
  />
</Stack>
```

### 5.4 `ExportVersionList`

- Table with columns: `version` (number), `created_at` (dayjs), `source` (Badge: scheduled=blue, manual=teal, rollback=orange), `findings.critical` (red when >0), `findings.warning` (yellow when >0), `findings.info` (blue when >0).
- **Rollback-source rows** (`source === 'rollback'`) also show a "not QC'd" Badge (gray) in a separate column. The finding counts are 0 (QC didn't run) — the badge prevents misreading as "clean".
- Row has two radio inputs: "A" and "B" to select versions for diffing. Default A = latest, B = previous (latest-1).
- Row has a "Rollback to this version" button → opens `RollbackConfirmModal`.

### 5.5 `ExportVersionDiff`

- Renders `DiffOut` from the diff endpoint.
- Grouped by product: `Accordion` with one `Accordion.Item` per changed product (use `changed.map(p => p.product_id)` as keys). Plus a summary of `added` and `removed` product IDs as `Alert`s.
- Per-product fields: simple `Table` with columns: `field` (str), `old` (Code or Text), `new` (Code or Text). Render `old → new` with a `→` arrow. NEVER line-based.
- Empty state (when `added`, `removed`, `changed` all empty): "No changes between these versions."
- Loading state: `LoadingState`.
- Error state: `ErrorState` + retry.

### 5.6 `RollbackConfirmModal`

- `ConfirmModal` (danger, with `typeToConfirm` for the version number — e.g. "Type `42` to confirm"):
  - Title: `t('export.rollbackConfirmTitle')`
  - Body: "Rolling back to version {N} will create a new version with `source='rollback'`. The new version is append-only and has not passed quality checks. This action cannot be undone."
  - Confirm: calls `useRollbackToVersion.mutate({ version })`.
  - Success: notify + close + invalidate export history.

### 5.7 i18n additions

- `en/export.json` + `de/export.json`: extend M10-c keys with `versions`, `selectA`, `selectB`, `rollbackToVersion`, `notQcd`, `findings.critical` (label), etc.; plus `rollbackConfirmTitle`, `rollbackConfirmBody` (interpolation), `rollbackSuccess`, `rollbackFailed`, `noChanges`, `diffGrouped` (interpolation for product count).
- Note: the existing `export.json` from M10-c has the `ExportUrlBlock` keys. M10-d extends.

### 5.8 Tests (Task 4)

- `ExportPage.test.tsx`:
  - Renders URL block + version list.
  - Rollback-source row shows "not QC'd" badge.
  - Default selection: A = latest, B = previous.
  - Selecting different versions updates the diff query.
  - Diff renders changed/added/removed groups.
  - Rollback button opens confirm modal; typeToConfirm requires exact match.
  - Confirm calls POST and invalidates history.
- `ExportVersionDiff.test.tsx`: separate component test.
  - Renders field-based table.
  - Empty diff shows empty state.
- `RollbackConfirmModal.test.tsx`: covered via page test or separate.

---

## 6. Final integration (Task 4)

### 6.1 Router cleanup

Remove the four placeholders (`PipelinePlaceholder`, `MonitoringPlaceholder`, `ExportPlaceholder`, `PluginPlaceholder`) from `placeholders.tsx` and wire the real pages:

- `pipeline` → `<PipelinePage>` (from Task 2)
- `monitoring` → redirect to `monitoring/runs` (from Task 3)
- `monitoring/runs` → `<MonitoringRunsPage>` (from Task 3)
- `monitoring/findings` → `<MonitoringFindingsPage>` (from Task 3)
- `monitoring/dry-run` → `<MonitoringDryRunPage>` (from Task 3)
- `export` → `<ExportPage>` (from Task 4)
- `clients/:clientId/plugins/:pluginId` → `<PluginPage>` (from Task 1)
- `plugins/:pluginId` → `<PluginPage>` (from Task 1)

### 6.2 AppShell dynamic nav verification

The M10-b AppShell renders plugin nav from `usePlugins()`. With the demo plugin's `frontend` manifest key, "Example Upper" should appear in the nav. Test asserts this. If the icon mapping is missing, add the `letter-e` tabler icon to the icon map.

### 6.3 Full M10 DoD pass

- All 84 M10-c tests still pass.
- New M10-d tests pass (Pipeline, Monitoring runs/findings/dry-run, Export, PluginPage, etc.).
- `npm test -- --run && npm run typecheck && npm run build` is green.
- Backend tests remain green (no backend changes).
- Manual smoke (deferred to runtime): every route renders, every mutation round-trips, diff renders correctly, dry-run returns results.

### 6.4 Decisions to record (in `docs/decisions.md`)

- dnd-kit `@dnd-kit/core@6.3.1` + `@dnd-kit/sortable@10.0.0` used for Pipeline Editor (per spec).
- Monitoring split into 3 routes instead of `?tab=` (brainstorming decision; consistent with deep-linkability).
- Export diff as inline section (brainstorming decision).
- Plugin enable toggle lives in Pipeline Editor registry panel (spec compliant; brainstorming confirmed).
- Demo plugin manifest `frontend` block verified present in Task 1.

---

## 7. File plan

### Task 1 (Plugin infra)

```
plugins/example_upper/manifest.json   (MODIFY: verify/add frontend key)
frontend/src/
├── api/
│   ├── hooks.ts                       (MODIFY: add useUpdatePluginEnabled, usePluginConfig, useSavePluginConfig)
│   ├── queryKeys.ts                   (MODIFY: add pluginConfig key)
│   └── hooks.plugin.test.tsx          (NEW: tests for the 3 hooks)
├── app/router.tsx                     (MODIFY: route /plugins/:id and /clients/:cid/plugins/:id to PluginPage)
├── features/
│   ├── plugin/PluginPage.tsx          (NEW)
│   ├── plugin/PluginPage.test.tsx     (NEW)
│   └── placeholders.tsx               (MODIFY: remove PluginPlaceholder)
└── public/locales/{en,de}/plugins.json  (CREATE or MODIFY)
```

### Task 2 (Pipeline Editor)

```
frontend/src/
├── api/
│   ├── hooks.ts                       (MODIFY: add useFeedSourcePipeline, useSavePipeline)
│   ├── queryKeys.ts                   (MODIFY: add feedSource(id).pipeline key)
│   ├── types.ts                       (MODIFY: add PipelineInstanceOut, PipelineInstanceIn)
│   └── hooks.pipeline.test.tsx        (NEW)
├── features/
│   ├── pipeline/PipelinePage.tsx              (NEW)
│   ├── pipeline/PipelinePage.test.tsx         (NEW)
│   ├── pipeline/PluginPalette.tsx             (NEW)
│   ├── pipeline/PluginPalette.test.tsx        (NEW)
│   ├── pipeline/PipelineWorkspace.tsx         (NEW)
│   ├── pipeline/PipelineInstanceCard.tsx      (NEW)
│   ├── pipeline/PipelineInstanceCard.test.tsx (NEW)
│   ├── pipeline/PluginRegistryPanel.tsx       (NEW)
│   ├── pipeline/PluginRegistryPanel.test.tsx  (NEW)
│   ├── pipeline/registryPanelState.ts         (NEW: localStorage helper)
│   └── placeholders.tsx                       (MODIFY: remove PipelinePlaceholder)
└── public/locales/{en,de}/pipeline.json       (CREATE)
```

### Task 3 (Monitoring)

```
frontend/src/
├── features/
│   ├── monitoring/MonitoringLayout.tsx        (NEW: shared header for the 3 pages)
│   ├── monitoring/MonitoringRunsPage.tsx      (NEW)
│   ├── monitoring/MonitoringRunsPage.test.tsx (NEW)
│   ├── monitoring/MonitoringFindingsPage.tsx   (NEW)
│   ├── monitoring/MonitoringFindingsPage.test.tsx (NEW)
│   ├── monitoring/MonitoringDryRunPage.tsx    (NEW)
│   ├── monitoring/MonitoringDryRunPage.test.tsx (NEW)
│   ├── monitoring/IngestionRunsTable.tsx       (NEW)
│   ├── monitoring/FindingsTable.tsx            (NEW)
│   ├── monitoring/DryRunForm.tsx               (NEW)
│   ├── monitoring/DryRunResults.tsx            (NEW)
│   └── placeholders.tsx                        (MODIFY: remove MonitoringPlaceholder)
└── public/locales/{en,de}/monitoring.json      (CREATE)
```

### Task 4 (Export + integration)

```
frontend/src/
├── api/
│   ├── hooks.ts                       (MODIFY: add useExportVersionDiff, useRollbackToVersion)
│   ├── queryKeys.ts                   (MODIFY: add feedSource(id).exportDiff key)
│   └── hooks.export.test.tsx          (NEW)
├── features/
│   ├── export/ExportPage.tsx                  (NEW)
│   ├── export/ExportPage.test.tsx             (NEW)
│   ├── export/ExportVersionList.tsx           (NEW)
│   ├── export/ExportVersionList.test.tsx      (NEW)
│   ├── export/ExportVersionDiff.tsx           (NEW)
│   ├── export/ExportVersionDiff.test.tsx      (NEW)
│   ├── export/RollbackConfirmModal.tsx        (NEW)
│   ├── placeholders.tsx                       (MODIFY: remove ExportPlaceholder)
│   └── setup/ExportUrlCard.tsx                (M10-c; reused via ExportPage)
├── app/router.tsx                     (MODIFY: wire all 4 areas' routes)
└── public/locales/{en,de}/export.json        (MODIFY: extend with version/diff/rollback keys)
```

---

## 8. Sequencing (4 tasks)

| Task | Scope | Files | Verification |
|------|-------|-------|--------------|
| 1 — Plugin infra | Hooks, PluginPage, demo plugin manifest, i18n | 6+ files | typecheck + build + 8+ tests |
| 2 — Pipeline Editor | Hooks, dnd-kit UI, registry panel, dirty tracking | 11+ files | typecheck + build + 10+ tests |
| 3 — Monitoring | 3 routes, 3 tables, dry-run form | 11+ files | typecheck + build + 12+ tests |
| 4 — Export + integration | Version list, inline diff, rollback, final router wiring, full M10 DoD pass | 9+ files | typecheck + build + 8+ tests |

Each task: TDD (RED-GREEN-REFACTOR), full gate (`npm test -- --run && npm run typecheck && npm run build`), review checkpoint, `main` green after every merge.

---

## 9. Testing strategy (per AGENTS.md, spec §5)

- **Component tests:** Vitest + Testing Library + jsdom, fetch stubbed via `src/test/fetch.ts` (existing pattern, no new mocking library).
- **dnd-kit tests:** use `DndContext` with `dispatchEvent` or the official testing helpers; if no clean API, use `@testing-library/user-event` with custom pointer events.
- **Router tests:** use `MemoryRouter` with `initialEntries`; the existing pattern in `LoginPage.test.tsx` works.
- **Notifications tests:** `notifications.clean()` in `beforeEach` to prevent leakage (M10-c lesson).
- **i18n acceptance:** typecheck (typed keys) + targeted tests for key presence; manual switch verified in browser (deferred to runtime per spec).
- **DoD minimums (spec §5):** column-config persistence (M10-c, already met), pipeline-builder dirty tracking (M10-d, Task 2), schema-form rendering (M10-b, already met), notification on mutation failure (M10-b, already met), diff-view rendering (M10-d, Task 4), auth route guards (M10-b, already met).

---

## 10. Open risks

- **dnd-kit in jsdom:** drag-drop testing is notoriously fiddly in jsdom. If dnd-kit testing becomes a blocker, Task 2 plan includes a fallback: test the underlying state-mutation functions (add/reorder/remove) directly, plus a single end-to-end test that dispatches synthetic dnd events. DoD says "pipeline-builder dirty tracking" — state-mutation coverage is sufficient.
- **Tabler icon for demo plugin:** `letter-e` may not exist in `@tabler/icons-react@3.46.0`. Task 1 verifies and adds a fallback in the icon map if missing.
- **Diff endpoint `against` semantics:** The route accepts `?against=N` (optional). If absent, M10-a presumably diffs against the previous version — **verify in M10-a service**. If it errors, the frontend always sends `against`.
- **Plugin enable 409 vs 200:** M10-a may or may not return 409 on disable-in-use. Frontend uses confirm regardless; if backend returns 409 with a clearer message, frontend should display it.

---

## 11. Self-review (post-write)

- **Placeholder scan:** no TBDs. Dry-run cap behavior flagged in §4.5. Open questions listed in §0.3.
- **Internal consistency:** §3.3 state model matches §3.4 layout matches §3.11 tests. §5 hooks match §5.3 layout. File plan §7 covers all components mentioned in §3-5.
- **Scope check:** 4 tasks, each well-bounded. Plugin infra is foundational; Pipeline depends on it; Monitoring/Export are independent. Single plan matches spec §6.
- **Ambiguity check:**
  - "Pipeline Editor registry panel" → §3.8 specifies it lives in `PipelinePage` not a separate route.
  - "Default diff selection" → §5.4 specifies A=latest, B=previous.
  - "typeToConfirm for disable warning" → §3.8 specifies requiring the number.
  - "Dry-run prefill 100" → §4.5 keeps per spec, documents cap behavior in help text.
