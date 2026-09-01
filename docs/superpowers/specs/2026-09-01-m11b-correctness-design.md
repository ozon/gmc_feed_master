# M11b Correctness Batch — Design

**Date:** 2026-09-01
**Cycle branch:** `m11b-correctness` (off main `10ebbb5`; merge to main at cycle end)
**Workflow:** subagent-driven development (per-task implement → review → commit), final whole-branch review before merge
**Spec source:** TODO 1.2 (rescoped per owner decision), TODO 3.3, TODO 1.8, and the background-task shutdown-drain follow-up from the 2026-08-31 final review.

## §0 Context

All P1s closed (`457fc2f`). This cycle lands a small correctness batch: plugin disable-in-use protection, logout error handling, per-version QC findings badges, and a lifecycle hardening for the manual run trigger's background tasks.

Owner decisions (2026-09-01):
- TODO 1.2 premise was FALSE (backend never returns 409; the typeToConfirm modal is the only guard). Resolution: ADD the backend 409 (defense-in-depth) + frontend 409 branch.
- Zero-count findings render visible-but-dimmed (0/0/0 reads "clean", distinct from rollback's "not QC'd").
- 409 detail format: `"plugin in use by N feed sources"`.

## §1 Task 1 — Plugin disable 409 (TODO 1.2, rescoped)

### §1.1 Backend

`backend/app/routes/plugins.py` `update_plugin_enabled` (lines 123-134): when `payload.enabled is False`, compute the plugin's usage count with the same join `list_plugins` uses (`ModuleInstance.plugin_id` × `ModulePipeline.feed_source_id` distinct count, filtered to this plugin's DB id); if ≥ 1 → `HTTPException(status_code=409, detail=f"plugin in use by {count} feed sources")`. Enabling (`enabled=True`) stays unconditional. Unknown plugin → 404 (unchanged).

