# M11b Correctness Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land four independent correctness fixes: plugin disable-in-use 409 (backend + frontend), logout error notification, per-version QC findings badges in ExportVersionList, and a background-task shutdown drain for manual run triggers.

**Architecture:** Branch `m11b-correctness` off main (`7ee1cd6`). Four tasks, each independently testable and reviewed: Task 1 spans backend (409 guard in `update_plugin_enabled`) and frontend (409 branch in PluginRegistryPanel); Task 2 touches `useLogout` + AppShell UserMenu; Task 3 is a render-only column addition; Task 4 hardens the lifespan shutdown path.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), React 19 + Mantine + TanStack Query + i18next (frontend), pytest + httpx ASGITransport (backend), vitest + RTL (frontend).

**Spec:** `docs/superpowers/specs/2026-09-01-m11b-correctness-design.md`

## Global Constraints

- No comments in code (repo convention, binding).
- All user-visible strings via `t()`; en+de i18n trees IDENTICAL (every new key added to both `frontend/public/locales/en/<ns>.json` and `frontend/public/locales/de/<ns>.json` with matching structure).
- Frontend gate per task: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run && npm run typecheck && npm run build` (re-run solo if flaked by a concurrent backend suite).
- Backend gate: `cd /home/ozon/gmc_feed_master/backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto` (real PostgreSQL).
- `git diff --check` clean (all files end with trailing newlines).
- Docs: API-surface changes update `backend/docs/api.md` in the same commit.
- Work on branch `m11b-correctness` (already created). Do not touch main.
- hooks.ts stays i18n-free (no `useTranslation` imports in `frontend/src/api/hooks.ts`).
- The per-feed-source run lock must not be bypassed; Task 4 only changes shutdown/lifecycle behavior, not the lock.

---

### Task 1: Plugin disable-in-use 409 (TODO 1.2, rescoped)

**Files:**
- Modify: `backend/app/routes/plugins.py:123-134` (`update_plugin_enabled` — add 409 guard + usage-count helper)
- Modify: `backend/tests/test_plugins_api.py` (add 3 tests)
- Modify: `backend/docs/api.md` (409 note on the endpoint)
- Modify: `frontend/src/features/pipeline/PluginRegistryPanel.tsx` (409 branch in `confirmToggle`'s mutate call)
- Modify: `frontend/public/locales/en/pipeline.json` + `frontend/public/locales/de/pipeline.json` (`disableBlocked` key)
- Test: `frontend/src/features/pipeline/PluginRegistryPanel.test.tsx` (add 2 tests)

**Interfaces:**
- Consumes: `useUpdatePluginEnabled` (hooks.ts:337) — `useMutation` calling `apiPut<PluginInfo>('/plugins/${id}/enabled', { enabled })`, invalidating `queryKeys.plugins` on success. `ApiError` (frontend/src/api/client.ts) exposes `status: number` and `detail?: string`.
- Produces: `PUT /plugins/{id}/enabled` now returns **409** `{"detail": "plugin in use by N feed sources"}` when disabling (`enabled: false`) a plugin whose distinct feed-source usage ≥ 1; 200 otherwise (enable always allowed).

- [ ] **Step 1.1: Write the failing backend tests (RED)**

Append to `backend/tests/test_plugins_api.py` (after `test_toggle_enabled_unknown_plugin_returns_404`, around line 135). Reuse the file's existing helpers: `seed_plugin`, `logged_in_client`, and the manual seeding style of `test_plugins_list_includes_usage_count` (lines 301-345: Client → FeedSource → ModulePipeline → ModuleInstance chain; note `ModuleInstance` needs `position` + `name` + `configuration`).

```python
async def _seed_plugin_in_use(factory, plugin_name="used_plugin"):
    async with factory() as session:
        async with session.begin():
            plugin = Plugin(
                name=plugin_name,
                version="1.0.0",
                enabled=True,
                manifest=make_manifest(id=plugin_name),
            )
            session.add(plugin)
            await session.flush()
            acme = Client(name="Acme")
            session.add(acme)
            await session.flush()
            feed = FeedSource(client_id=acme.id, name="DE", source_format="wide_tsv")
            session.add(feed)
            await session.flush()
            pipeline = ModulePipeline(
                feed_source_id=feed.id, name="p", version="1", definition={}
            )
            session.add(pipeline)
            await session.flush()
            session.add(
                ModuleInstance(
                    pipeline_id=pipeline.id,
                    plugin_id=plugin.id,
                    position=0,
                    name="a",
                    configuration={},
                )
            )
            return plugin.id


