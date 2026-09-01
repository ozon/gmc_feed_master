# M11c Micro-batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close TODO 1.9 (shared error handler for both plugin-toggle mutate paths) and TODO 1.10 (aria-label severity cues on findings badges) — both frontend-only, single-component changes.

**Architecture:** Two independent micro-tasks. Task 1 unifies PluginRegistryPanel's two `useUpdatePluginEnabled` mutate call sites through one `mutateToggle` function so the error handler exists once. Task 2 adds an `aria-label` to each of the three findings badges in ExportVersionList, reusing the existing `title` i18n expression.

**Tech Stack:** React 19 + Mantine + TanStack Query + i18next; vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-09-01-m11c-micro-design.md`

## Global Constraints

- No comments in code (repo convention, binding).
- All strings via `t()`; NO new i18n keys in this cycle (both tasks reuse existing keys); en+de trees unchanged.
- Frontend gate per task: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run && npm run typecheck && npm run build` (re-run solo if flaked by a concurrent backend suite).
- `git diff --check` clean (trailing newlines on all touched files).
- Work on branch `m11c-micro`. Do not touch main.
- No backend files touched; no backend gate needed.

---

### Task 1: Fast-path toggle onError (TODO 1.9)

**Files:**
- Modify: `frontend/src/features/pipeline/PluginRegistryPanel.tsx:22-46` (unify mutate paths)
- Test: `frontend/src/features/pipeline/PluginRegistryPanel.test.tsx` (add 1 test)

**Interfaces:**
- Consumes: `useUpdatePluginEnabled` (hooks.ts:337) — `useMutation({ mutationFn: ({id, enabled}) => apiPut(...), onSuccess: invalidate plugins })`; per-call callbacks via `mutate(vars, { onError })`. `ApiError` (client.ts) exposes `status`. Existing i18n keys in pipeline namespace: `disableBlocked` ("Plugin is in use by {{count}} feed sources. Cannot disable."), `disableFailed` ("Could not disable plugin.").
- Produces: `mutateToggle(plugin: PluginInfo, enabled: boolean)` — module-internal; both `onChange` (fast path) and `confirmToggle` route through it.

- [ ] **Step 1.1: Write the failing test (RED)**

Append inside `describe('PluginRegistryPanel', ...)` in `frontend/src/features/pipeline/PluginRegistryPanel.test.tsx`. The scenario: stale cache — plugin object says `used_by_feed_sources: 0` (no modal), server says 409. The toast's count comes from the panel's cached value (0) by design.

```tsx
  it('shows the disableBlocked toast when a stale-cache fast-path disable hits 409', async () => {
    const user = userEvent.setup();
    stubFetch((url, init) => {
      if (url.startsWith(`/plugins/${pluginUnused.id}/enabled`) && init?.method === 'PUT') {
        return new Response(JSON.stringify({ detail: 'plugin in use by 2 feed sources' }), {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    renderAt([pluginUnused]);
    await user.click(screen.getByTestId('registry-panel-control'));
    await user.click(screen.getByTestId(`plugin-toggle-${pluginUnused.id}`));

    expect(
      await screen.findByText(/in use by 0 feed sources/i),
    ).toBeInTheDocument();
  });
```