Implementation notes:
- Extract the usage-count query into a small helper (`_usage_count(session, plugin_row_id) -> int`) so `list_plugins` and `update_plugin_enabled` share it (DRY — `list_plugins` currently computes all-plugins usage in one grouped query; keep its grouped query, add the single-plugin helper, OR refactor both to use the helper. Prefer: keep the grouped query in `list_plugins` (it's one round-trip for all plugins) and have the helper used by the 409 path only. The reviewer may flag the near-duplication; the join is 4 lines — acceptable).
- The check runs inside the same `session.begin()` that flips `enabled` — no TOCTOU window worth worrying about at this scale.
- `test_plugins_api.py` (has `seed_plugin` helper at line 68): add tests — disable-in-use → 409 (seed plugin + a ModulePipeline/ModuleInstance referencing it), disable-unused → 200, enable-in-use → 200, 409 detail contains the count. Seeding a pipeline needs the `ModulePipeline`/`ModuleInstance` models (see `test_pipeline_api.py` for the shape).

### §1.2 Frontend

`PluginRegistryPanel.tsx`: `confirmToggle` calls `toggleEnabled.mutate(...)` — the mutation currently has no error handling. Add `onError` in the component's mutate call site (or via a wrapper): on `error instanceof ApiError && error.status === 409`, show `notifyError(t('disableBlocked', { count: ... }))` — the count can be parsed from the detail string, but simpler and more robust: the panel already has `plugin.used_by_feed_sources` on the pendingToggle object — use `t('disableBlocked', { count: pendingToggle.used_by_feed_sources })`. On non-409 errors: `notifyMutationError(error, t('pipeline' namespace fallback))` → simplest: same toast with the generic failure message; use `notifyMutationError` for the non-409 path.

Switch revert: NOT needed — the Switch is `checked={plugin.enabled}` (server state from the plugins query; no optimistic update exists), so a failed mutation leaves the cache untouched and the switch re-renders at its old value automatically.

i18n (`pipeline.json`, en+de identical trees):
- `"disableBlocked": "Plugin is in use by {{count}} feed sources. Cannot disable."` / de: `"Plugin wird von {{count}} Feed-Quellen verwendet. Deaktivieren nicht möglich."`

Tests (`PluginRegistryPanel.test.tsx`): 409 response → toast with "in use" text; switch still reflects server state; non-409 → generic failure toast.

### §1.3 Docs

`backend/docs/api.md`: `PUT /plugins/{id}/enabled` — note the 409 on disable-in-use.

## §2 Task 2 — Logout error notification (TODO 3.3)

`frontend/src/api/hooks.ts` `useLogout` (lines 182-190) + `AppShell.tsx` UserMenu call site:

Decision (binding): hooks.ts stays i18n-free (repo pattern — hooks.ts has no `useTranslation` imports). Split responsibilities:
- `useLogout` (hooks.ts): `mutationFn` unchanged; replace `onSuccess` with `onSettled: () => { queryClient.removeQueries({ queryKey: queryKeys.session }); }` — local session cleared on BOTH success and error (the user clicked Log out; they expect local logout either way). Note this changes `resetQueries` → `removeQueries` (matches `makeUnauthorizedHandler`'s established pattern of removing, not resetting, the session cache).
- `AppShell.tsx` UserMenu (line 166): keep `onSuccess: () => navigate('/login')`; add `onError: (error) => notifyMutationError(error, t('errors.logoutFailed'))`.

Navigation on error: the user stays on the current page initially (TODO 3.3 acceptance). With the session cache removed in `onSettled`, `RequireSession`'s `useSession` refetches; if the server session is truly gone the 401 handler navigates to `/login`. If the server still holds the session (only the logout call failed), the user simply stays logged in with the toast explaining. Both outcomes are server-state-driven — correct.

i18n (`common.json`, en+de identical): `"errors": { ..., "logoutFailed": "Log out failed on the server. You were logged out locally." }` / de: `"Abmelden ist auf dem Server fehlgeschlagen. Sie wurden lokal abgemeldet."` (merge into the existing `errors` section added in m11a-p1s).

Tests: `AppShell.test.tsx` — the existing "logs out and returns to the login page" test covers success; add a failing-logout test: `/auth/logout` → 500 with `/auth/me` stubbed 200 (user remains logged in UI-wise), assert the toast shows the logoutFailed text. The toast renders via the `<Notifications />` component already mounted in that test's tree. No new hook-level test file (the AppShell test covers the path; `useLogout`'s `onSettled` cache behavior is implicitly covered — if desired, an assertion that `queryClient.getQueryData(queryKeys.session)` is undefined after the failed logout pins the cache-clear behavior).

## §3 Task 3 — ExportVersionList findings badges (TODO 1.8)

`frontend/src/features/export/ExportVersionList.tsx`:

- New column header after "Products": `t('columns.findings')`.
- For each version row:
  - `source === 'run'` (or any non-rollback source) AND `version.findings != null`: render three count badges — critical (red), warning (yellow), info (blue). Zero counts rendered **visible but dimmed** (e.g. `variant="light"` + `c="dimmed"` on the Text inside, or Mantine Badge with `color={n ? color : 'gray'}`). Use a11y-friendly label: `aria-label={`${severity} findings: ${count}`}` with a `data-testid={`findings-${severity}-${version.version_number}`}`.
  - `source === 'rollback'` (findings null): render nothing in the findings cell (the existing "not QC'd" badge in the version cell already distinguishes it; no 0/0/0).
- Findings display format: `critical: 2 · warning: 0 · info: 5` as three separate tiny Badges (one per severity) — pick three badges, each showing `severityLetter: count` or the count with a title. Simplest that satisfies "0/0/0 reads clean, not empty": three badges labeled with the severity name and count, zero-count ones dimmed.

Decision (binding): three `Badge` components per run-version row: `size="xs"`, `variant="light"`, color red/`yellow`/`blue` for critical/warning/info; when the count is 0 the badge uses `color="gray"` (dimmed reads "checked, none found"). Each: `title={t('findings.critical', { count })}` for hover, data-testid for tests. No i18n pluralization needed — counts are numeric.

i18n (`export.json`, en+de identical):
- `"columns.findings": "Findings"` / de: `"Qualität"` (short, fits the column header, matches the QC concept of the existing "not QC'd" badge; the de tree uses plain translations elsewhere).
- Tooltip keys (en): `"findings": { "critical": "{{count}} critical", "warning": "{{count}} warning", "info": "{{count}} info" }`; de: `"{{count}} kritisch"`, `"{{count}} Warnungen"`, `"{{count}} Hinweise"`.

Tests (`ExportPage.test.tsx` — extend the `versions` fixture with `findings`): run version with `{critical: 2, warning: 0, info: 5}` renders the counts; rollback version (findings null) shows no findings badges but keeps notQcd; run version with 0/0/0 shows three dimmed/gray badges (assert testids present, not absent).

`url` stays unused (per TODO 1.8 acceptance).

## §4 Task 4 — Background-task shutdown drain

`backend/app/main.py` lifespan, after `yield`:

```python
        background_tasks = getattr(application.state, "background_tasks", None)
        if background_tasks:
            done, pending = await asyncio.wait(
                set(background_tasks), timeout=_SHUTDOWN_DRAIN_TIMEOUT
            )
            if pending:
                logger.warning(
                    "shutdown drain: %d background task(s) still pending; "
                    "they will be marked interrupted on next startup",
                    len(pending),
                )
```

- Module constant `_SHUTDOWN_DRAIN_TIMEOUT = 10.0` (monkeypatchable in tests).
- Exception logging: in `trigger_run` (clients.py), the done-callback currently only discards. Replace with a callback that retrieves and logs exceptions:

```python
    def _on_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.exception... # actually: logger.error("background pipeline task failed: %s", task.exception())
        background_tasks.discard(task)
```

  (clients.py needs a module logger — check if one exists; add `logger = logging.getLogger(__name__)` if absent.)

Order in lifespan: drain BEFORE `scheduler_service.shutdown()`? No — scheduler jobs may spawn tasks? Scheduler jobs call `runner.execute` directly (not via `trigger_run`), so they are NOT in `background_tasks`. Drain can go first or last; put it FIRST after yield (most urgent: don't kill in-flight runs early), then scheduler shutdown, http client close, engine dispose (current order preserved after inserting the drain first).

Tests (`backend/tests/test_run_trigger_tracking.py` extend):
- Gated run + lifespan shutdown (via `async with LifespanManager(app)` or manually driving the lifespan context) → assert the gated task got to run to completion (release before/inside shutdown) and `background_tasks` empty after.
- A test asserting the drain timeout path: monkeypatch `_SHUTDOWN_DRAIN_TIMEOUT` to ~0.1s, gate never releases, shutdown returns within a bounded time, pending task logged/abandoned (assert app did not hang; the task is cancelled? `asyncio.wait` does NOT cancel pending tasks — log-only is the design; the abandoned task keeps running until process exit; reconcile at next startup marks the run interrupted. Assert: shutdown completed and warning logged (caplog)).
- A test for the done-callback: a runner.execute that raises → the 202 already returned; on task completion the exception is logged (caplog), no "Task exception was never retrieved" noise (hard to assert directly; assert the log record instead).

If `LifespanManager` (asgi-lifespan) is not a dependency, drive the lifespan manually: `async with app.router.lifespan_context(app):` (Starlette internal — check test_m9_lifespan.py for the established pattern; it exists per test list).

## §5 Order of work

1. Branch `m11b-correctness` off main.
2. Task 1 (409) → review → 1-2 commits (backend+tests, frontend+i18n+tests may be one commit or split by concern per m11a precedent: split).
3. Task 2 (logout) → review → 1 commit.
4. Task 3 (findings badges) → review → 1 commit.
5. Task 4 (drain) → review → 1 commit.
6. Final whole-branch review → merge to main → TODO.md cycle log + progress.md → push (owner pushed last cycle; ask).

## §6 Gates

Per task + final: backend `uv run pytest -n auto` (TEST_DATABASE_URL, real PostgreSQL); frontend `npm test -- --run && npm run typecheck && npm run build`; `git diff --check` clean.

## §7 Out of scope

- ruff/mypy install-or-drop decision (ops follow-up — owner hasn't decided).
- vite allowedHosts machine-specific host cleanup.
- 65 backend warnings classification.
- P2 pool remaining: 1.3-1.6, 2.2, 3.5, 6.1, 6.2.