async def test_disable_plugin_in_use_returns_409(app_factory):
    _, factory = app_factory
    await _seed_plugin_in_use(factory)
    client = await logged_in_client(app_factory)
    resp = await client.put("/plugins/used_plugin/enabled", json={"enabled": False})
    assert resp.status_code == 409
    assert "1 feed source" in resp.json()["detail"]


async def test_enable_plugin_in_use_is_allowed(app_factory):
    _, factory = app_factory
    await _seed_plugin_in_use(factory)
    client = await logged_in_client(app_factory)
    resp = await client.put("/plugins/used_plugin/enabled", json={"enabled": True})
    assert resp.status_code == 200


async def test_disable_unused_plugin_is_allowed(app_factory):
    _, factory = app_factory
    await seed_plugin(factory)
    client = await logged_in_client(app_factory)
    resp = await client.put("/plugins/title_case/enabled", json={"enabled": False})
    assert resp.status_code == 200
```

(`Plugin`, `Client`, `FeedSource`, `ModulePipeline`, `ModuleInstance`, `make_manifest` are already imported/defined in this test file — verify imports at the top.)

- [ ] **Step 1.2: Run backend tests (verify RED)**

```bash
cd /home/ozon/gmc_feed_master/backend
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \
  uv run pytest tests/test_plugins_api.py -k "in_use or unused_plugin_is" -v
```

Expected: `test_disable_plugin_in_use_returns_409` FAILS (returns 200 — no guard yet); the other two PASS (they assert behavior that already works).

- [ ] **Step 1.3: Implement the 409 guard**

In `backend/app/routes/plugins.py`, add a module-level helper below `_get_plugin_by_name` (around line 44):

```python
async def _usage_count(session: AsyncSession, plugin_row_id: int) -> int:
    from ..models.pipeline import ModuleInstance, ModulePipeline

    result = await session.execute(
        select(func.count(func.distinct(ModulePipeline.feed_source_id)))
        .join(ModulePipeline, ModuleInstance.pipeline_id == ModulePipeline.id)
        .where(ModuleInstance.plugin_id == plugin_row_id)
    )
    return int(result.scalar() or 0)
```

(Import `func` is already at the top; `select` too. The `from ..models.pipeline` local import mirrors `list_plugins`' existing local import at line 103.)

Then replace `update_plugin_enabled`'s body (lines 123-134) so the disable path checks usage inside the same transaction:

```python
@router.put("/plugins/{plugin_id}/enabled")
async def update_plugin_enabled(
    plugin_id: str,
    payload: EnabledPut,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, str]:
    session = _require_db(db_session)
    async with session.begin():
        plugin = await _get_plugin_by_name(session, plugin_id)
        if not payload.enabled:
            count = await _usage_count(session, plugin.id)
            if count > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"plugin in use by {count} feed source"
                    f"{'s' if count != 1 else ''}",
                )
        plugin.enabled = payload.enabled
    return {"status": "ok"}
```

- [ ] **Step 1.4: Run backend tests (verify GREEN)**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \
  uv run pytest tests/test_plugins_api.py -v
```

Expected: all pass (existing 20+ plus 3 new).

- [ ] **Step 1.5: Update api.md**

In `backend/docs/api.md`, find the plugin endpoints section (search `enabled`). Change the `PUT /plugins/{id}/enabled` line to:

```
- `PUT /plugins/{id}/enabled` — enable/disable plugin; returns 409 when disabling a plugin used by ≥1 feed source
```

- [ ] **Step 1.6: Write the failing frontend tests (RED)**

Append to `frontend/src/features/pipeline/PluginRegistryPanel.test.tsx` inside the existing `describe` block. The existing tests show the pattern: `stubFetch` in the test overrides the `beforeEach` default; `renderAt([pluginInUse])`; the disable flow for an in-use plugin opens the ConfirmModal (typeToConfirm = `String(plugin.used_by_feed_sources)` = `"2"`), types the count, clicks confirm.

