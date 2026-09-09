# TODO — Follow-up tasks after M10

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Each item below is sized for a single subagent task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **For human readers:** This file is the working backlog. Tasks were collected from the M10-d final review (`docs/superpowers/sdd/progress.md`), earlier carry-forwards, and the 2026-08-30 cycle's final review. Each task is self-contained: it names the file(s), the change, the acceptance bar, and the references needed to start.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` complete · `[!]` blocked

**Priority legend:** P0 = should land before any new milestone · P1 = should land before the next M10-followup work · P2 = nice to have

---

## Cycle log

- **2026-09-09 (branch `main`, review-remediation plan `docs/superpowers/plans/2026-09-08-review-remediation.md`):** 13 tasks executed (Tasks 1–13; Task 14 eslint deferred per operator approval; Task 15 bookkeeping). Backend: B1 global-tier scope guard (403 for scoped users on global plugins), B7 422 detail propagation. CI: ruff pinned + baseline gate, mypy baseline gate. Infrastructure: alembic DATABASE_URL passthrough, Makefile plugin-test target, AGENTS path fix. Frontend: F1 hook-order crash fix, F2 diff empty-state spinner, F3/U2 save-error toasts (CustomLabelsUI), U1/F10+F11 honest toasts (rotateFailed + deleted), F5+F4 admin toggle errors + null-safe client_ids, F8+F9 NumberInput clamping + cron preset labels, U3/U4/U7/U8/U9 German i18n pass (Sie register, grammar, missing keys), U15 plural forms for count keys. Docs: RJSF ADR superseded, Rolldown adopted, stack lines fixed, proxy list updated, data-model/api refreshed to match code, makefile Caddy targets added. Gates (re-run 2026-09-09 with follow-ups): backend 923/923 after README doc-test fix (`114237f`; Task 12 had dropped `http://127.0.0.1:8000`), 924/924 after TODO 9A.13 fix (`1d42d45`), ruff zero-new at 505, mypy baseline 42 held; frontend 377/377 + typecheck + build clean. Reviews: Tasks 6, 7 approved by reviewer; Tasks 8–13 controller-verified inline (subagent rate limits). Head: `e2d31f6`. Post-cycle follow-ups: `114237f` README fix, `c8ebde9` TODO 9A.13 filing, `1d42d45` alembic URL-precedence fix (9A.13).

- **2026-09-07 (branch `main`, session convention):** labelizer polish cycle — closed every still-open minor + recommendation from the two 2026-09-05 labelizer final reviews, in 8 tasks (spec `docs/superpowers/specs/2026-09-07-labelizer-polish-design.md`, plan `docs/superpowers/plans/2026-09-07-labelizer-polish.md`). Backend: `merge_scopes` deleted (probe-verified zero production callers; tests now exercise `_resolve_declared`), equivalence fixture deduped into `backend/tests/labels_equivalence.py`, plugin module loaded once via `backend/tests/labels_plugin_module.py`, dead manifest dict-key check deleted (probe: sole entry is `json.loads`; empty-`{}` + non-string-key-value branches gained tests). Frontend: `mergeSlotIds` tracks `sourceTier` (inherited badge derives its tier instead of hardcoding `scope.client`), values-textarea aria-label localized, `activeRulesCount` pluralized (en+de), nowrap headers wrap, tier chains memoized, `usePreview` resets error at request start + clears result on 422, tests de-flaked, data-URL/badge assertions made exact (fix round: row-scoped badge assertions — the pre-click count was the ScopeContextBar badge), origin-key route integration test added. **Plan amendment (operator-approved):** Task 1's original "delete `preview.__annotations__` lines" step was REFUTED by experiment — under `from __future__ import annotations` the runtime assignments are load-bearing (removal breaks route registration, 4 tests fail); the cycle-2 "dead `__annotations__` line" minor was a mis-review; recorded in decisions.md. Per-task reviews clean (Task 7 needed one fix round: weak badge assertion strengthened to row-scoped). Final whole-branch review: ready to merge, 1 Important fixed pre-merge (`30970ae` — racy post-`waitFor` DOM read made event-driven) + decisions.md module-load sentence qualified. Gates: backend 885 passed; frontend 293 (1 known ProductsPage parallel-load flake, 12/12 solo) + typecheck + build clean; ruff zero new in touched files. Infra note: subagent sessions died mid-task twice (empty returns) — Tasks 1/2 final phases controller-executed with full verification; all other tasks subagent-driven. New backlog: Section 9.

