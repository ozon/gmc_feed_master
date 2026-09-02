# M11e Dnd-pair Design (TODO 1.3, 1.4)

**Date:** 2026-09-02 · **Branch:** `m11e-dnd` (from main `ad65fcc`) · **Scope decided by owner:** the pipeline-dnd P2 pair 1.3 + 1.4, frontend-only, 2-task cycle.

## §1 Task 1 — stable dnd-kit instance ids (TODO 1.3)

### §1.1 Problem
`PipelinePage.tsx` mints fresh random ids in two places: `toLocal` (`generateLocalId()` — used for hydration, the `serverSnapshot` memo, and `onReset`) and `dndUtils.addInstance` (`generateId()`). Every save→refetch and every reset regenerates all `clientId`s, so React remounts every `PipelineInstanceCard` (key churn) and layout animations re-fire.

### §1.2 Design (binding)
Id derivation becomes deterministic from server identity: `clientId = ${plugin_id}-${position}`.

**`dndUtils.ts`:**
- `addInstance(instances, plugin)` → `clientId = ${plugin.id}-${instances.length}` (append position = next free index, same scheme as server identity).
- DELETE `generateId()` (no remaining caller in the file).
- `reorderInstances` / `removeInstance` / `isInstancesEqual` / `stripClientIds` — UNCHANGED.

**`PipelinePage.tsx`:**
- `toLocal(instances)` → `clientId = ${instance.plugin_id}-${instance.position}`.
- DELETE `generateLocalId()`.
- `toServer(instances)` → normalize `position` to array index: `instances.map(({ clientId: _clientId, ...rest }, index) => ({ ...rest, position: index }))`. Rationale: after a local reorder the array order and stale `position` fields disagree; without normalization, save → refetch → `toLocal` would re-derive ids from the stale positions, producing ids that disagree with what the user just saw (animation churn returns through the back door). Normalizing makes saved pipelines round-trip stable ids.

**Uniqueness argument (v2 — amends the flawed v1 after Task 1 review):** v1 claimed `instances.length` only reuses a FREED index; false — `removeInstance` does not renormalize positions (TODO 1.3 acceptance mandates remove preserve ids; the existing `removeInstance` test pins stale positions), so after removing an earlier item, `instances.length` can equal a SURVIVOR's held index. Repro: hydrate `[p1@0, p2@1]` → remove `p1-0` → append p2 → v1 mints `p2-1`, duplicating the held id (duplicate React keys; `removeInstance('p2-1')` filters out BOTH). **Fix (binding):** `addInstance` starts at `instances.length` and BUMPS the suffix past any held clientId (`while (taken.has(\`${plugin.id}-${index}\`)) index += 1`, where `taken` is the Set of current clientIds). The mint stays a pure function of list state (deterministic), all existing assertions still hold (`p2-1` onto `[a]`, double-append `p-0`/`p1-1`, freed-index reuse when unheld), and a held id is never duplicated. Renormalizing positions on remove was REJECTED: it violates the TODO's own acceptance ("removeInstance preserve existing clientIds") and the pinned existing test. Round-trip note: after a remove+append, save normalizes positions (`toServer`) and refetch re-derives ids from server truth — ids legitimately change across a non-no-op reload; stability is only promised for unchanged lists.

### §1.3 Test changes (`dndUtils.test.ts`)
- UPDATE existing `addInstance` test: assert `result[1].clientId` is `'p2-1'` (appending plugin p2 to `[a]` → index 1) instead of `not.toBe('')`. This is the RED line: today the id is a random uuid.
- NEW: "addInstance mints deterministic ids" — `addInstance(addInstance([], p), p)` → clientIds `p-0`, `p-1` (same plugin twice is legal).
- NEW: "reorder and remove preserve ids" — `reorderInstances([a,b,c],0,2)` keeps each item's own `clientId` (just moved); `removeInstance([a,b,c],'b')` leaves `a` and `c` ids intact; `addInstance(removeInstance(...), p)` reuses the freed index only when unheld.
- NEW (v2, the duplicate-id regression test): remove `p1-0` from `[p1-0, p2-1]`, append p2 → `['p2-1', 'p2-2']` (the bump-past-held fix; RED against v1 code, which mints the duplicate `p2-1`).