```tsx
  it('shows a disableBlocked toast and keeps the switch on when the server returns 409', async () => {
    const user = userEvent.setup();
    stubFetch((url, init) => {
      if (url.startsWith(`/plugins/${pluginInUse.id}/enabled`) && init?.method === 'PUT') {
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
    renderAt([pluginInUse]);
    await user.click(screen.getByTestId('registry-panel-control'));
    await user.click(screen.getByTestId(`plugin-toggle-${pluginInUse.id}`));
    await user.type(
      screen.getByLabelText(/type 2 to confirm/i),
      '2',
    );
    await user.click(await screen.findByRole('button', { name: /disable/i }));

    expect(
      await screen.findByText(/in use by 2 feed sources/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId(`plugin-toggle-${pluginInUse.id}`)).toBeChecked();
  });
```

Note: verify the ConfirmModal confirm-label text — `ConfirmModal` renders `confirmLabel ?? t('actions.confirm')`; the panel passes `confirmLabel={t('disable')}`, so the button name is the `pipeline` namespace's `disable` value (check `frontend/public/locales/en/pipeline.json` for its exact text and adjust the regex). The typeToConfirm label comes from `actions.typeToConfirm` in common.json: `"Type {{name}} to confirm"` → the input's label matches `/type 2 to confirm/i`. Also verify how the toast text renders: the notification shows `t('disableBlocked', { count: 2 })` = "Plugin is in use by 2 feed sources. Cannot disable." — the regex `/in use by 2 feed sources/i` must match that string (it does).

Add a second test for the non-409 error path:

```tsx
  it('shows the generic failure toast on a non-409 toggle error', async () => {
    const user = userEvent.setup();
    stubFetch((url, init) => {
      if (url.startsWith(`/plugins/${pluginInUse.id}/enabled`) && init?.method === 'PUT') {
        return new Response(JSON.stringify({ detail: 'boom' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    renderAt([pluginInUse]);
    await user.click(screen.getByTestId('registry-panel-control'));
    await user.click(screen.getByTestId(`plugin-toggle-${pluginInUse.id}`));
    await user.type(
      screen.getByLabelText(/type 2 to confirm/i),
      '2',
    );
    await user.click(await screen.findByRole('button', { name: /disable/i }));

    expect(await screen.findByText(/could not/i)).toBeInTheDocument();
  });
```