- **2026-09-02 (branch `m11e-dnd`, fast-forward merged to main):** closed the pipeline-dnd pair, completing TODO section 1: TODO 1.3 (stable ids — spec v1's uniqueness argument was flawed; Task 1 review caught a real duplicate-id window after remove+append, fixed via spec v2 bump-past-held suffix + regression test `99ee4fc`) and TODO 1.4 (applyDragEnd extraction + pointer interaction test — two disclosed deviations approved: dead-guard omission per controller; pointer-sequence rewrite after user-event's `offset` proved to be caret semantics, replaced with `coords` + geometry spies). Final whole-branch review: one Important fixed pre-merge (`beb5459` — the plan dropped spec §2.3's reorder-branch unit test). Gates: frontend 176/176 + typecheck + build clean; backend untouched. Reviewer probed the backend PUT contract: positions were always re-enumerated server-side — no latent bug.

- **2026-09-01 (branch `m11d-micro`, fast-forward merged to main):** closed the export-hooks P2 pair: TODO 1.5 (exportDiff key factory union-typed — shared `{ disabled: true }` key replaces the `-1` sentinels; enabled key byte-identical) and TODO 1.6 (rollback also invalidates the export-diff prefix). Per-task reviews clean; Task 2 had one APPROVED deviation — the plan's `getQueryData → undefined` test mechanism was impossible on query-core 5.102.8 (invalidation never evicts observer-less data; verified against installed source), so the assertion uses the established `invalidateQueries` spy convention instead — briefs must stop proposing that mechanism. Final whole-branch review: merge-ready, no Critical/Important — 2 Minors filed as leftovers inside the 1.5/1.6 Done entries (prefix-matcher seed assertion; JSON.stringify key comparisons). Gates: frontend 169/169 + typecheck + build clean (reviewer re-verified first-hand); backend untouched.

- **2026-09-01 (branch `m11c-micro`, fast-forward merged to main):** closed the two m11b final-review carry-overs: TODO 1.9 (unified `mutateToggle` with one error handler across both toggle paths; stale-cache fast-path 409 now toasts) and TODO 1.10 (severity aria-labels on the findings badges, zero new strings). Per-task reviews clean; final whole-branch review: merge-ready, no Critical/Important — 2 Minors filed as leftovers inside the 1.9/1.10 Done entries (enable-error toast wording needs a future `enableFailed` key; span-aria-label SR robustness). Gates: frontend 168/168 + typecheck + build clean (reviewer re-verified); backend untouched.

- **2026-09-01 (branch `m11b-correctness`, fast-forward merged to main at `d9d5eab`):** executed TODO 1.2 (rescoped per owner: backend 409 on disabling a plugin in use by ≥1 feed source + frontend `disableBlocked`/`disableFailed` toast branch; 1.2's original premise — "verify whether the backend returns 409" — was false, the endpoint accepted any state), TODO 3.3 (`useLogout` `onSettled` clears session cache on success AND error; AppShell `onError` toast `errors.logoutFailed`), TODO 1.8 (ExportVersionList "Findings" column: three per-severity badges, gray-on-zero = clean, nothing for rollbacks), and the m11a ops follow-up (lifespan shutdown drain of manual-trigger background tasks, 10s monkeypatchable timeout, pending-warning, exception-logging done-callback; documented in architecture.md). Per-task reviews clean (3 forced brief-snippet fixes, all reviewer-verified: `.select_from` join, stub-detail removal ×2, `logoutAttempted` flag); final whole-branch review: merge-ready with 1 Important fixed pre-merge (architecture.md drain note — binding doc-sync policy). Gates on merged main: backend 662/662; frontend 166/166 + typecheck + build clean. New tasks 1.9, 1.10 filed from carried minors.

- **2026-08-31 (branch `m11a-p1s`, fast-forward merged to main at `457fc2f`):** executed Task-1 WIP landing (owner's manual run trigger: backend `POST /feed-sources/{id}/run` + `GET /feed-sources/{id}` + frontend button/hook; add-feed `source_url` input; Caddyfile.dev + `make dev-caddy`; uvicorn dep; ingest fix: bare structured columns parse as `kind='generic'` — spec §5.8 amended to match, owner decision), TODO 3.4 (plugin nav routes by `manifest.config_scope`/`data_scope`; client-scoped hidden without client), and TODO 1.7 (`RouteErrorBoundary` on the AppShell route with Reload for chunk-load failures). Per-task reviews clean; final whole-branch review: merge-ready with 2 Important fixed pre-merge (spec §5.8 sync, api.md `{run_id}` accuracy) + hoisted nav scope check. Gates on merged main: backend 657/657 (`pytest -n auto`, real PostgreSQL); frontend 160/160 + typecheck + build clean, no chunk-size warning. Follow-ups filed: background-task shutdown drain (DONE this cycle); ruff/mypy not installed in the backend dev group (baseline 430/45 pre-existing errors; pin+configure or drop the gates — ops task).

- **2026-08-30 (branch `m11-followups`, fast-forward merged to main at `4bdc3a8`):** executed 1.1, 2.1, 2.3, 3.1, 3.2, 4.1 via subagent-driven development (per-task reviews clean; final whole-branch review: merge-ready, no Critical). 7.1 turned out to be already complete (`6215c8f`). 3.4 was inadvertently omitted from the cycle's approved scope. New tasks 1.7 and 1.8 were added from the cycle's final review. Gates on merged main: backend 654/654 (`pytest -n auto`, real PostgreSQL); frontend 151/151 + typecheck + build clean, no chunk-size warning.

---

## Section 1 — Frontend correctness (M10 review carry-overs)

### 1.1 [x] Centralize 422 per-field + summary notification in one helper [P1]

**Done (2026-08-30, `676ed29`):** `frontend/src/app/notifyApiError.ts` exports `notifyApiError(error, fallback, errorsSummary?) → Record<string,string>` (surfaces the summary/joined toast; returns the colon-split per-field map) plus pure `mapFieldErrors` for render paths (no toast during render). Re-exported from `notifications.ts`. PluginPage/PipelinePage/ExportPage migrated; PluginPage's local `mapErrors` deleted. MonitoringDryRunPage verified: query-only failure path via `withLoadingNotification`, no 422 branch — no change needed. 10 new tests.

*Leftover (Minor, optional):* the convenience re-export creates a benign module cycle `notifications.ts ↔ notifyApiError.ts` (safe today — function declarations, live bindings, no module-scope calls). Co-locating the helper in `notifications.ts` would remove the hazard.

---

### 1.2 [x] Plugin enable toggle: handle backend 409 response explicitly [P2]

**Done (2026-09-01, `cdfb32d`+`d69fcf9`, m11b cycle):** premise rescoped per owner decision — the backend never returned 409 (the typeToConfirm modal was the only guard), so the cycle ADDED the 409: `_usage_count` helper (distinct feed-source join, same transaction as the flip) guards disable-only; detail is `"plugin in use by N feed source(s)"` with singular/plural. Frontend: `confirmToggle` per-call `onError` — 409 → `notifyError(t('disableBlocked', {count}))` using the panel's own `plugin.used_by_feed_sources` (no detail parsing); non-409 → `notifyMutationError(error, t('disableFailed'))`. No switch revert needed (server-state-driven, no optimistic update). api.md documents the 409. 5 new tests (3 backend, 2 frontend). TOCTOU accepted (defense-in-depth behind the modal). Fast-path `onChange` mutate still has no onError — Task 1.9.

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

### 1.9 [x] PluginRegistryPanel fast-path toggle: add `onError` toast [P2] — added 2026-09-01 (m11b final review)

**Done (2026-09-01, `619c145`, m11c cycle):** `mutateToggle(plugin, enabled)` unifies both mutate call sites (fast path + confirm path) behind the single m11b error handler (409 → `disableBlocked` with cached count; else `disableFailed`); `confirmToggle` clears `pendingToggle` before mutating. 1 new test (stale-cache fast-path 409 → toast shows the cached count 0, proving no detail parsing). Leftover (m11c final review, Minor): enable-path non-409 errors toast "Could not disable plugin." — file a `toggleFailed`/`enableFailed` key in a future cycle (blocked by the no-new-keys decision this cycle).

**Why:** `onChange`'s direct `toggleEnabled.mutate` (enable, or disable when the cache says unused) has no `onError`. If the plugins query is stale (plugin became used since fetch), the server's new 409 is silently swallowed — the switch stays correct (server-state-driven) but the user gets no feedback. Pre-existing for enable; asymmetric with the now-handled confirm path.

**Files:** `frontend/src/features/pipeline/PluginRegistryPanel.tsx` (extract the `confirmToggle` onError into a shared handler passed to both mutate calls); test: existing file.

**Acceptance:** both mutate call sites share one `onError` handler (409 → disableBlocked with the plugin's count, else disableFailed); a test covers the fast-path 409 (stale `used_by_feed_sources: 0`, server 409 → toast fires).

---

### 1.10 [x] Findings badges: add `aria-label` severity cues [P2] — added 2026-09-01 (m11b final review)

**Done (2026-09-01, `991393d`, m11c cycle):** all three badges carry `aria-label` using the same i18n expression as `title` (`findings.<severity>`, zero new strings); 1 new test asserts en-locale labels ("2 critical" / "0 warning" / "5 info"). Leftover (m11c final review, Minor): `aria-label` on Mantine Badge's generic `<span>` may be suppressed by some SR/browser combos (NVDA browse mode) — `role="img"` or visually-hidden text would be more robust; candidate follow-up.

**Why:** The m11b findings badges carry severity via color + `title` only. Per the accname computation, `title` on a non-interactive element is not reliably announced; screen readers get "2", "0", "5" with no severity. The m10 design sketch (§3) called for `aria-label`; the m11b spec's binding decision dropped it to title-only.

**Files:** `frontend/src/features/export/ExportVersionList.tsx` (add `aria-label={t('findings.<severity>', { count })}` — same i18n keys, zero new strings); test: existing file (assert `aria-label` present).

**Acceptance:** each badge has an `aria-label` naming severity + count; en+de reuse the existing `findings.*` keys; no i18n changes.

---

### 1.3 [x] PipelinePage: use stable dnd-kit instance ids derived from `plugin_id + position` [P2]

**Done (2026-09-02, `b54b538` + `99ee4fc` amendment, m11e cycle):** `toLocal` derives `${plugin_id}-${position}` from server data; `addInstance` mints `${plugin.id}-${instances.length}` with a bump-past-held suffix loop (amendment — v1's mint could duplicate a held id after remove+append; regression-tested); `toServer` index-normalizes positions so saved pipelines round-trip the same ids; both random id helpers deleted. Reviewer's PUT-contract probe: the backend was never trusting client positions (route re-enumerates), so normalization is payload self-consistency, not a bug fix — refetch stability comes from deterministic ids + backend contiguity. Note (final review, Minor): spec §1.2's toServer rationale overstates — harmless; positions on local cards can diverge from id suffixes after a bump (cosmetic, normalized on save).

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

### 1.4 [x] dnd-kit interaction test for palette → workspace add [P2]

**Done (2026-09-02, `a7f739a` + `beb5459`, m11e cycle):** `onDragEnd` logic extracted to pure `applyDragEnd(instances, event)` in dndUtils (palette-append + workspace-reorder branches; `null` = no state change); PipelinePage keeps a thin wrapper. Coverage: 3 unit tests (append, null cases, reorder branch — the last added in final review after the plan silently dropped spec §2.3's mandate) + 1 real pointer-path drag test (`palette-card-upper` → workspace asserts `pipeline-instance-upper-0` renders). Plan's pointer sequence was invalid (user-event `offset` is a caret offset, not pointer pixels; jsdom has zero rects) — implementer source-verified and used `coords` + getBoundingClientRect spies; approved deviation. Follow-up note: pointer test is coupled to dnd-kit geometry internals — revisit on any dnd-kit major bump (spec §2.4 fallback documented).

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

### 1.5 [x] `useExportVersionDiff` queryKey sentinels: drop the `-1` placeholders [P2]

**Done (2026-09-01, `bfc0159`, m11d cycle):** `exportDiff` key factory is union-typed — concrete `{ version, against }` when both defined (byte-identical to the old enabled key), else one shared `['feed-source', id, 'export-diff', { disabled: true }]` key; no `-1` anywhere. 1 new test proves the shared disabled key (two mixed-undefined renders → one cache entry). architecture.md key-structure line updated. Follow-up candidate (m11d final review, Minor): the disabled-key test's second render stays mounted — name carries the intent; JSON.stringify key comparisons in tests are cosmetic.

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

### 1.6 [x] `useRollbackToVersion`: also invalidate the diff query [P2]

**Done (2026-09-01, `45637ae`, m11d cycle):** rollback `onSuccess` additionally invalidates the literal prefix `['feed-source', id, 'export-diff']` (all diff keys for the feed source); existing history invalidation unchanged. Rollback test extended to assert both invalidations via the codebase's `invalidateQueries` spy convention — the plan's original `getQueryData → undefined` mechanism was factually impossible on query-core 5.102.8 (invalidation marks stale; it never evicts observer-less data). architecture.md invalidation row updated. Leftover (m11d final review, Minor): the spy proves the hook passes the prefix but not that query-core's prefix-matcher actually matches a concrete 4-element diff key — a seed + `find(diffKey)?.state.isInvalidated` assertion would close that gap.

**Why:** After a rollback, a new version is prepended. If the user has a diff displayed (A=old_latest, B=previous), the visible diff is technically still accurate (against the two version numbers they selected), but the default-selection `useEffect` will run with the new versions array and pick new A/B; the cached diff for the user's current selection may be stale until React Query re-fetches.

**Files:**
- Modify: `frontend/src/api/hooks.ts` (`useRollbackToVersion`'s `onSuccess`)
- Test: existing `hooks.export.test.tsx` (add invalidation assertion)

**Acceptance:**
- `useRollbackToVersion`'s `onSuccess` invalidates both `queryKeys.feedSource(id).exportHistory` and `queryKeys.feedSource(id).exportDiff` (the latter with a wildcard — React Query supports invalidating all keys matching a prefix).
- The test asserts `invalidateQueries` is called with the exportHistory key AND with a key that matches the exportDiff prefix.

**Reference:** `frontend/src/api/hooks.ts:404-413` (current `useRollbackToVersion`).

---

### 1.7 [x] Route error boundary for lazy chunk-load failures [P1] — added 2026-08-30 (final review)

**Done (2026-08-31, `5131ee8`):** `RouteErrorBoundary` in `frontend/src/app/router.tsx` — `isChunkLoadFailure` detects the Chrome/Safari/Firefox dynamic-import TypeError messages; boundary mounted as `errorElement` on the AppShell route (covers all 9 lazy pages); friendly message + Reload button (`window.location.assign(href)`); generic variant for non-chunk errors; no stack traces. i18n `errors.chunkLoadFailed/routeError/reload` in en+de common.json. 2 new tests via `createMemoryRouter` (default "Unexpected Application Error" UI asserted absent). Reviewer noted (Minor, plan-mandated): `errors.routeError` duplicates `state.error` strings; no top-level `errorElement` outside the AppShell subtree (LoginPage is eager, so not exposed).

**Why:** Task 4.1 moved all 9 feature pages into on-demand chunks. After any deploy, a stale open tab that navigates gets `Failed to fetch dynamically imported module` and react-router's built-in `DefaultErrorComponent` (raw "Unexpected Application Error!" + stack trace, no retry). This is now the most common user-visible error after every deploy; a reload always fixes it, so the UI should offer one.

**Files:**
- Modify: `frontend/src/app/router.tsx` (route-level `errorElement` or a small `RouteErrorBoundary` component offering a reload)
- Modify: `frontend/public/locales/{en,de}/common.json` (new keys for the error message + reload label; en+de identical)
- Test: `frontend/src/app/router.test.tsx` (simulate a lazy import rejection)

**Acceptance:**
- A chunk-load failure (dynamic `import()` rejection) renders a friendly error state with a Reload button (e.g. `window.location.assign(current location)`), not the default stack dump.
- The 401/session-guard behaviors from tasks 3.1/3.2 are unchanged.
- New test covers the rejection path; all existing tests pass.

**Reference:** `frontend/src/app/router.tsx` (lazy route components + `RequireSession`), react-router v7 `errorElement` docs (Context7).

---

### 1.8 [x] ExportVersionList: render per-version QC findings badges [P2] — added 2026-08-30 (split from 2.1)

**Done (2026-09-01, `e67baf3`, m11b cycle):** "Findings" column after Products — three `size="xs" variant="light"` badges per non-rollback version with `findings != null` (condition `version.source !== 'rollback' && version.findings != null`); colors red/yellow/blue when count > 0, gray on zero (0/0/0 reads "clean"); `title` tooltips via i18n (`findings.critical/warning/info` en+de); rollbacks render nothing (existing notQcd badge distinguishes them); `url` still unused. 3 new tests. Severity is color/title-only (a11y gap) — Task 1.10.

**Why:** 2.1's original acceptance claimed the frontend would show per-version findings "without further frontend change" — that was wrong. The backend now returns `findings: {critical, warning, info} | null` and `url` on every `ExportVersionOut` (spec §4.7), but `ExportVersionList` has no findings column; the data currently dead-ends in an unused optional type field.

**Files:**
- Modify: `frontend/src/features/export/ExportVersionList.tsx` (per-severity counts column)
- Modify: `frontend/public/locales/{en,de}/export.json` (column label and any count labels; en+de identical)
- Test: `frontend/src/features/export/ExportVersionList.test.tsx` (or the ExportPage test)

**Acceptance:**
- `source='run'` versions render critical/warning/info counts from `version.findings`.
- `source='rollback'` versions (`findings: null`) keep the existing "not QC'd" badge and show no counts (must not read as 0/0/0 "clean").
- `url` remains available for future use; no rendering required in this task.

**Reference:** spec `2026-08-28-m10-frontend-design.md` §4.7, `frontend/src/api/types.ts` (`ExportVersionOut`), `backend/app/schemas/export.py`.

---

## Section 2 — Backend follow-ups (from M10-d implementer flags)

### 2.1 [x] Backend: add `findings` and `url` to `ExportVersionOut` to match spec §4.7 [P1]

**Done (2026-08-30, `a48ffd6`):** `ExportVersionOut` gained `findings: ExportFindingCounts | None` and `url: str | None`. **Sourcing decision:** counts come from the joined `ExportRun`'s denormalized `critical/warning/info_finding_count` — NOT from `QualityFinding` rows (`persist_findings` deletes feed-keyed findings on every run, so older runs' rows no longer exist). `source='rollback'` → `findings=None` ("not QC'd", distinct from 0/0/0 "clean", per spec §4.7). `url` = `{public_base_url}/export/{export_token}.xml` (mirrors `routes/clients.py:56-57`), the feed source's current public URL on every row. Service layer (`list_versions`/`rollback`) returns Pydantic models via a shared `_version_out` helper; routes stay thin; frontend `types.ts` extended with optional fields only. Decision recorded in `docs/decisions.md` (2026-08-30). Frontend rendering is Task 1.8.

---

### 2.2 [x] Backend: extend `ExportVersionOut.source` to the 3-value enum from the spec [P2] — done 2026-09-09 (operator decision, 9A.12)

**Done:** `PipelineRunner.execute` gained a `trigger` param (manual default; `SchedulerService` registers jobs with `trigger="scheduled"`) plumbed through `StepContext` into `ExportService.export_for_run(source=...)`. Model default `'run'` → `'manual'` + migration `20260909_0001` (data-migrates `'run'` rows). `ExportVersionOut.source` is now `Literal["scheduled", "manual", "rollback"]` (`ExportSource`). Frontend: types narrowed to the 3-value union, `SOURCE_COLOR` per value, i18n `source.scheduled`/`source.manual` (en+de, `source.run` removed). Docs: data-model.md, api.md.

**Files (frontend, conditional on backend change):**
- Modify: `frontend/src/features/export/ExportVersionList.tsx` (extend source enum)
- Modify: `frontend/public/locales/{en,de}/export.json` (add `source.scheduled` and `source.manual` keys)

**Acceptance:**
- This task is **deferred** until the backend decides whether to keep the 2-value `'run'/'rollback'` enum or expand to the 3-value spec. File a backend question: ask before implementing. If backend stays at 2 values, this task is moot.

**Reference:** `backend/app/export/service.py:136,336`, spec §4.7.

---

### 2.3 [x] Backend: IngestionRun 90-day retention (spec §4 line 73, §10 line 284) [P1]

**Done (2026-08-30, `ccefd08`):** `purge_expired_ingestion_runs` in `backend/app/staging/purge.py` plus a second daily system job `system-ingestion-run-purge` (same `0 3 * * *` cron as the staging purge; `replace_existing=True` prevents double-registration). **Owner decision (2026-08-29):** NULL `export_runs.ingestion_run_id` on purge (option 1 — export history preserved; option 2 delete-export-runs was rejected). **Dependent-resolution strategy (single transaction):** candidates = runs with `started_at < now−90d`; runs still referenced by `staging_products.ingestion_run_id` are SKIPPED entirely (a feed's live staging state is never destroyed); for purged runs: NULL the export_runs FK → delete their `quality_findings` → delete the runs. Safe against running pipelines (a recent `started_at` is never a candidate); timezone-clean end-to-end. Decision + rationale recorded in `docs/decisions.md` (2026-08-30). Tests: `backend/tests/test_purge_ingestion_runs.py` (7 scenarios incl. protection, detach, rollback-NULL, empty tables) + lifespan registration assertion in `test_m9_lifespan.py`.

---

## Section 3 — M10-b carry-forwards

### 3.1 [x] 401 handler: reset session query on 401 [P1]

**Done (2026-08-30, `36eeaa3`):** `makeUnauthorizedHandler` in `frontend/src/app/router.tsx` calls `queryClient.removeQueries({ queryKey: queryKeys.session })` unconditionally (even when already on `/login`, before the navigation guard) and BEFORE `router.navigate(...)`, so a login-page `useSession` mount refetches instead of reading stale cache. `router.test.tsx` extended: invocation-order assertion (`invocationCallOrder`), already-on-login reset case, and an end-to-end 401 repro through the real App (redirect + login renders + cache `undefined`).

---

### 3.2 [x] Guard redirects: handle 503 (and other errors) with ErrorState, not silent redirect [P1]

**Done (2026-08-30, `f8874bb`):** `RequireSession` now branches: `error instanceof ApiError && error.status === 401` → unchanged `<Navigate to="/login" replace state={{ from }} />`; any other error (503, other statuses, network TypeError/offline) → `<ErrorState onRetry={() => void refetch()} />` with the default `state.error` message (no new i18n keys). Four new tests in `router.test.tsx`: 401→login, 503→ErrorState (not redirected), network rejection→ErrorState, retry→refetch→guarded content renders.

---

### 3.3 [x] Logout mutation: add `onError` notification [P2]

**Done (2026-09-01, `8819787`, m11b cycle):** `useLogout` `onSettled` → `removeQueries(session)` (clears local cache on BOTH success and error, matching `makeUnauthorizedHandler`'s remove-pattern; hooks.ts stays i18n-free). AppShell UserMenu mutate call keeps `onSuccess: navigate('/login')` + gains `onError: (error) => notifyMutationError(error, t('errors.logoutFailed'))` ("Log out failed on the server. You were logged out locally." / de equivalent). Stay-vs-redirect after a failed logout is server-state-driven (refetch → 401 handler navigates if the session is truly gone). 1 new test (seeded cache, failing logout, toast + cache-undefined assertions).

**Why:** `useLogout` in `frontend/src/api/hooks.ts` only invalidates the session on success. A network failure on logout leaves the user in a weird state (UI says logged out, server still has the cookie). The plan flagged this in M10-b.

**Files:**
- Modify: `frontend/src/api/hooks.ts` (`useLogout`'s `onError`)
- Test: existing test (add an error-path test)

**Acceptance:**
- On logout error, show a `notifyMutationError(error, t('logoutFailed'))` notification.
- Still clear the local session query (the user clicked Log out — they expect to be logged out locally).
- Navigation: stay on the current page; the notification tells the user the server didn't acknowledge the logout.

**Reference:** `frontend/src/api/hooks.ts:170` (`useLogout`), `frontend/src/app/notifications.ts`.

---

### 3.4 [x] Plugin nav routing: route by `manifest.config_scope` / `data_scope` [P1]

**Done (2026-08-31, `c29ba27`):** `AppShell.tsx` gained module-local `manifestScopes(manifest, key)` (safe normalization: string | string[] | malformed → string[]) and `isClientScoped(manifest)` (true iff `'client'` ∈ config_scope OR data_scope). Client-scoped plugins link `/clients/${clientId}/plugins/${pluginId}`; hidden from nav when no `clientId` in URL; everything else links `/plugins/${pluginId}` (scopeless manifests default global, matching backend `_parse_scope`). 5 new AppShell tests (real `href` assertions); 3 of the 5 new tests had coincidentally passed under old behavior — the RED state was carried by the other 2. `feed_source` scope deliberately does not affect nav routing.

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

### 4.1 [x] Code-split the frontend bundle (M10 chunk > 500kB warning) [P1]

**Done (2026-08-30, `4bdc3a8`):** `React.lazy` for the 9 feature pages (LoginPage + AppShell stay eager); vendor chunking via Vite 8/rolldown `build.rolldownOptions.output.codeSplitting.groups` — note `manualChunks` is REMOVED in Vite 8 (the original task text was stale). Entry `index-*.js` 980kB → 21kB; largest chunk `vendor-mantine` 376kB; Vite chunk-size warning gone; zero test edits; vendor-mantine CSS emitted and linked (no FOUC). Chunking strategy documented in `frontend/vite.config.ts` (one-line comment) + `docs/decisions.md` (2026-08-30). Follow-up: Task 1.7 (chunk-load error boundary).

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

### 7.1 [x] Record M10-d decisions in `docs/decisions.md` [P1]

**Done (pre-cycle, `6215c8f`, 2026-08-29):** all 9 M10-d decisions recorded under `## 2026-08-29` (dnd-kit pinning, Monitoring 3 routes, Export inline diff, plugin enable toggle location, demo plugin manifest, auto-form only, DiffOut shape, ExportVersionOut realignment, 422 pattern). The 2026-08-30 cycle appended further entries under `## 2026-08-30` (findings/url sourcing, retention purge strategy, chunking strategy).

---

## Section 8 — Backlog (longer-term)

### 8.1 [ ] M11+ scope planning [P0]

**Why:** M10 is done. M11+ requirements need to be gathered (from spec gaps, from the remaining follow-ups, from Core plugin UIs, from any new business requirements). Without a plan, coding agents have no roadmap.

**Owner action:** Decide M11 scope. Options:
- M11a: Backend follow-ups — IngestionRun retention and ExportVersionOut findings/url are DONE (2026-08-30); only the source enum expansion (Task 2.2) remains
- M11b: Core plugin implementation (Labelizer, Category, Rules) — unblocks Task 5.1
- M11c: New feature work (TBD by product)

**Acceptance:** A brainstorming session produces a new design spec; a plan follows; a new cycle begins. Until then, agents should pick from the tasks above — each is independently valuable.

---

## Section 9 — Labelizer polish cycle leftovers (2026-09-07 final-review triage, all BACKLOG)

### 9.1 [x] Sibling customLabels i18n keys lack plural forms [P2]

**Done (2026-09-09, `dd02d72`, review-remediation Task 11):** `matchedCount` and `shadowedCount` pluralized (en+de `_one`/`_other` pairs); `idCount` and `coverage.labeledOf` also pluralized. `slotLabeled` and `freshnessHint` no longer exist in the codebase (removed by the 2026-09-08 rule-card refactor).

**Acceptance:** `_one`/`_other` variants for each key, en+de; update tests asserting the old single-key strings.

### 9.2 [ ] usePreview disabled-path test: fake timers instead of the 1500ms blind sleep [P2]

**Why:** `usePreview.test.tsx`'s "sends no request when disabled" test sleeps 1500ms real time to prove no request fired (plan-mandated margin). Deterministic fake-timer control would remove the wall-clock dependency; risks `setTick`/debounce interplay — attempt only with the RTL-rerender-remounts lesson in mind.

### 9.3 [ ] `labels_equivalence.py`: copy instead of alias fixture rows [P2]

**Why:** `MERGED_SLOT_RULES` aliases rows of `GLOBAL_SLOT_RULES`/`CLIENT_SLOT_RULES` (read-only today, docstring guards it). A `copy.deepcopy` in construction would make cross-suite mutation structurally impossible.

### 9.4 [ ] Inherited-badge UI test cannot distinguish derived `sourceTier` from re-hardcode [P2, blocked]

**Why:** For custom_labels data tiers (`client` → `feed_source`), an inherited value can only originate at client — derived and hardcoded labels coincide by construction. A distinguishing test becomes possible only when a second scoped plugin or a third data tier adopts the pattern.

### 9.5 [ ] `manifest.py` `config_merge` key-check error message overstates [P2]

**Why:** After deleting the probe-justified `isinstance(key, str)` half, the message "config_merge keys must be non-empty strings" overstates `if not key:` for hypothetical non-JSON callers (a truthy non-string key would pass). Unreachable in production (`json.loads`); wording-only.

### 9.6 [ ] App-side plugin.py re-exec under `create_app(plugins_dir=...)` [P2]

**Why:** `backend/tests/labels_plugin_module.py` consolidated the two test-preamble loads, but `load_plugin_class` still execs `plugin.py` under `gmc_plugin_custom_labels` in tests that start the app with a `plugins_dir`. Test-only; the decisions.md entry now carries the "(test preambles...)" qualifier.

---

## Section 9A — Review remediation deferred findings (2026-09-09)

### 9A.1 [ ] U5 products-table keyboard/row activation path (a11y) [P2]

**Why:** UX a11y — products table lacks keyboard navigation and row activation. `docs/reports/2026-09-08-04-ux-i18n.md`.

### 9A.2 [ ] U6 raw enum values in tables/filters — translate via existing keys [P2]

**Why:** Raw enum values shown in tables/filters instead of translated labels. Same report.

### 9A.3 [ ] U12 NotFound route instead of silent redirect [P2]

**Why:** Missing route silently redirects instead of showing NotFound page. Same report.

### 9A.4 [ ] U11 disabled-nav tooltip when no feed source selected [P2]

**Why:** Nav items disabled without tooltip explaining why. Same report.

### 9A.5 [ ] U14 ProductDrawer dayjs locale + `drawerRawData` key [P2]

**Why:** ProductDrawer doesn't respect locale; missing i18n key. Same report.

### 9A.6 [ ] U16 ConfirmModal for unsaved-changes guards (replace `window.confirm`) [P2]

**Why:** `window.confirm` used for unsaved-changes prompts — should use ConfirmModal. Same report.

### 9A.7 [ ] U17 i18n a11y labels (pagination, user menu) [P2]

**Why:** Pagination and user menu lack i18n a11y labels. Same report.

### 9A.8 [ ] U18 localized lead-in for raw server error details [P2]

**Why:** Raw server error details shown without localized lead-in text. Same report.

### 9A.9 [ ] F6 ProductsPage state reset on feed-source change [P2]

**Why:** ProductsPage state not reset when feed source changes. `docs/reports/2026-09-08-03-frontend.md`.

### 9A.10 [ ] F13 deep-link page strip; F14 usePreview deps/unmount; F15 toggle rollback scope; F16 ProductsTable dead code; F17 raw_data heading; F18 MonitoringLayout dead code [P2]

**Why:** Multiple frontend minors from the review. Same report.

### 9A.11 [ ] T6 Caddyfile parameterized document root; T11 compose restart policy; T12 Caddy encode/headers; T13 engines field + committed .nvmrc [P2]

**Why:** Deployment hardening items. `docs/reports/2026-09-08-05-tooling.md`.

### 9A.12 [x] Operator questions: enable/disable toggle admin-gating (B1 follow-up), U10 terminology pick, TODO 2.2 source enum [P2] — answered 2026-09-09

**Decisions:**
1. **Admin-gate `PUT /plugins/{id}/enabled`** — registry-wide state affecting every client's feeds, same cross-tenant class as B1's global-tier writes (`backend/app/routes/plugins.py:139` currently `require_user` only).
2. **U10: "Mandant"** is the German term for client — sweep `Kunde*` out of all de/ namespaces.
3. **TODO 2.2: expand to the 3-value spec enum** — `source ∈ {scheduled, manual, rollback}` per spec §4.7; backend stops writing `'run'`; frontend whitelist + en/de i18n keys expand.

### 9A.14 [ ] T7 frontend eslint adoption — blocked by typescript-eslint × TypeScript 7 [P2]

**Why:** Plan Task 14 (`docs/superpowers/plans/2026-09-08-review-remediation.md:1461`) specifies eslint + typescript-eslint + react-hooks rules. Attempted 2026-09-09 (operator re-approved): `typescript-eslint@8.70.0` hard-fails at import on the repo's `typescript 7.0.2` pin (scaffolded at `92205a3`) — the TS 7 native package ships no JS AST API (`require('typescript')` exports only `version`/`versionMajorMinor`), and `typescript-eslint/dist/index.js` throws `typescript-eslint does not support TS 7.0` before any linting. No released typescript-eslint supports TS ≥7; tracking issue typescript-eslint/typescript-eslint#10940. Plain eslint cannot parse TS syntax, so partial adoption (react-hooks plugin without the TS parser) is not possible. Latest TS 6 is 6.0.3 if a side-by-side (TS 6 for the eslint API + TS 7 native for tsc) or downgrade is ever chosen instead — both are dependency/toolchain changes needing operator approval.

**Acceptance:** Re-run plan Task 14 verbatim when typescript-eslint ships TS ≥7.1 support (#10940). Install artifacts were reverted (package.json/package-lock clean); nothing landed.

### 9A.13 [x] alembic env.py: ambient `DATABASE_URL` silently overrides conftest's template-DB URL [P1] — done 2026-09-09

**Why:** `backend/alembic/env.py:13-18` (review-remediation Task 3) reads `DATABASE_URL` from the environment and overrides `sqlalchemy.url` — including the URL that `backend/tests/conftest.py:_load_alembic_schema` sets via `config.set_main_option` for the pytest-postgresql template DB. Any test run with `DATABASE_URL` exported (e.g. `set -a; source .env`) silently migrates the dev DB instead of the template: 320 DB-dependent tests fail with `UndefinedTableError` (`relation "export_versions" does not exist`) while the migration logs look healthy. Observed live 2026-09-09 during the cycle's final backend gate; misdiagnosis as a regression is easy.

**Done:** `env.py` now prefers `config.attributes["database_url"]` over the env var; all seven programmatic alembic callers in tests set the attribute; regression test `test_upgrade_targets_config_url_not_ambient_database_url` (upgrades with ambient `DATABASE_URL` pointing at a second scratch DB, asserts schema lands in the configured DB only); invocation note in `backend/AGENTS.md`. Full suite 924/924 green with `DATABASE_URL` exported.

---

## Section 10 — Ops: mypy baseline cleanup (2026-09-08)

### 10.1 [ ] Fix mypy baseline errors (42) [P2]

**Why:** `backend/AGENTS.md` documents `uv run mypy .` but mypy was not a dev dep (2026-08-31 ops item). 2026-09-08: mypy 2.3.1 added to the dev group with `[tool.mypy]` config (py 3.10 target, stub-ignore limited to jsonschema/apscheduler/asyncpg); command now runs and reports 42 known errors snapshotted in `backend/docs/mypy-baseline.md`. Fixes were deferred (operator decision) so the tool is usable now without a big fix cycle.

**Acceptance:** Work the baseline doc cluster-by-cluster; each fix removes its lines from `backend/docs/mypy-baseline.md` in the same commit. When it reaches zero, flip `backend/AGENTS.md` to gate on exit-0 like ruff.

**References:** `backend/docs/mypy-baseline.md` (byte-exact error list + cluster notes; `app/routes/quality.py:58-63` is a variable-reuse inference artifact, not a runtime bug).

---

## Working notes for the next agent

- **Remaining P2 pool:** 2.2 (deferred on backend question), 3.5, 6.1, 6.2, Section 9 (labelizer polish leftovers), plus the m11c leftovers (enable-error toast wording key; span-aria-label robustness — noted inside the 1.9/1.10 Done entries) and the m11d leftovers (prefix-matcher seed assertion; noted inside the 1.6 Done entry). TODO section 1 is now COMPLETE. dnd-kit follow-up: the pointer interaction test is coupled to geometry internals — revisit on any dnd-kit major bump (noted inside the 1.4 Done entry). Task 5.1 blocked on core plugins (Labelizer/Rules/Filter shipped 2026-09-05; Category still planned); 8.1 is the owner's planning meta-task. Open ops items: ruff 506 pre-existing errors (un-pinned but installed; zero-new-in-touched-files convention holds); mypy now installed+configured with a 42-error baseline (Section 10.1); ProductsPage.test.tsx parallel-load flake (passes solo — documented, worth a fake-timer pass); vite allowedHosts machine-specific host + Caddyfile.dev site-label mismatch. German findings tooltips lack pluralization (`{{count}} Warnungen` renders "1 Warnungen") — use `_one`/`_other` suffixes if the keys are ever touched. ENVIRONMENT LESSON (2026-09-07): subagent sessions can die mid-task returning empty — controller must verify working tree vs brief and either re-dispatch a finisher or controller-execute; stale `task-N-report.md` files from prior cycles sit at the same paths — always overwrite and check freshness.
- **All P1s closed** (m11a cycle). The 2026-08-31/09-01 cycles closed 1.2, 1.7, 1.8, 1.9, 1.10, 3.3, 3.4 + the shutdown-drain ops follow-up.
- **M10 gate per task:** `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run && npm run typecheck && npm run build`. Backend tasks: `cd /home/ozon/gmc_feed_master && pytest -n auto` (requires `TEST_DATABASE_URL`).
- **Conventions** (binding): no comments in code; all strings via `t()`; en+de identical i18n trees; 422 errors summary notification (now via `notifyApiError` in `frontend/src/app/notifyApiError.ts`); query-key invalidation; Loading/Empty/ErrorState on every data view.
- **M10-d lessons** (binding): TanStack Form dirty uses `form.Subscribe`; `notifications.clean()` in `beforeEach`; `beforeAll(loadNamespaces)` for non-default namespaces; `useBlocker` requires data router (`createMemoryRouter`+`RouterProvider` in tests); nullable fields in `plugin.manifest` need optional chaining.
- **2026-08-30 cycle notes:** Vite 8 uses rolldown — `manualChunks` is gone, use `build.rolldownOptions.output.codeSplitting.groups`. Frontend full-suite runs can flake when a heavy backend suite runs concurrently (load-induced jsdom timing); re-run solo before diagnosing. Task 1.7 (route error boundary) should land before the next deploy-heavy cycle.
- **Per-task workflow:** Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. After each task, merge to main and update `.superpowers/sdd/progress.md` (the SDD ledger; gitignored, lives on disk only).
- **Originals:** specs at `docs/superpowers/specs/2026-08-29-m10-d-areas-2-design.md` and `docs/superpowers/specs/2026-08-28-m10-frontend-design.md`; full 2026-08-30 cycle history in `.superpowers/sdd/progress.md`.

---

_Generated 2026-08-29 after M10-d merge (`aa86c10`). Updated 2026-08-30 after the `m11-followups` cycle (merged at `4bdc3a8`): 22 tasks across 8 sections, 7 complete (1.1, 2.1, 2.3, 3.1, 3.2, 4.1, 7.1), 2 new (1.7, 1.8). Updated 2026-08-31 after the `m11a-p1s` cycle (merged at `457fc2f`): 9 complete — all P1s closed (3.4, 1.7 done; WIP landed as 5 commits). Updated 2026-09-01 after the `m11b-correctness` cycle (merged at `d9d5eab`): 12 complete (1.2, 3.3, 1.8, shutdown drain), 2 new (1.9, 1.10). Updated 2026-09-01 after the `m11c-micro` cycle: 14 complete (1.9, 1.10). Updated 2026-09-01 after the `m11d-micro` cycle: 16 complete (1.5, 1.6). Updated 2026-09-02 after the `m11e-dnd` cycle: 18 complete (1.3, 1.4) — section 1 fully closed. Updated 2026-09-07 after the labelizer polish cycle (head `30970ae`, all on main): Section 9 added (6 BACKLOG items from the final-review triage); labelizer deferred minors from the 2026-09-05 cycles all closed. Updated 2026-09-08: mypy 2.3.1 added to the backend dev group with `[tool.mypy]` config + 42-error baseline (`backend/docs/mypy-baseline.md`, tracked as Section 10.1) — fixes deferred per operator decision._