(`pluginUnused` is the file's existing fixture with `used_by_feed_sources: 0` — the fast path fires with no ConfirmModal.)

- [ ] **Step 1.2: Run (verify RED)**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm test -- --run src/features/pipeline/PluginRegistryPanel.test.tsx
```

Expected: the new test FAILS — no toast appears (fast path has no onError; the 409 is swallowed).

- [ ] **Step 1.3: Implement the unified mutate**

In `frontend/src/features/pipeline/PluginRegistryPanel.tsx`, replace `onChange` and `confirmToggle` (lines 22-46) with:

```tsx
  function mutateToggle(plugin: PluginInfo, enabled: boolean) {
    toggleEnabled.mutate(
      { id: plugin.id, enabled },
      {
        onError: (error) => {
          if (error instanceof ApiError && error.status === 409) {
            notifyError(t('disableBlocked', { count: plugin.used_by_feed_sources }));
          } else {
            notifyMutationError(error, t('disableFailed'));
          }
        },
      },
    );
  }

  function onChange(plugin: PluginInfo, next: boolean) {
    if (!next && plugin.used_by_feed_sources > 0) {
      setPendingToggle(plugin);
      return;
    }
    mutateToggle(plugin, next);
  }

  function confirmToggle() {
    if (!pendingToggle) return;
    const plugin = pendingToggle;
    setPendingToggle(null);
    mutateToggle(plugin, false);
  }
```

Imports unchanged (`ApiError`, `notifyError`, `notifyMutationError`, `PluginInfo` all already imported).

- [ ] **Step 1.4: Run (verify GREEN)**

```bash
npm test -- --run src/features/pipeline/PluginRegistryPanel.test.tsx
```

Expected: all pass — 8 existing (5 panel + 2 m11b + this one = 8 total after this task; count: the file had 7 tests after m11b, now 8) + the 2 m11b error-path tests unaffected (same toasts, same handler semantics — only the call site moved).

- [ ] **Step 1.5: Full frontend gate**

```bash
npm test -- --run && npm run typecheck && npm run build
git diff --check
```

Expected: 167 tests (166 + 1), typecheck + build clean.

- [ ] **Step 1.6: Commit**

```bash
git add frontend/src/features/pipeline/PluginRegistryPanel.tsx \
  frontend/src/features/pipeline/PluginRegistryPanel.test.tsx
git commit -m "fix(pipeline): shared error handler for both plugin toggle paths (TODO 1.9)"
```

---

### Task 2: Findings badge aria-labels (TODO 1.10)

**Files:**
- Modify: `frontend/src/features/export/ExportVersionList.tsx:75-101` (add aria-label per badge)
- Test: `frontend/src/features/export/ExportPage.test.tsx` (extend the existing findings tests)

**Interfaces:**
- Consumes: existing i18n keys in export namespace — `findings.critical` = `"{{count}} critical"`, `findings.warning` = `"{{count}} warning"`, `findings.info` = `"{{count}} info"` (en); same expressions already used for `title`. Test fixture version 3 has `findings: { critical: 2, warning: 0, info: 5 }`.
- Produces: nothing — render-only attribute addition.

- [ ] **Step 2.1: Extend the failing test (RED)**

In `frontend/src/features/export/ExportPage.test.tsx`, extend the existing test that asserts the findings badges (the one using `findings-critical-3` etc.) — read the file's current findings tests first and add the aria-label assertions to it, OR append a focused new test:

```tsx
  it('announces badge severity and count via aria-label', () => {
    renderAt();
    expect(screen.getByTestId('findings-critical-3')).toHaveAttribute('aria-label', '2 critical');
    expect(screen.getByTestId('findings-warning-3')).toHaveAttribute('aria-label', '0 warning');
    expect(screen.getByTestId('findings-info-3')).toHaveAttribute('aria-label', '5 info');
  });
```

(Follow the file's existing render pattern — the m11b findings tests show it; `renderAt` + optional `waitFor` on a row testid if the list renders async. Mirror whichever pattern the neighboring findings tests use.)

- [ ] **Step 2.2: Run (verify RED)**

```bash
npm test -- --run src/features/export/ExportPage.test.tsx
```

Expected: the new/extended test FAILS — badges have no aria-label.

- [ ] **Step 2.3: Implement**

In `frontend/src/features/export/ExportVersionList.tsx`, add `aria-label` to each of the three badges — same expression as `title`:

```tsx
                  <Badge
                    size="xs"
                    variant="light"
                    color={version.findings.critical ? 'red' : 'gray'}
                    title={t('findings.critical', { count: version.findings.critical })}
                    aria-label={t('findings.critical', { count: version.findings.critical })}
                    data-testid={`findings-critical-${version.version_number}`}
                  >
                    {version.findings.critical}
                  </Badge>
```

(the same one-line addition for the warning and info badges with their keys/values).

- [ ] **Step 2.4: Run (verify GREEN)**

```bash
npm test -- --run src/features/export/ExportPage.test.tsx
```

Expected: all pass — existing findings tests unaffected (testid-based), the new aria-label test green.

- [ ] **Step 2.5: Full frontend gate**

```bash
npm test -- --run && npm run typecheck && npm run build
git diff --check
```

Expected: 168 tests (167 + 1), typecheck + build clean.

- [ ] **Step 2.6: Commit**

```bash
git add frontend/src/features/export/ExportVersionList.tsx frontend/src/features/export/ExportPage.test.tsx
git commit -m "a11y(export): severity aria-labels on findings badges (TODO 1.10)"
```

---

## Session Close (controller)

- [ ] **Step C.1: Whole-branch review** — `scripts/review-package $(git merge-base main HEAD) HEAD`; final reviewer (small diff — one reviewer pass).
- [ ] **Step C.2: Update TODO.md** — mark 1.9, 1.10 `[x]` with Done entries; cycle log entry.
- [ ] **Step C.3: Update `.superpowers/sdd/progress.md`.**
- [ ] **Step C.4: Merge to main** — `git checkout main && git merge --ff-only m11c-micro`.
- [ ] **Step C.5: Ask the owner about pushing.**