(The generic fallback key: check `pipeline.json` for an existing failure key — e.g. `saveFailed` or similar; use whatever generic mutation-failure key exists in the `pipeline` namespace, or reuse `common.json`'s `state.error` "Something went wrong." via the default-namespace `t` — in the component the `t` is namespace-scoped to 'pipeline', so pass the second arg: `t('translation:state.error')`... simpler and binding: add NO new generic key — `notifyMutationError(error, t('pipeline:state.error'))` won't work since pipeline.json has no state.error. BINDING DECISION: for the non-409 path use `notifyMutationError(error, t('disableFailed'))` and add `"disableFailed": "Could not disable plugin."` + de `"Plugin konnte nicht deaktiviert werden."` to pipeline.json alongside `disableBlocked`. Adjust the second test's assertion to `/could not disable plugin/i`.)

- [ ] **Step 1.7: Run frontend tests (verify RED)**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm test -- --run src/features/pipeline/PluginRegistryPanel.test.tsx
```

Expected: the 2 new tests FAIL (no error handling in `confirmToggle` yet — no toast appears).

- [ ] **Step 1.8: Implement the frontend 409 branch + i18n keys**

(a) `frontend/public/locales/en/pipeline.json` — add (keeping existing key order, insert near the disable keys):

```json
  "disableBlocked": "Plugin is in use by {{count}} feed sources. Cannot disable.",
  "disableFailed": "Could not disable plugin."
```

`frontend/public/locales/de/pipeline.json` — identical placement:

```json
  "disableBlocked": "Plugin wird von {{count}} Feed-Quellen verwendet. Deaktivieren nicht möglich.",
  "disableFailed": "Plugin konnte nicht deaktiviert werden."
```

(b) `frontend/src/features/pipeline/PluginRegistryPanel.tsx` — imports first:

```tsx
import { ApiError } from '../../api/client';
import { notifyError, notifyMutationError } from '../../app/notifications';
```

(check existing imports; `useTranslation` already imported; `notifyMutationError` and `notifyError` are exported from `../../app/notifications`).

Then change `confirmToggle` (lines 28-32):

```tsx
  function confirmToggle() {
    if (!pendingToggle) return;
    const plugin = pendingToggle;
    toggleEnabled.mutate(
      { id: plugin.id, enabled: false },
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
    setPendingToggle(null);
  }
```

(The count comes from the plugin object the panel already has — no detail-string parsing. The switch needs no revert logic: it's `checked={plugin.enabled}` from server state, no optimistic update exists.)

- [ ] **Step 1.9: Run frontend tests (verify GREEN)**

```bash
npm test -- --run src/features/pipeline/PluginRegistryPanel.test.tsx
```

Expected: all pass (5 existing + 2 new).

- [ ] **Step 1.10: Full gates**

```bash
cd /home/ozon/gmc_feed_master/backend
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto
cd /home/ozon/gmc_feed_master/frontend
npm test -- --run && npm run typecheck && npm run build
git diff --check
```

Expected: backend 660 passed (657 + 3), frontend 162+ (160 + 2), typecheck/build clean, diff-check clean.

- [ ] **Step 1.11: Commit (split by concern)**

```bash
cd /home/ozon/gmc_feed_master
git add backend/app/routes/plugins.py backend/tests/test_plugins_api.py backend/docs/api.md
git commit -m "feat(backend): 409 on disabling a plugin in use by feed sources (TODO 1.2)"
git add frontend/src/features/pipeline/PluginRegistryPanel.tsx \
  frontend/src/features/pipeline/PluginRegistryPanel.test.tsx \
  frontend/public/locales/en/pipeline.json frontend/public/locales/de/pipeline.json
git commit -m "feat(frontend): handle plugin disable 409 with blocked toast (TODO 1.2)"
```

---

### Task 2: Logout error notification (TODO 3.3)

**Files:**
- Modify: `frontend/src/api/hooks.ts:182-190` (`useLogout` — `onSettled` clears session cache)
- Modify: `frontend/src/app/AppShell.tsx:166` (UserMenu mutate call — add `onError` toast)
- Modify: `frontend/public/locales/en/common.json` + `de/common.json` (`errors.logoutFailed`)
- Test: `frontend/src/app/AppShell.test.tsx` (add 1 test)

**Interfaces:**
- Consumes: `queryKeys.session` = `['session']`; `notifyMutationError(error, fallback)` from `../../app/notifications`; `logout()` from `api/client` (POSTs `/auth/logout`).
- Produces: `useLogout` clears the session cache on BOTH success and error (behavior change: was `onSuccess` + `resetQueries`; now `onSettled` + `removeQueries` — matching `makeUnauthorizedHandler`'s established remove-pattern).

- [ ] **Step 2.1: Write the failing test (RED)**

Append inside `describe('AppShell', ...)` in `frontend/src/app/AppShell.test.tsx` (after the existing "logs out and returns to the login page" test at lines 123-147):

```tsx
  it('shows a logoutFailed toast when the server rejects the logout', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/auth/logout') return jsonResponse({ detail: 'boom' }, 500);
      if (url === '/dashboard/summary') return jsonResponse(summary);
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });
    render(<App />);

    await screen.findByRole('heading', { name: 'Dashboard' });
    await user.click(screen.getByRole('button', { name: 'operator' }));
    await user.click(await screen.findByText('Log out'));

    expect(await screen.findByText(/failed on the server/i)).toBeInTheDocument();
    expect(
      queryClient.getQueryData(queryKeys.session),
    ).toBeUndefined();
  });
