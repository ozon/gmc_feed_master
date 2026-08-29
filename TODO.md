# TODO — Follow-up tasks after M10

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Each item below is sized for a single subagent task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **For human readers:** This file is the working backlog. Tasks were collected from the M10-d final review (`docs/superpowers/sdd/progress.md`) and earlier carry-forwards. Each task is self-contained: it names the file(s), the change, the acceptance bar, and the references needed to start.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` complete · `[!]` blocked

**Priority legend:** P0 = should land before any new milestone · P1 = should land before the next M10-followup work · P2 = nice to have

---

## Section 1 — Frontend correctness (M10 review carry-overs)

### 1.1 [ ] Centralize 422 per-field + summary notification in one helper [P1]

**Why:** The 422 errors summary notification pattern was applied in three places by hand (`PluginPage.tsx`, `PipelinePage.tsx`, `ExportPage.tsx`). All three follow the same shape: branch on `error instanceof ApiError && error.errors && error.errors.length > 0`, call `notifyError` with a joined message, fall through to `notifyMutationError` otherwise. The drift is real — `PluginPage` only counts errors, the others join them. One helper would prevent future drift.

**Files:**
- Create: `frontend/src/app/notifyApiError.ts` — single helper
- Modify: `frontend/src/app/notifications.ts` (re-export or co-locate)
- Modify: `frontend/src/features/plugin/PluginPage.tsx` (use helper)
- Modify: `frontend/src/features/pipeline/PipelinePage.tsx` (use helper)
- Modify: `frontend/src/features/export/ExportPage.tsx` (use helper)
- Modify: `frontend/src/features/monitoring/MonitoringDryRunPage.tsx` (already uses `withLoadingNotification`; verify pattern is consistent)
- Test: `frontend/src/app/notifyApiError.test.ts`

**Acceptance:**
- New helper signature (suggested): `notifyApiError(error: unknown, fallback: string, fieldErrorsKey?: string): void`
- Always surfaces a notification. When `error.errors` is non-empty, joins them into one toast. When only `error.detail` exists, surfaces the detail.
- Returns a per-field-errors map `Record<string,string>` for callers that want to render field-level messages (e.g. `PluginPage`'s `JsonSchemaForm`).
- Existing tests for all 4 pages still pass; behavior unchanged from the user perspective.
- New helper test: ApiError with `errors[]` → joins + returns map; ApiError with `detail` only → surfaces detail; plain Error → uses fallback; non-Error → uses fallback.

**Reference:** `frontend/src/app/notifications.ts:14-20` (current `notifyMutationError`), the three call sites above.

---

### 1.2 [ ] Plugin enable toggle: handle backend 409 response explicitly [P2]

**Why:** `PluginRegistryPanel.tsx` shows a `ConfirmModal` (typeToConfirm) before calling `useUpdatePluginEnabled({id, enabled: false})`. The plan §3.8 notes the backend may return 409 on disable-in-use; the current implementation has no error path for that 409 (it would fall through to the generic mutation error).

**Files:**
- Modify: `frontend/src/features/pipeline/PluginRegistryPanel.tsx` (or a wrapper hook)
- Test: existing `PluginRegistryPanel.test.tsx`; add a 409 case

**Acceptance:**
- When the mutation returns 409, show a notification: "Plugin is in use by N feed sources. Cannot disable." (reuse the `inUse` i18n key).
- No state change on error: the Switch reverts to its previous value (currently it stays at the user-clicked value because we mutate optimistically without rollback).
- Add the new translation key to en/de `pipeline.json`.

**Reference:** `frontend/src/api/hooks.ts` (`useUpdatePluginEnabled`), `backend/app/routes/plugins.py` for the 409 contract (verify whether the backend actually returns 409; if not, this is moot — record the finding and skip).

---

### 1.3 [ ] PipelinePage: use stable dnd-kit instance ids derived from `plugin_id + position` [P2]

**Why:** `PipelinePage.tsx`'s `toLocal` and `toServer` regenerate fresh `clientId`s on every reset and on every save→refetch. dnd-kit keys churn, which means Mantine's internal layout animations re-fire each time. A stable id derived from `plugin_id + position` would be stable across normal lifecycle (add/remove mint new ids; reorder and reset keep ids).

**Files:**
- Modify: `frontend/src/features/pipeline/PipelinePage.tsx`
- Modify: `frontend/src/features/pipeline/dndUtils.ts` (add a `toLocalStable` helper or change `addInstance` to mint from `plugin_id + index`)
- Test: `frontend/src/features/pipeline/dndUtils.test.ts` (verify stable id generation)

**Acceptance:**
- `addInstance` returns an instance with `clientId = ${plugin.id}-${index}` (or similar deterministic scheme).
- `reorderInstances` and `removeInstance` preserve existing `clientId`s.
- On a server refetch, `toLocal` re-uses the server `position` to derive the same id, so a no-op reload does not change dnd-kit keys.
- `dndUtils.test.ts` adds a "stable id" test.
- All existing dndUtils and PipelinePage tests still pass.

**Reference:** `frontend/src/features/pipeline/PipelinePage.tsx:17-30` (`toLocal`/`toServer`/id generation).

---

### 1.4 [ ] dnd-kit interaction test for palette → workspace add [P2]

**Why:** Plan §3.11 calls for a "drag from palette to workspace" interaction test. The current dndUtils unit tests cover state mutations, but no test exercises the full `DndContext` → `onDragEnd` → `addInstance` path. A single smoke test would catch regressions in the wiring.

**Files:**
- Modify: `frontend/src/features/pipeline/PipelinePage.test.tsx`

**Acceptance:**
- One new test renders `<PipelinePage />` inside a `DndContext` + `RouterProvider` test wrapper.
- Simulates a drag from a palette card to the workspace (use `@testing-library/user-event` pointer events; or directly invoke the `onDragEnd` handler exposed for testing).
- Asserts a new instance card appears in the workspace.
- Existing 2 tests still pass; no flaky behavior.

**Reference:** `frontend/src/features/pipeline/PipelinePage.tsx:64-75` (the `onDragEnd` handler), dnd-kit testing docs (Context7) for the exact pointer-event sequence.

---

### 1.5 [ ] `useExportVersionDiff` queryKey sentinels: drop the `-1` placeholders [P2]

**Why:** `frontend/src/api/hooks.ts:392-394` uses `version: version ?? -1, against: against ?? -1` as the query key when `enabled: false`. Benign in practice (the query never runs), but the sentinel values are arbitrary and could collide with a real version `-1` if the backend ever allowed it. Use a discriminated key shape that omits undefined fields.

**Files:**
- Modify: `frontend/src/api/queryKeys.ts` (allow the `exportDiff` key to take `undefined` and produce a stable "disabled" key)
- Modify: `frontend/src/api/hooks.ts` (`useExportVersionDiff` key generator)
- Test: existing `hooks.export.test.tsx` (the "does not fetch when version is undefined" test still passes)

**Acceptance:**
- When both `version` and `against` are undefined, the key is `['feed-source', id, 'export-diff', {disabled: true}]` or similar — explicit, not a sentinel.
- When one is defined and the other is not, the key reflects that asymmetry.
- Existing tests pass; new behavior is documented in a JSDoc (one line only, repo permits doc comments on exported types per the project exception — verify this exception in AGENTS.md first; if not permitted, leave undocumented).

**Reference:** `frontend/src/api/hooks.ts:386-402` (`useExportVersionDiff`), `frontend/src/api/queryKeys.ts` (`exportDiff` key factory).

---

### 1.6 [ ] `useRollbackToVersion`: also invalidate the diff query [P2]

**Why:** After a rollback, a new version is prepended. If the user has a diff displayed (A=old_latest, B=previous), the visible diff is technically still accurate (against the two version numbers they selected), but the default-selection `useEffect` will run with the new versions array and pick new A/B; the cached diff for the user's current selection may be stale until React Query re-fetches.

**Files:**
- Modify: `frontend/src/api/hooks.ts` (`useRollbackToVersion`'s `onSuccess`)
- Test: existing `hooks.export.test.tsx` (add invalidation assertion)

**Acceptance:**
- `useRollbackToVersion`'s `onSuccess` invalidates both `queryKeys.feedSource(id).exportHistory` and `queryKeys.feedSource(id).exportDiff` (the latter with a wildcard — React Query supports invalidating all keys matching a prefix).
- The test asserts `invalidateQueries` is called with the exportHistory key AND with a key that matches the exportDiff prefix.

**Reference:** `frontend/src/api/hooks.ts:404-413` (current `useRollbackToVersion`).

---

## Section 2 — Backend follow-ups (from M10-d implementer flags)

### 2.1 [ ] Backend: add `findings` and `url` to `ExportVersionOut` to match spec §4.7 [P1]

**Why:** The M10 spec (`docs/superpowers/specs/2026-08-28-m10-frontend-design.md` §4.7) says `ExportVersionOut` includes `findings: {critical, warning, info}` (so the frontend can show per-version finding counts in the version list). The actual backend response (`backend/app/schemas/export.py:9-19`) has only `product_count` and no `findings`. The frontend was built to match the backend (commit `981c32d` in M10-d), but the spec is the binding document. Closing this gap means the frontend can show the planned per-version QC summary.

**Files:**
- Modify: `backend/app/schemas/export.py` (add `findings: ExportFindingCounts | None` to `ExportVersionOut`; `url: str | None`)
- Modify: `backend/app/services/export.py` (compute findings from `QualityFinding` rows for the run that produced this version; populate `url` from `ExportFileStore.published_path`)
- Test: `backend/tests/test_export_history.py` (add tests for the new fields; verify default `None` for rollback-source versions since QC didn't run)

**Acceptance:**
- For `source='run'` versions: `findings` is non-null with counts sourced from the latest `QualityFinding` rows for that run; `url` is the public export URL of the latest version.
- For `source='rollback'` versions: `findings` is `null` (or `0/0/0`); `url` is the rollback's URL.
- The frontend's current code path (which already handles `findings: undefined` gracefully per the review) will start showing the per-version findings without further frontend change.
- New tests run in the existing test suite; `pytest -n auto` passes.

**Reference:** `backend/app/schemas/export.py:9-19`, `backend/app/services/export.py`, `docs/superpowers/specs/2026-08-28-m10-frontend-design.md` §4.7.

---

### 2.2 [ ] Backend: extend `ExportVersionOut.source` to the 3-value enum from the spec [P2]

**Why:** The spec says `source ∈ {scheduled, manual, rollback}` (3 values). The backend currently writes only `'run'` and `'rollback'` (verified in `backend/app/services/export.py:135,301`). The frontend now matches the backend (M10-d `981c32d`). If the backend is extended to distinguish scheduled vs manual runs, the frontend's `source.run | source.rollback` whitelist needs to expand and the i18n needs a third key.

**Files (frontend, conditional on backend change):**
- Modify: `frontend/src/features/export/ExportVersionList.tsx` (extend source enum)
- Modify: `frontend/public/locales/{en,de}/export.json` (add `source.scheduled` and `source.manual` keys)

**Acceptance:**
- This task is **deferred** until the backend decides whether to keep the 2-value `'run'/'rollback'` enum or expand to the 3-value spec. File a backend question: ask before implementing. If backend stays at 2 values, this task is moot.

**Reference:** `backend/app/services/export.py:135,301`, spec §4.7.

---

### 2.3 [ ] Backend: IngestionRun 90-day retention (spec §4 line 73, §10 line 284) [P1]

**Why:** The spec mandates a 90-day retention purge for `ingestion_runs` (StagingHistory 90-day retention is already implemented in `app/staging/purge.py`). Currently `ingestion_runs` grows unbounded. The natural home is the daily system purge job (`system-staging-purge`, `0 3 * * *`). Three RESTRICT FKs reference `ingestion_runs` (`staging_products.ingestion_run_id`, `quality_findings.ingestion_run_id`, `export_runs.ingestion_run_id` nullable). A purge must resolve dependents first.

**Files:**
- Modify: `backend/app/staging/purge.py` (add `purge_expired_ingestion_runs`; pick a dependent-resolution strategy)
- Modify: `backend/app/scheduler/registry.py` (or wherever `system-staging-purge` is registered — register the new purge alongside)
- Migration: new Alembic revision for the purge index/column if needed (likely none — table already exists)
- Test: `backend/tests/test_purge_ingestion_runs.py` — covers the dependent-resolution strategy

**Open question (resolve before implementing):** What happens to `export_runs.ingestion_run_id` for runs older than 90 days? Three options:
1. `NULL` the column on purge (preserves the export run record; export history is independent of ingestion retention).
2. Delete `export_runs` whose `ingestion_run_id` is being purged (loses history; reject).
3. Block purge for any run that still has `export_runs` pointing to it (default-deny).

Owner decision needed. Document the choice in `backend/docs/decisions.md` when implemented.

**Acceptance:**
- New purge job runs daily at the same time as the staging purge.
- Purge respects 90 days; respects the chosen dependent-resolution strategy.
- `pytest -n auto` green; M9 acceptance suite still green.

**Reference:** `backend/app/staging/purge.py` (existing staging purge), `backend/docs/decisions.md`, spec §4 line 73.

---

## Section 3 — M10-b carry-forwards

### 3.1 [ ] 401 handler: reset session query on 401 [P1]

**Why:** The centralized 401 handler in `frontend/src/api/client.ts` navigates to `/login` but does not reset the `queryKeys.session` query. After a 401, the next page that reads the session may see a stale "authenticated" value until the next refetch. The plan noted this in the M10-b carry-forwards.

**Files:**
- Modify: `frontend/src/api/client.ts` (in the 401 handler registered via `setUnauthorizedHandler`)
- Test: `frontend/src/api/client.test.ts` (add a 401 → session reset test)

**Acceptance:**
- On 401, the handler calls `queryClient.removeQueries({ queryKey: queryKeys.session })` (or `setQueryData(session, null)`) before navigating.
- The login page renders without flicker after a 401.
- The session query is reset even if navigation is to the same page.

**Reference:** `frontend/src/api/client.ts:42-48` (current handler), `frontend/src/api/hooks.ts:52-60` (`useSession`).

---

### 3.2 [ ] Guard redirects: handle 503 (and other errors) with ErrorState, not silent redirect [P1]

**Why:** `RequireSession` in `frontend/src/app/router.tsx` redirects to `/login` only on `status === 'error'`. This conflates 401 (correct redirect) with 503 / network errors (should show `ErrorState` + retry). The plan flagged this in M10-b.

**Files:**
- Modify: `frontend/src/app/router.tsx` (`RequireSession` component)
- Test: `frontend/src/app/router.test.tsx` (new) — covers 401 → login, 503 → ErrorState + retry, network → ErrorState

**Acceptance:**
- When the session query returns 401: redirect to `/login` (current behavior).
- When it returns 503 or any other error: render `ErrorState` with a retry button.
- When the network request throws (offline): render `ErrorState` with a retry button.
- The retry button calls `refetch()` on the session query.

**Reference:** `frontend/src/app/router.tsx:26-41` (`RequireSession`).

---

### 3.3 [ ] Logout mutation: add `onError` notification [P2]

**Why:** `useLogout` in `frontend/src/api/hooks.ts` only invalidates the session on success. A network failure on logout leaves the user in a weird state (UI says logged out, server still has the cookie). The plan flagged this in M10-b.

**Files:**
- Modify: `frontend/src/api/hooks.ts` (`useLogout`'s `onError`)
- Test: existing test (add an error-path test)

**Acceptance:**
- On logout error, show a `notifyMutationError(error, t('logoutFailed'))` notification.
- Still clear the local session query (the user clicked Log out — they expect to be logged out locally).
- Navigation: stay on the current page; the notification tells the user the server didn't acknowledge the logout.

**Reference:** `frontend/src/api/hooks.ts:150-159` (`useLogout`), `frontend/src/app/notifications.ts`.

---

### 3.4 [ ] Plugin nav routing: route by `manifest.config_scope` / `data_scope` [P1]

**Why:** The current AppShell renders ALL plugin nav items as `/plugins/:pluginId` (global). The spec says plugins declaring `'client'` in `config_scope` should route to `/clients/:clientId/plugins/:pluginId` (scoped to the current client). The plan flagged this in M10-b as a carry-forward.

**Files:**
- Modify: `frontend/src/app/AppShell.tsx` (nav rendering)
- Test: existing `AppShell.test.tsx`

**Acceptance:**
- For each plugin in `usePlugins().data`: read `manifest.config_scope` and `manifest.data_scope`. If `'client'` is in the scopes, the nav link points to `/clients/${clientId}/plugins/${pluginId}`. Otherwise `/plugins/${pluginId}` (global).
- When no client is selected, client-scoped plugins are hidden from the nav (they have no `clientId` context).
- The route component `PluginPage` already reads `clientId` from `useParams` — no change there.

**Reference:** `frontend/src/app/AppShell.tsx` (nav rendering), spec §3.

---

### 3.5 [ ] `PluginIconMap`: real icon registry, not skeleton [P2]

**Why:** Current `PluginIconMap.ts` has 4 letter icons + a circle fallback. Plugins can declare any icon string; the spec implies a broader registry. The plan flagged this in M10-b.

**Files:**
- Modify: `frontend/src/components/PluginIconMap.ts` (expand the MAP)
- Test: existing test or new test (verify known names map to known icons, unknown names fall back)

**Acceptance:**
- Add at least 10 common icon names (`cog`, `database`, `tag`, `wand`, `shield`, `lock`, `link`, `mail`, `chart`, `transform`) mapped to their `@tabler/icons-react` equivalents.
- Document in `docs/decisions.md` that the icon registry is best-effort: unknown names fall back to `IconCircle`.
- Verify `@tabler/icons-react@3.46.0` actually exports the named icons (read the package's export map before adding each name).

**Reference:** `frontend/src/components/PluginIconMap.ts`, spec §3.

---

## Section 4 — Bundle / build hygiene

### 4.1 [ ] Code-split the frontend bundle (M10 chunk > 500kB warning) [P1]

**Why:** After M10, the production bundle is ~980kB minified / ~296kB gzipped. Vite warns about the >500kB threshold. The plan flagged this in M10-b and the warning persists. Manual chunks can reduce the entry chunk and let route-based code splitting load area-specific code on demand.

**Files:**
- Modify: `frontend/vite.config.ts` (add `build.rollupOptions.output.manualChunks`)

**Acceptance:**
- The main `dist/assets/index-*.js` chunk drops below 500kB minified.
- Each of the 4 areas (plugin, pipeline, monitoring, export) gets its own chunk loaded only when the user navigates to that area.
- Lazy-load the area pages via `React.lazy` + `Suspense` in `router.tsx` (or the equivalent in the data-router pattern).
- Full gate still green; no test regressions.
- Document the chunking strategy in `frontend/vite.config.ts` comments (one line — repo permits config comments).

**Reference:** `frontend/vite.config.ts`, Vite docs on `manualChunks` (Context7).

---

## Section 5 — Core plugin UIs (deferred from M10)

### 5.1 [ ] Core plugin-specific UIs: Labelizer / Category / Rules [P2, blocked on core plugin implementation]

**Why:** Design §3 last bullet: "Core-plugin-specific UIs (m10 §3.8 last bullet: Labelizer/Category/Rules screens) are **deferred** until the core plugins are built (owner decision, §0.2)." When the core plugins (labelizer, category, rules) are built, they will need their own UI screens with plugin-specific forms and views. Today those plugins don't exist.

**Status:** `[!]` Blocked on the core plugin implementation. When that work begins, create a new plan for these UIs following the same TDD + subagent-driven pattern used in M10-d. The plugin auto-form pattern in `PluginPage` is the starting point; the core-plugin UIs will likely need richer inputs (label multi-select, category tree, rule editor) and a custom JSX renderer on top of the JSON Schema form.

**Reference:** `docs/superpowers/specs/2026-08-28-m10-frontend-design.md` §3 (last bullet), `m10-frontend-instructions.md` §3.8.

---

## Section 6 — Test hygiene (carried from M10-d final review)

### 6.1 [ ] Newline-at-EOF pass for all new files in M10-d [P2]

**Why:** Vite/ESLint convention; the diff footer shows `\ No newline at end of file` on many new files. Not load-bearing, but visible to reviewers.

**Files:** all files created in M10-d tasks (Task 1-4). One file at a time, just add a trailing newline.

**Acceptance:**
- `git diff --check` returns no `No newline at end of file` warnings on the M10-d commits.
- No content changes (only the newline added).

**Reference:** M10-d final-review Minor #4 (missing newlines).

---

### 6.2 [ ] Centralize QueryClientProvider in test wrapper (fix double-wrap) [P2]

**Why:** `frontend/src/test/render.tsx` was extended in Task 1 to accept a `RenderOptions.wrapper`. Several test files manually wrap with `QueryClientProvider` AND pass it via the `wrapper` option — double-wrapping. Functionally fine (nested providers share state via the same `QueryClient` instance) but noisy.

**Files:**
- Modify: `frontend/src/test/render.tsx` (make `RenderOptions` cleaner; consider always wrapping with the test `QueryClient`)
- Modify: `frontend/src/features/pipeline/PipelinePage.test.tsx`, `frontend/src/features/monitoring/*.test.tsx`, `frontend/src/features/export/*.test.tsx` (drop the manual `QueryClientProvider` wrap if the test helper now provides it)
- Test: existing tests still pass

**Acceptance:**
- `render(ui, { wrapper: SomeComponent })` always wraps the tree once with the chosen `QueryClient` + `MantineProvider`. No double-wrap.
- Test files become shorter (no manual `<QueryClientProvider>` in each test).
- All existing tests still pass; no behavioral change.

**Reference:** `frontend/src/test/render.tsx`, M10-d final-review Minor #2.

---

## Section 7 — Documentation

### 7.1 [ ] Record M10-d decisions in `docs/decisions.md` [P1]

**Why:** The M10-d design doc (§7) listed 5 decisions to record: dnd-kit pinning, Monitoring 3 routes, Export inline diff, plugin enable toggle location, demo plugin manifest. M10-a/b/c recorded their decisions; M10-d did not.

**Files:**
- Modify: `docs/decisions.md` (or the equivalent — locate the existing decisions file)

**Acceptance:**
- Each of the 5 M10-d decisions has a one-line entry with a date and a short rationale.
- The decisions are placed in the correct section (likely "M10 frontend" or similar).
- No new file; only append to the existing decisions document.

**Reference:** M10-d design §7, M10-a/b/c decisions in `docs/decisions.md`.

---

## Section 8 — Backlog (longer-term)

### 8.1 [ ] M11+ scope planning [P0]

**Why:** M10 is done. M11+ requirements need to be gathered (from spec gaps, from the IngestionRun 90-day retention need, from Core plugin UIs, from any new business requirements). Without a plan, coding agents have no roadmap.

**Owner action:** Decide M11 scope. Options:
- M11a: Backend follow-ups (IngestionRun retention, ExportVersionOut findings/url, source enum expansion)
- M11b: Core plugin implementation (Labelizer, Category, Rules)
- M11c: New feature work (TBD by product)

**Acceptance:** A brainstorming session produces a new design spec; a plan follows; a new cycle begins. Until then, agents should pick from the tasks above — each is independently valuable.

---

## Working notes for the next agent

- **All tasks above are independent** — you can pick any `[ ]` and start. Tasks 1.1-1.6 are P1/P2 frontend quality work; Tasks 2.1-2.3 are backend spec gaps; Tasks 3.1-3.5 are M10-b carry-forwards; Task 4.1 is bundle hygiene; Task 7.1 is documentation. Task 8.1 is the meta-task.
- **M10 gate per task:** `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run && npm run typecheck && npm run build`. Backend tasks: `cd /home/ozon/gmc_feed_master && pytest -n auto` (requires `TEST_DATABASE_URL`).
- **Conventions** (binding): no comments in code; all strings via `t()`; en+de identical i18n trees; 422 errors summary notification; query-key invalidation; Loading/Empty/ErrorState on every data view.
- **M10-d lessons** (binding): TanStack Form dirty uses `form.Subscribe`; `notifications.clean()` in `beforeEach`; `beforeAll(loadNamespaces)` for non-default namespaces; `useBlocker` requires data router (`createMemoryRouter`+`RouterProvider` in tests); nullable fields in `plugin.manifest` need optional chaining.
- **Per-task workflow:** Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Each task is sized for a single subagent + reviewer cycle. After each task, merge to main and update `.superpowers/sdd/progress.md` (the SDD ledger; gitignored, lives on disk only).
- **Originals:** this file is derived from `.superpowers/sdd/progress.md` (M10-d final review + M10-b carry-forwards; gitignored, read it for full context). Specs at `docs/superpowers/specs/2026-08-29-m10-d-areas-2-design.md` and `docs/superpowers/specs/2026-08-28-m10-frontend-design.md`.

---

_Generated 2026-08-29 after M10-d merge (`aa86c10`). Total: 15 tasks across 8 sections, mixed P0/P1/P2 priorities. Last touch: M10-d decisions recorded at `6215c8f`._
