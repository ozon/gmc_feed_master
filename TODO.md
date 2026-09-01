# TODO — Follow-up tasks after M10

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Each item below is sized for a single subagent task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **For human readers:** This file is the working backlog. Tasks were collected from the M10-d final review (`docs/superpowers/sdd/progress.md`), earlier carry-forwards, and the 2026-08-30 cycle's final review. Each task is self-contained: it names the file(s), the change, the acceptance bar, and the references needed to start.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` complete · `[!]` blocked

**Priority legend:** P0 = should land before any new milestone · P1 = should land before the next M10-followup work · P2 = nice to have

---

## Cycle log

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

### 2.2 [ ] Backend: extend `ExportVersionOut.source` to the 3-value enum from the spec [P2]

**Why:** The spec says `source ∈ {scheduled, manual, rollback}` (3 values). The backend currently writes only `'run'` and `'rollback'` (verified in `backend/app/services/export.py:135,301`). The frontend now matches the backend (M10-d `981c32d`). If the backend is extended to distinguish scheduled vs manual runs, the frontend's `source.run | source.rollback` whitelist needs to expand and the i18n needs a third key.

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

## Working notes for the next agent

- **Remaining P2 pool:** 1.3, 1.4 (pipeline-dnd pair — riskier: jsdom interaction-test flake risk + dnd-kit key churn), 2.2 (deferred on backend question), 3.5, 6.1, 6.2, plus the m11c leftovers (enable-error toast wording key; span-aria-label robustness — noted inside the 1.9/1.10 Done entries) and the m11d leftovers (prefix-matcher seed assertion; noted inside the 1.6 Done entry). Task 5.1 blocked on core plugins; 8.1 is the owner's planning meta-task. Open ops items: ruff/mypy install/pin-or-drop decision (baseline 430/45 pre-existing errors); 65 backend warnings classification; vite allowedHosts machine-specific host + Caddyfile.dev site-label mismatch. German findings tooltips lack pluralization (`{{count}} Warnungen` renders "1 Warnungen") — use `_one`/`_other` suffixes if the keys are ever touched.
- **All P1s closed** (m11a cycle). The 2026-08-31/09-01 cycles closed 1.2, 1.7, 1.8, 1.9, 1.10, 3.3, 3.4 + the shutdown-drain ops follow-up.
- **M10 gate per task:** `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run && npm run typecheck && npm run build`. Backend tasks: `cd /home/ozon/gmc_feed_master && pytest -n auto` (requires `TEST_DATABASE_URL`).
- **Conventions** (binding): no comments in code; all strings via `t()`; en+de identical i18n trees; 422 errors summary notification (now via `notifyApiError` in `frontend/src/app/notifyApiError.ts`); query-key invalidation; Loading/Empty/ErrorState on every data view.
- **M10-d lessons** (binding): TanStack Form dirty uses `form.Subscribe`; `notifications.clean()` in `beforeEach`; `beforeAll(loadNamespaces)` for non-default namespaces; `useBlocker` requires data router (`createMemoryRouter`+`RouterProvider` in tests); nullable fields in `plugin.manifest` need optional chaining.
- **2026-08-30 cycle notes:** Vite 8 uses rolldown — `manualChunks` is gone, use `build.rolldownOptions.output.codeSplitting.groups`. Frontend full-suite runs can flake when a heavy backend suite runs concurrently (load-induced jsdom timing); re-run solo before diagnosing. Task 1.7 (route error boundary) should land before the next deploy-heavy cycle.
- **Per-task workflow:** Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. After each task, merge to main and update `.superpowers/sdd/progress.md` (the SDD ledger; gitignored, lives on disk only).
- **Originals:** specs at `docs/superpowers/specs/2026-08-29-m10-d-areas-2-design.md` and `docs/superpowers/specs/2026-08-28-m10-frontend-design.md`; full 2026-08-30 cycle history in `.superpowers/sdd/progress.md`.

---

_Generated 2026-08-29 after M10-d merge (`aa86c10`). Updated 2026-08-30 after the `m11-followups` cycle (merged at `4bdc3a8`): 22 tasks across 8 sections, 7 complete (1.1, 2.1, 2.3, 3.1, 3.2, 4.1, 7.1), 2 new (1.7, 1.8). Updated 2026-08-31 after the `m11a-p1s` cycle (merged at `457fc2f`): 9 complete — all P1s closed (3.4, 1.7 done; WIP landed as 5 commits). Updated 2026-09-01 after the `m11b-correctness` cycle (merged at `d9d5eab`): 12 complete (1.2, 3.3, 1.8, shutdown drain), 2 new (1.9, 1.10). Updated 2026-09-01 after the `m11c-micro` cycle: 14 complete (1.9, 1.10). Updated 2026-09-01 after the `m11d-micro` cycle: 16 complete (1.5, 1.6)._