```

Notes: the toast text comes from the new key `errors.logoutFailed` = "Log out failed on the server. You were logged out locally." — regex `/failed on the server/i` matches. `queryClient` is already imported in this test file (line 7); `queryKeys` is imported in router.test.tsx but check AppShell.test.tsx — if absent, add `import { queryKeys } from '../api/queryKeys';`. Also: the AppShell test tree must render `<Notifications />` — check the test file's render approach: it renders the full `<App />` which mounts Notifications already (App.tsx line 7). Toasts render into the Notifications portal — RTL queries find them since App is fully rendered.

- [ ] **Step 2.2: Run (verify RED)**

```bash
npm test -- --run src/app/AppShell.test.tsx
```

Expected: new test FAILS (no toast — no onError handler; and session cache: on error nothing clears it today... note the old `onSuccess` didn't fire, so `getQueryData(session)` may be `undefined` anyway if never set in this test — if that makes the cache assertion vacuous, seed it first: `queryClient.setQueryData(queryKeys.session, { username: 'operator' });` right after the Dashboard renders. Add that seeding line BEFORE clicking Log out).

- [ ] **Step 2.3: Implement**

(a) `frontend/src/api/hooks.ts` `useLogout` (lines 182-190) — replace with:

```ts
export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.removeQueries({ queryKey: queryKeys.session });
    },
  });
}
```

(b) `frontend/src/app/AppShell.tsx` — imports: add `notifyMutationError` to the notifications import (check current imports; the file imports nothing from notifications today — add `import { notifyMutationError } from '../app/notifications';`). UserMenu's logout item (line 166):

```tsx
            onClick={() =>
              logoutMutation.mutate(undefined, {
                onSuccess: () => navigate('/login'),
                onError: (error) =>
                  notifyMutationError(error, t('errors.logoutFailed')),
              })
            }
```

(c) i18n — `frontend/public/locales/en/common.json`, merge into the existing `errors` section (added in m11a-p1s):

```json
  "errors": {
    "chunkLoadFailed": "A new version of the app is available. Reload to continue.",
    "routeError": "Something went wrong.",
    "reload": "Reload",
    "logoutFailed": "Log out failed on the server. You were logged out locally."
  },
```

`de/common.json` — identical structure:

```json
  "errors": {
    "chunkLoadFailed": "Eine neue Version der App ist verfügbar. Zum Fortfahren neu laden.",
    "routeError": "Etwas ist schiefgelaufen.",
    "reload": "Neu laden",
    "logoutFailed": "Abmelden ist auf dem Server fehlgeschlagen. Sie wurden lokal abgemeldet."
  },
```

- [ ] **Step 2.4: Run (verify GREEN)**

```bash
npm test -- --run src/app/AppShell.test.tsx
```

Expected: all pass (6 existing + 1 new). Verify the pre-existing "logs out and returns to the login page" test still passes (its flow: success → removeQueries → navigate — the navigation is in the AppShell onSuccess, unaffected).

- [ ] **Step 2.5: Full frontend gate**

```bash
npm test -- --run && npm run typecheck && npm run build
git diff --check
```

Expected: all green (163 tests), no new chunk warnings.

- [ ] **Step 2.6: Commit**

```bash
git add frontend/src/api/hooks.ts frontend/src/app/AppShell.tsx frontend/src/app/AppShell.test.tsx \
  frontend/public/locales/en/common.json frontend/public/locales/de/common.json