No `PipelinePage.test.tsx` changes in Task 1 (page-level id derivation is covered by Task 2's interaction test asserting the minted id renders).

### §1.4 Doc-sync
None — `frontend/docs/architecture.md` describes the workspace as "local React state" (unchanged); id-minting detail is below doc granularity. No i18n changes.

## §2 Task 2 — palette → workspace interaction test (TODO 1.4)

### §2.1 Problem
No test exercises the full `DndContext` → `onDragEnd` → `addInstance` wiring (PipelinePage.tsx:74-89). dndUtils unit tests cover pure list ops only.

### §2.2 Design (binding)
Two layers, one per TODO-sanctioned mechanism:

**Layer 1 — pure handler logic (flake-free):** extract `onDragEnd`'s decision logic into `dndUtils.ts` as a pure function:

```ts
export function applyDragEnd(
  instances: LocalInstance[],
  event: { active: { id: string | number; data?: { current?: unknown } }; over: { id: string | number } | null },
): LocalInstance[] | null
```

Returns the next instance list for a palette→workspace drop, or `null` when the event is a non-palette drop / workspace reorder / no target. `PipelinePage.onDragEnd` becomes a thin wrapper: `const next = applyDragEnd(local, event); if (next) setLocal(next);` — preserving exact current behavior (palette branch appends; workspace-reorder branch must ALSO be handled by applyDragEnd or left in the wrapper — binding: move BOTH branches into `applyDragEnd`; the wrapper is only the setLocal plumbing. The reorder branch needs the `local` closure list, which `applyDragEnd` already receives as `instances`).

Note: the real dnd-kit `DragEndEvent` carries more runtime fields than this structural type; the parameter is typed structurally (no `as DragEndEvent` cast needed at the call site — dnd-kit's event is assignable to the structural shape).

**Layer 2 — one real pointer-path smoke test (the full wiring):** render `<PipelinePage />` via the file's existing `renderAt()`, then perform a real dnd-kit pointer drag: `userEvent` pointer sequence on `palette-card-upper` (pointerDown → move ≥4px (PointerSensor activation distance) over the workspace → pointerUp). Assert `pipeline-instance-upper-0` appears in the workspace. This testid only exists with Task 1's deterministic ids — the assertion proves the ENTIRE path: DndContext sensors → plugin data extraction → applyDragEnd → addInstance('upper-0') → render.

### §2.3 Test changes
- `dndUtils.test.ts`: +1 "applyDragEnd" unit test — palette event object `{ active: { id: 'palette-upper', data: { current: { source: 'palette', plugin: { id: 'upper', name: 'Upper' } } } }, over: { id: 'workspace-droppable' } }` → appends `upper-0`; workspace-reorder event returns the reordered list; null `over` → `null` return (no state change).
- `PipelinePage.test.tsx`: +1 interaction test (Layer 2).

### §2.4 Flake protocol (binding)
The pointer test may flake under concurrent load — solo re-run before diagnosing; 3 consecutive solo greens = accept (documented repo pattern). If it flakes SOLO 2+ times: delete the pointer test, keep Layer 1's unit test plus a render-only wiring assertion (that the DndContext wrapper and palette render), and record the fallback invocation in the cycle log — this is the TODO's own "or directly invoke the onDragEnd handler" clause realized.

## §3 Order & rationale
Task 1 first: Task 2's assertions depend on Task 1's stable ids (`pipeline-instance-upper-0` only exists with deterministic ids). Same-file sequencing (`PipelinePage.tsx` in both tasks), no parallel implementers.

## §4 Gates (both tasks)
- Frontend only: `npm test -- --run` — expected 171 after Task 1 (169 + 2 new dndUtils tests), 173 after Task 2 (+1 applyDragEnd unit, +1 pointer interaction) — plan pins these counts; `npm run typecheck`; `npm run build`; `git diff --check`.
- Backend untouched. No new i18n keys.
- `hooks.ts`-style purity: `dndUtils.ts` stays i18n-free and React-free (pure functions only).
