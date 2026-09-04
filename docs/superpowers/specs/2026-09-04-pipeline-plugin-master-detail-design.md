# Pipeline Page Plugin Master–Detail Rework — Design

Date: 2026-09-04
Status: Approved (brainstorming session)

## Problem

The per-feed-source pipeline page (`frontend/src/features/pipeline/PipelinePage.tsx`)
splits plugin handling across three areas: a drag-out palette (`PluginPalette`),
a workspace of instance cards (`PipelineWorkspace`/`PipelineInstanceCard`), and a
collapsed registry accordion with enable/disable switches
(`PluginRegistryPanel`). Plugin configuration is embedded in workspace cards,
there is no per-instance enable, and no at-a-glance overview of the pipeline.

## Goal

One master–detail layout on the pipeline page:

- **Left:** ordered plugin instance list — drag to reorder, per-instance
  enable/disable Switch, click to select; add-from-registry section; global
  registry toggles.
- **Right:** configuration of the selected instance (JSON-schema form).
- **Top:** overview strip with instance counts, enabled/disabled counts, and
  dirty state.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Which page | Rework `PipelinePage` (per feed source) |
| Left switch semantics | Per-instance enable (new flag) |
| Right pane edits | Pipeline instance configuration only |
| Adding plugins | Single source list — "add" buttons from registered `pipeline_module` plugins; drag-out palette removed |
| Overview form | Header strip (counts + dirty badge) |
| Per-instance enable persistence | Immediate `PATCH`, not part of Save |
| Global registry toggles | Live in the left list (third section), accordion retired |
| Drag library | `@dnd-kit/sortable` (existing dependency). Mantine 9 has no flat sortable list component — its native DnD is the hierarchical `Tree` component and `@mantine/schedule`; both are poor fits for a flat reorderable list. Mantine renders the rows. |

## Backend changes

### Schema (approved by operator)

- New column `module_instances.enabled` (`Boolean`, `nullable=False`,
  `default=True`, `server_default=true`) via Alembic autogenerate migration.

### API

- `GET /feed-sources/{id}/pipeline` — each instance gains `id` (DB primary key)
  and `enabled`.
- `PUT /feed-sources/{id}/pipeline` — instances accepted with optional `id`
  (present = update, absent = insert); rows missing from the payload are
  deleted. Replace delete-all-and-reinsert with **upsert-by-id** so instance
  ids stay stable across saves and PATCH targets never dangle.
  Validation rules (unknown plugin, disabled plugin, wrong extension point,
  `validate_config`) unchanged.
- `PATCH /feed-sources/{id}/pipeline/instances/{instance_id}` — body
  `{"enabled": bool}`. 404 when feed source or instance not found. Updates the
  row and the pipeline `definition` JSONB (which mirrors instances) so
  `definition` never contradicts the rows.

### Run behavior

- `resolve_config_bundle` (`backend/app/staging/config_resolver.py`) excludes
  instances with `enabled=false`. `PluginStep` therefore skips them naturally.
- The bundle feeds `config_hash`; a toggle changes the hash so the next run
  reprocesses products (correct delta semantics, no extra code).

## Frontend changes

All in `frontend/src/features/pipeline/`:

- `PipelinePage` — orchestrates `local` state, `hydrated`, dirty check,
  `useBlocker`, Save/Reset (unchanged semantics: reorder/add/remove/config
  edits go through Save). Holds `selectedId` for the detail pane; falls back
  to the first instance, cleared when the selected instance is removed.
  Layout: `Grid` span 4 (list) / span 8 (config).
- `PluginList` (new) — left pane. `SortableContext` + `useSortable` rows:
  drag handle, per-instance Switch (optimistic flip, rollback +
  `notifyApiError` on PATCH failure), name, selected-row highlight. Below the
  instance rows:
  1. **Add from registry** — compact rows for registered `pipeline_module`
     plugins not yet in the pipeline; click adds to the end of the local list.
  2. **Registry** — global enable/disable per plugin, same logic as
     `PluginRegistryPanel` today (409 `disableBlocked` message, type-to-confirm
     `ConfirmModal` for plugins in use by other feed sources).
- `PluginConfigPanel` (new) — right pane: header (instance name, plugin version
  badge, remove button) + `JsonSchemaForm` bound to
  `instance.configuration` via the existing `onChangeInstance` flow. Disabled
  instance: informational banner (does not run until enabled); form remains
  editable so configuration is preserved for re-enabling.
- `PipelineOverviewStrip` (new) — counts (total / enabled / disabled) and dirty
  badge; derived, stateless.
- `dndUtils` — `LocalInstance` gains `id: number | null` and `enabled:
  boolean`; `applyDragEnd` loses the palette-source branch.
- Deleted: `PluginPalette`, `PipelineWorkspace`, `PipelineInstanceCard`,
  `PluginRegistryPanel`, `registryPanelState` (+ their tests). Replaced by the
  components above.
- `frontend/src/api/types.ts` — `PipelineInstance` gains `id`, `enabled`.
- `frontend/src/api/hooks.ts` — new `usePatchPipelineInstance(feedSourceId)`
  mutation (`PATCH .../pipeline/instances/{instanceId}`, invalidates the
  pipeline query on success). `useSavePipeline` unchanged.

## Error handling

- PATCH failure: revert the local switch state, `notifyApiError`, refetch the
  pipeline query.
- Registry disable while in use: existing 409 handling and ConfirmModal flow.
- Save validation errors: unchanged (`saveFailedWithErrors`).

## Testing

- Backend:
  - Pipeline API tests: PATCH endpoint (enable/disable, 404s), GET returns
    `id`/`enabled`, PUT upsert keeps ids of untouched instances, deletes
    missing ones.
  - `resolve_config_bundle` / `PluginStep`: disabled instances excluded from
    the bundle and skipped at run time.
  - Existing migration patterns followed for the new column.
- Frontend (vitest + testing-library):
  - `PipelinePage.test.tsx` updated: select instance → config edits; toggle
    switch → PATCH called, rollback on failure; add from registry; reorder
    via drag simulation; remove.
  - New tests for `PluginList`, `PluginConfigPanel`, `PipelineOverviewStrip`.
- Commands: `uv run pytest -n auto`, `uv run ruff check .`, `uv run mypy .`
  (backend); `npm run test`, `npm run typecheck`, `npm run build` (frontend).

## Documentation (same change)

- `backend/docs/api.md` — PATCH endpoint, new instance fields, upsert
  semantics.
- `backend/docs/data-model.md` — `module_instances.enabled` column.
- `backend/docs/architecture.md` — disabled instances skipped in Module
  Runner stage.
- `frontend/docs/architecture.md` — pipeline page structure.

## Out of scope

- Scoped config API (three-tier merge) integration in this page — stays on
  `PluginPage`.
- Bulk enable/disable, search/filter of the registry list.
- Keyboard-accessible reordering (dnd-kit limitation; future up/down buttons
  if requested).