git commit -m "feat(app): logout error toast and unconditional local session clear (TODO 3.3)"
```

---

### Task 3: ExportVersionList findings badges (TODO 1.8)

**Files:**
- Modify: `frontend/src/features/export/ExportVersionList.tsx` (findings column + badges)
- Modify: `frontend/public/locales/en/export.json` + `de/export.json` (column + tooltip keys)
- Test: `frontend/src/features/export/ExportPage.test.tsx` (extend fixture + 3 assertions; the file has no separate ExportVersionList test)

**Interfaces:**
- Consumes: `ExportVersionOut.findings?: { critical: number; warning: number; info: number } | null` (types.ts:186 — shipped in m11a 2.1); existing column structure in `ExportVersionList.tsx` (columns at lines 34-41, rows at 44-98, notQcd badge at 49-53).
- Produces: render-only change — a new "Findings" column between "Products" and "A" (diffA). Three Badges per non-rollback row with `findings != null`; nothing for rollback rows.

- [ ] **Step 3.1: Extend the test fixture and write failing assertions (RED)**

In `frontend/src/features/export/ExportPage.test.tsx`, change the `versions` fixture (lines 39-43) to include findings:

```tsx
const versions = [
  { id: 3, version_number: 3, product_count: 100, file_hash: 'h3', source: 'run', source_version_id: null, created_at: '2026-08-29T10:00:00Z', findings: { critical: 2, warning: 0, info: 5 } },
  { id: 2, version_number: 2, product_count: 98, file_hash: 'h2', source: 'rollback', source_version_id: 3, created_at: '2026-08-28T10:00:00Z', findings: null },
  { id: 1, version_number: 1, product_count: 90, file_hash: 'h1', source: 'run', source_version_id: null, created_at: '2026-08-27T10:00:00Z', findings: { critical: 0, warning: 0, info: 0 } },
];
```

Append inside the existing `describe` block (read the file's remaining tests first — lines 61-103 — and follow their render/wait patterns):

```tsx
  it('renders per-severity findings badges for run versions', () => {
    renderAt();
    expect(screen.getByTestId('findings-critical-3')).toHaveTextContent('2');
    expect(screen.getByTestId('findings-warning-3')).toHaveTextContent('0');
    expect(screen.getByTestId('findings-info-3')).toHaveTextContent('5');
  });

  it('renders no findings badges for rollback versions but keeps the not-QC badge', () => {
    renderAt();
    expect(screen.queryByTestId('findings-critical-2')).not.toBeInTheDocument();
    expect(screen.getByTestId('not-qcd-badge')).toBeInTheDocument();
  });

  it('renders zero-count findings as dimmed gray badges for clean run versions', () => {
    renderAt();
    const badge = screen.getByTestId('findings-critical-1');
    expect(badge).toHaveTextContent('0');
    expect(badge).toHaveAttribute('title', '0 critical');
  });
```

(Note: `renderAt` in this file may be async or return a user — read the existing tests at lines 61-103 first and mirror their exact call pattern. The notQcd badge renders only on the rollback row; if multiple rollback rows existed there'd be duplicates, but with one rollback row `getByTestId` is fine.)

- [ ] **Step 3.2: Run (verify RED)**

```bash
npm test -- --run src/features/export/ExportPage.test.tsx
```

Expected: 3 new tests FAIL (no findings badges rendered; testids absent).

- [ ] **Step 3.3: Implement the findings column**

(a) i18n — `frontend/public/locales/en/export.json`: add `"findings": "Findings"` inside `columns` (after `"products"`), and a new top-level `findings` section:

```json
  "findings": {
    "critical": "{{count}} critical",
    "warning": "{{count}} warning",
    "info": "{{count}} info"
  },
```

`de/export.json` identical structure: `"findings": "Qualität"` in columns; top-level:

```json
  "findings": {
    "critical": "{{count}} kritisch",
    "warning": "{{count}} Warnungen",
    "info": "{{count}} Hinweise"
  },
```

(b) `frontend/src/features/export/ExportVersionList.tsx`:

Add the column header after the Products `Table.Th` (line 37):

```tsx
          <Table.Th>{t('columns.findings')}</Table.Th>
```

Add the cell after the Products `Table.Td` (line 70), inside the `versions.map` row:

```tsx
            <Table.Td>
              {version.source !== 'rollback' && version.findings != null ? (
                <Group gap={4} wrap="nowrap">
                  <Badge
                    size="xs"
                    variant="light"
                    color={version.findings.critical ? 'red' : 'gray'}
                    title={t('findings.critical', { count: version.findings.critical })}
                    data-testid={`findings-critical-${version.version_number}`}
                  >
                    {version.findings.critical}
                  </Badge>
                  <Badge
                    size="xs"
                    variant="light"
                    color={version.findings.warning ? 'yellow' : 'gray'}
                    title={t('findings.warning', { count: version.findings.warning })}
                    data-testid={`findings-warning-${version.version_number}`}
                  >
                    {version.findings.warning}
                  </Badge>
                  <Badge
                    size="xs"
                    variant="light"
                    color={version.findings.info ? 'blue' : 'gray'}
                    title={t('findings.info', { count: version.findings.info })}
                    data-testid={`findings-info-${version.version_number}`}
                  >
                    {version.findings.info}
                  </Badge>
                </Group>
              ) : null}
            </Table.Td>
```

The condition `version.source !== 'rollback' && version.findings != null` is deliberate: rollbacks render nothing (their notQcd badge already distinguishes them), and any future source value with findings still renders counts.

- [ ] **Step 3.4: Run (verify GREEN)**

```bash
npm test -- --run src/features/export/ExportPage.test.tsx
```

Expected: all pass (existing + 3 new).

- [ ] **Step 3.5: Full frontend gate**

```bash
npm test -- --run && npm run typecheck && npm run build
git diff --check
```

Expected: all green, build unchanged (ExportPage is lazy; +~1kB chunk growth acceptable).

- [ ] **Step 3.6: Commit**

```bash
git add frontend/src/features/export/ExportVersionList.tsx frontend/src/features/export/ExportPage.test.tsx \
  frontend/public/locales/en/export.json frontend/public/locales/de/export.json
git commit -m "feat(export): per-severity QC findings badges in version list (TODO 1.8)"
```

---

### Task 4: Background-task shutdown drain (ops follow-up)

**Files:**
- Modify: `backend/app/main.py` (lifespan post-`yield` — drain + warning; module constant)
- Modify: `backend/app/routes/clients.py:317-321` (`trigger_run` done-callback logs exceptions) + module logger if absent
- Test: `backend/tests/test_run_trigger_tracking.py` (add 2 tests) — may also need `backend/tests/test_m9_lifespan.py`-style lifespan driving; use `app.router.lifespan_context(app)` per that file's established pattern (lines 76, 100)

**Interfaces:**
- Consumes: `app.state.background_tasks: set[asyncio.Task]` (created in `create_app` line 198; `trigger_run` adds tasks with `add_done_callback(background_tasks.discard)`); `app.router.lifespan_context(app)` async context manager (Starlette) for test driving; `reconcile_interrupted_runs` marks non-terminal runs interrupted at next startup (safety net).
- Produces: `_SHUTDOWN_DRAIN_TIMEOUT: float = 10.0` module constant in main.py (monkeypatchable); lifespan drains background tasks after `yield` with a warning if pending remain.

- [ ] **Step 4.1: Write the failing tests (RED)**

Append to `backend/tests/test_run_trigger_tracking.py` (uses the file's existing `app_factory`, `_logged_in_client`, `_seed_feed_source`, and the gated-execute monkeypatch pattern from `test_manual_run_task_is_tracked_until_done` at lines 81-90). Note: the file's `app_factory` fixture (lines 26-50) creates the app but does NOT drive lifespan — the drain lives in lifespan shutdown, so the tests must enter `app.router.lifespan_context(app)`.

```python
async def test_shutdown_drain_lets_background_task_finish(app_factory):
    app, factory = app_factory
    client = await _logged_in_client(app)
    fs_id = await _seed_feed_source(client)

    release = asyncio.Event()
    real_execute = app.state.pipeline_runner.execute

    async def gated_execute(feed_source_id, run_id=None):
        await release.wait()
        return await real_execute(feed_source_id, run_id=run_id)

    app.state.pipeline_runner.execute = gated_execute

    async with app.router.lifespan_context(app):
        resp = await client.post(f"/feed-sources/{fs_id}/run")
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]
        await asyncio.sleep(0.1)
        assert len(app.state.background_tasks) == 1

        release.set()

    assert app.state.background_tasks == set()
    async with factory() as session:
        run = await session.get(IngestionRun, run_id)
    assert run.status == "success"
```

```python
async def test_shutdown_drain_times_out_and_warns(app_factory, monkeypatch, caplog):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_SHUTDOWN_DRAIN_TIMEOUT", 0.1)
    app, factory = app_factory
    client = await _logged_in_client(app)
    fs_id = await _seed_feed_source(client)

    gate = asyncio.Event()

    async def stuck_execute(feed_source_id, run_id=None):
        await gate.wait()
        return None

    app.state.pipeline_runner.execute = stuck_execute

    with caplog.at_level(logging.WARNING, logger="app.main"):
        async with app.router.lifespan_context(app):
            resp = await client.post(f"/feed-sources/{fs_id}/run")
            assert resp.status_code == 202
            await asyncio.sleep(0.05)
            assert len(app.state.background_tasks) == 1

        assert any(
            "background task" in record.message and "pending" in record.message
            for record in caplog.records
        )

    gate.set()
```

Add `import logging` at the top of the test file if absent. The second test releases the gate after the lifespan exits so the stuck task doesn't leak into other tests.

(Note: `app.state.pipeline_runner.execute` is monkeypatched on the runner INSTANCE — the same pattern the existing test at lines 83-90 uses. The lifespan drains `app.state.background_tasks` — the task wraps the patched execute.)

- [ ] **Step 4.2: Run (verify RED)**

```bash
cd /home/ozon/gmc_feed_master/backend
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \
  uv run pytest tests/test_run_trigger_tracking.py -k "shutdown" -v
```

Expected: both FAIL — test 1 because `background_tasks` is non-empty after lifespan exit today (nothing drains; the task completes only when `release.set()` fires, which happens before exit so the task MAY finish in time by luck of scheduling — if test 1 passes vacuously, that's fine: test 2 is the real RED (no drain → no warning → assertion fails; and without the drain the lifespan exits immediately with a pending task). Judge the RED state by test 2 at minimum.)

- [ ] **Step 4.3: Implement the drain**

(a) `backend/app/main.py` — add near the other module constants (after `_EXPORT_PATH_REDACTED`, ~line 59):

```python
_SHUTDOWN_DRAIN_TIMEOUT = 10.0
```

In the lifespan function, after `yield` (line 165) and BEFORE the scheduler shutdown block, insert:

```python
        background_tasks = getattr(application.state, "background_tasks", None)
        if background_tasks:
            done, pending = await asyncio.wait(
                set(background_tasks), timeout=_SHUTDOWN_DRAIN_TIMEOUT
            )
            if pending:
                logging.getLogger(__name__).warning(
                    "shutdown drain: %d background task(s) still pending; "
                    "they will be reconciled on next startup",
                    len(pending),
                )
```

Check main.py's imports: `asyncio` may not be imported at module level — if absent, add `import asyncio` to the imports (verify no circular-import concern; it's stdlib).

(b) `backend/app/routes/clients.py` — module logger: check whether the file has one; if not, add after the imports (line 32):

```python
import logging

logger = logging.getLogger(__name__)
```

(If `logging` import placement: keep stdlib imports grouped — `import asyncio` exists at line 3; add `import logging` next to it.)

Replace the done-callback in `trigger_run` (lines 318-321):

```python
    background_tasks = getattr(request.app.state, "background_tasks", None)
    if background_tasks is not None:
        def _on_done(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception() is not None:
                logger.error("background pipeline run failed: %s", task.exception())
            background_tasks.discard(task)

        background_tasks.add(task)
        task.add_done_callback(_on_done)
```

(Nested function inside the route — the callback closes over `background_tasks`. Ruff B008-style concerns don't apply; keep it simple. No blank line between the `if` and `def` per repo formatting — match the file's existing style; actually keep one consistent style: define `_on_done` before the `if` is not possible without the closure. This shape is fine.)

- [ ] **Step 4.4: Run backend tests (verify GREEN)**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \
  uv run pytest tests/test_run_trigger_tracking.py tests/test_m9_lifespan.py -v
```

Expected: all pass — the existing tracking tests still pass (the done-callback change is compatible: `discard` still runs), both new shutdown tests pass, lifespan tests unaffected.

- [ ] **Step 4.5: Full backend gate**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto
git diff --check
```

Expected: 662 passed (660 + 2).

- [ ] **Step 4.6: Commit**

```bash
git add backend/app/main.py backend/app/routes/clients.py backend/tests/test_run_trigger_tracking.py
git commit -m "feat(backend): drain background run tasks on shutdown and log task failures"
```

---

## Session Close (controller)

- [ ] **Step C.1: Whole-branch review** — `scripts/review-package $(git merge-base main HEAD) HEAD`, dispatch final reviewer.
- [ ] **Step C.2: Update TODO.md** — mark 1.2, 3.3, 1.8 `[x]` with Done entries; cycle log entry; working-notes update (remaining pool: 1.3-1.6, 2.2, 3.5, 6.1, 6.2; 8.1 owner meta-task; ruff/mypy ops decision still open).
- [ ] **Step C.3: Update `.superpowers/sdd/progress.md`** — cycle table + final review verdict.
- [ ] **Step C.4: Merge to main** — `git checkout main && git merge --ff-only m11b-correctness`.
- [ ] **Step C.5: Ask the owner about pushing.**
