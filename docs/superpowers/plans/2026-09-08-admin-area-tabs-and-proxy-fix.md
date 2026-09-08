# Admin Area Tabs + /admin Proxy Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `["admin","users"]` "Query data cannot be undefined" error (missing `/admin` proxy) and consolidate the three admin pages into one tabbed Admin Area page with a single "Admin" navbar entry.

**Architecture:** Proxy `/admin` to the backend in Vite dev + both Caddyfiles (root cause); harden `client.ts` to throw on 2xx non-JSON; new `AdminPage` with URL-driven Mantine tabs renders the existing `AdminUsersPage`/`AdminClientsPage`/`AdminSettingsPage` as tab panels; `AppShell` nav collapses the 3-item administration group into one "Admin" NavLink.

**Tech Stack:** React 19, TypeScript, Mantine 9, TanStack Query v5, React Router v7, i18next (typed keys from `public/locales/en/*.json`), Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-08-admin-area-tabs-and-proxy-fix-design.md`

## Global Constraints

- All `npm`/`npx` commands run from `frontend/`. `npm run typecheck` = `tsc -b`; use `npx vitest run <file>` for one-shot test runs (`npm run test` is watch-flavored `vitest`).
- NO code comments in any file (repo AGENTS.md rule).
- Server state only via TanStack Query hooks in `src/api/hooks.ts` — do not add fetch logic to components.
- i18n keys are typed from `public/locales/en/*.json` (`src/i18n/i18next.d.ts`); en and de files must keep identical key sets. `useSession` has `staleTime: Infinity`, so tests seed the session via `queryClient.setQueryData(queryKeys.session, …)` and no `/auth/me` fetch happens.
- **Agents do NOT run `git add`/`git commit`.** Parallel agents share the working tree and the git index; the orchestrator handles git after the operator approves.
- Only touch the files listed in your task's **Files** section. Nothing else.
- Do not modify `AdminUsersPage.tsx`, `AdminClientsPage.tsx`, or `AdminSettingsPage.tsx` — they become tab panels unchanged.
- Do not modify any backend file. The backend already serves `/admin/users|settings|scheduler` correctly.

## Parallel Execution Model

Tasks are grouped into waves. Dispatch each task in a wave as a separate parallel agent (one `task` call per task, all in one message). File ownership never overlaps, so agents cannot conflict.

| Task | Wave | Files owned (exclusive) |
|---|---|---|
| 1 — Proxy fix | 1 | `frontend/vite.config.ts`, `Caddyfile`, `Caddyfile.dev` |
| 2 — client.ts hardening | 1 | `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts` |
| 3 — i18n keys (add) | 1 | `frontend/public/locales/{en,de}/common.json`, `frontend/public/locales/{en,de}/admin.json` |
| 4 — AdminPage + routing + navbar | 2 (after 1–3) | `frontend/src/features/admin/AdminPage.tsx` (new), `frontend/src/features/admin/AdminPage.test.tsx` (new), `frontend/src/app/router.tsx`, `frontend/src/app/AppShell.tsx`, `frontend/src/app/AdminNav.test.tsx`, `frontend/public/locales/{en,de}/common.json` (key removal) |
| 5 — Docs | 2 (after 1–3) | `frontend/docs/architecture.md` |
| 6 — Integration verification | 3 (orchestrator, after all) | none (verification only) |

Why the waves: Task 4 consumes the i18n keys added by Task 3 and must remove their old usages together with the keys (removing keys while `AppShell.tsx` still references them breaks `tsc`). Wave-1 agents run only targeted vitest invocations to avoid concurrent `tsc -b` write races; full gates run in Task 4 and Task 6.

---

### Task 1 (Wave 1): Proxy `/admin` to the backend

**Files:**
- Modify: `frontend/vite.config.ts` (proxy object, lines 44–77)
- Modify: `Caddyfile` (site block, lines 1–26)
- Modify: `Caddyfile.dev` (site block, lines 1–30)

**Interfaces:**
- Consumes: nothing (config-only).
- Produces: dev-server and production reverse-proxy routing for `/admin/*` → `http://127.0.0.1:8000`. No exports; later tasks and runtime rely on this.

- [ ] **Step 1: Add the `/admin` proxy entry to `vite.config.ts`**

In `frontend/vite.config.ts`, inside `server.proxy`, insert this as the FIRST entry, immediately after the line `proxy: {` (keep the existing entries untouched below it):

```typescript
        '/admin': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
```

- [ ] **Step 2: Add the `/admin` handle to `Caddyfile`**

In `Caddyfile` (repo root), insert immediately after line 1 (`{$DOMAIN:localhost} {`), before the `/auth/*` handle. Use TAB indentation exactly like the neighboring blocks:

```
	handle /admin/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
```

- [ ] **Step 3: Add the `/admin` handle to `Caddyfile.dev`**

In `Caddyfile.dev` (repo root), insert immediately after line 1 (`http://localhost {`), before the `/auth/*` handle. Use TAB indentation:

```
	handle /admin/* {
		reverse_proxy http://127.0.0.1:8000
	}
```

- [ ] **Step 4: Validate**

Run from repo root:

```bash
command -v caddy >/dev/null && caddy validate --adapter caddyfile --config Caddyfile && caddy validate --adapter caddyfile --config Caddyfile.dev || echo "caddy not installed — config diff review only"
```

Expected: caddy prints `Valid configuration` for both files (or the skip message), and no tool rewrites the files. The TypeScript `vite.config.ts` edit is verified by `npm run build` (which runs `tsc -b` then `vite build`) in Task 6.

- [ ] **Step 5: Report**

Return: the three diffs and validation output. Do NOT commit.

---

### Task 2 (Wave 1): Harden `client.ts` against non-JSON 2xx responses (TDD)

**Files:**
- Modify: `frontend/src/api/client.ts` (`request()`, lines 40–55)
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Consumes: existing `ApiError` class (`constructor(status: number, detail?: string, errors?: string[] | null)`).
- Produces: `request<T>()` throws `new ApiError(response.status, \`Unexpected response content type: ${contentType}\`)` for 2xx responses carrying a non-JSON `content-type` header. 204 and empty-body behavior unchanged. Later tasks rely on this surfacing routing misconfigs as visible errors.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/api/client.test.ts`, inside the existing `describe('api client', …)` block, append these two tests (after the last `it(...)`):

```typescript
  it('throws ApiError for a 2xx response with a non-JSON content type', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('<!doctype html>', {
        status: 200,
        headers: { 'Content-Type': 'text/html' },
      }),
    );
    const error: unknown = await apiGet('/admin/users').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(200);
    expect((error as ApiError).detail).toContain('text/html');
  });

  it('still resolves undefined for 204 responses', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(apiGet('/clients/3')).resolves.toBeUndefined();
  });
```

- [ ] **Step 2: Run the tests to verify the new one fails**

Run from `frontend/`:

```bash
npx vitest run src/api/client.test.ts
```

Expected: FAIL — "throws ApiError for a 2xx response with a non-JSON content type" fails because `apiGet` currently resolves `undefined` (so `error` is `undefined`, not an `ApiError`). The 204 test should PASS already.

- [ ] **Step 3: Implement the throw**

In `frontend/src/api/client.ts`, replace this block inside `request()`:

```typescript
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType && !contentType.includes('application/json')) return undefined as T;
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
```

with:

```typescript
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType && !contentType.includes('application/json')) {
    throw new ApiError(
      response.status,
      `Unexpected response content type: ${contentType}`,
    );
  }
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
npx vitest run src/api/client.test.ts
```

Expected: PASS — all tests in the file, including the two new ones.

- [ ] **Step 5: Regression check on hook tests (targeted, no `tsc`)**

```bash
npx vitest run src/api
```

Expected: PASS — `hooks.*.test.tsx` stubs all set `Content-Type: application/json` explicitly, so nothing else breaks. If any OTHER test file fails because it stubs a 2xx response without a JSON content type, do NOT change production code — add the `headers: { 'Content-Type': 'application/json' }` to that test's `Response` and note it in your report.

- [ ] **Step 6: Report**

Return: which tests failed before/after, and the final `client.ts` diff. Do NOT commit.

---

### Task 3 (Wave 1): Add i18n keys (add-only — removal happens in Task 4)

**Files:**
- Modify: `frontend/public/locales/en/common.json`
- Modify: `frontend/public/locales/de/common.json`
- Modify: `frontend/public/locales/en/admin.json`
- Modify: `frontend/public/locales/de/admin.json`

**Interfaces:**
- Consumes: nothing.
- Produces: typed i18n keys — `common:nav.admin` (en: "Admin", de: "Verwaltung") and `admin:tabs.users|clients|settings` (en: Users/Clients/Settings; de: Benutzer/Kunden/Einstellungen). Task 4 uses these exact keys.

- [ ] **Step 1: Update `en/common.json`**

Replace the `nav` object (lines 3–14) with:

```json
  "nav": {
    "dashboard": "Dashboard",
    "setup": "Setup",
    "products": "Products",
    "pipeline": "Pipeline Editor",
    "monitoring": "Monitoring",
    "export": "Export",
    "adminSection": "Administration",
    "adminUsers": "Users",
    "adminClients": "Clients",
    "adminSettings": "Settings",
    "admin": "Admin"
  },
```

(Only the `"admin": "Admin"` line is new; `adminUsers/adminClients/adminSettings` are kept until Task 4 removes their usages.)

- [ ] **Step 2: Update `de/common.json`**

Replace the `nav` object with:

```json
  "nav": {
    "dashboard": "Übersicht",
    "setup": "Einrichtung",
    "products": "Produkte",
    "pipeline": "Pipeline-Editor",
    "monitoring": "Überwachung",
    "export": "Export",
    "adminSection": "Verwaltung",
    "adminUsers": "Benutzer",
    "adminClients": "Kunden",
    "adminSettings": "Einstellungen",
    "admin": "Verwaltung"
  },
```

- [ ] **Step 3: Update `en/admin.json`**

Add a `tabs` object as the FIRST key inside the root object (before `"users"`):

```json
  "tabs": {
    "users": "Users",
    "clients": "Clients",
    "settings": "Settings"
  },
```

- [ ] **Step 4: Update `de/admin.json`**

Add a `tabs` object as the FIRST key inside the root object (before `"users"`):

```json
  "tabs": {
    "users": "Benutzer",
    "clients": "Kunden",
    "settings": "Einstellungen"
  },
```

- [ ] **Step 5: Validate JSON syntax and parity**

```bash
node -e "for (const l of ['en','de']) { for (const f of ['common','admin']) { JSON.parse(require('node:fs').readFileSync('frontend/public/locales/'+l+'/'+f+'.json','utf8')); } } console.log('all valid')"
node -e "
const en = require('/home/ozon/gmc_feed_master/frontend/public/locales/en/admin.json');
const de = require('/home/ozon/gmc_feed_master/frontend/public/locales/de/admin.json');
const keys = (o, p='') => Object.entries(o).flatMap(([k,v]) => v && typeof v === 'object' ? keys(v, p+k+'.') : [p+k]);
if (JSON.stringify(keys(en).sort()) !== JSON.stringify(keys(de).sort())) { console.error('admin.json key mismatch'); process.exit(1); }
console.log('admin.json parity ok');"
```

Expected: `all valid` and `admin.json parity ok`.

- [ ] **Step 6: Run the i18n tests**

```bash
npx vitest run src/i18n
```

Expected: PASS.

- [ ] **Step 7: Report**

Return: the four diffs and command output. Do NOT commit.

---

### Task 4 (Wave 2): AdminPage + routing + navbar (TDD)

**Files:**
- Create: `frontend/src/features/admin/AdminPage.tsx`
- Create: `frontend/src/features/admin/AdminPage.test.tsx`
- Modify: `frontend/src/app/router.tsx` (lazy imports lines 54–62; admin routes lines 155–162)
- Modify: `frontend/src/app/AppShell.tsx` (icon imports lines 21–34; admin nav block lines 274–308)
- Modify: `frontend/src/app/AdminNav.test.tsx` (both tests)
- Modify: `frontend/public/locales/en/common.json` and `frontend/public/locales/de/common.json` (remove the three old nav keys)

**Interfaces:**
- Consumes: Task 3's i18n keys (`admin.tabs.users|clients|settings` via `useTranslation('admin')`, `nav.adminSection` and `nav.admin` via the default namespace); the existing components `AdminUsersPage`, `AdminClientsPage`, `AdminSettingsPage` (named exports in the same directory).
- Produces: named export `AdminPage` from `frontend/src/features/admin/AdminPage.tsx`; routes `admin`, `admin/users`, `admin/clients`, `admin/settings` all rendering `AdminPage`; a single admin NavLink (`to="/admin"`, label `t('nav.admin')`) in `AppShell`.

- [ ] **Step 1: Update `AdminNav.test.tsx` to the new expectations (failing)**

Replace the ENTIRE file `frontend/src/app/AdminNav.test.tsx` with:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import App from '../App';
import { queryClient } from '../api/queryClient';
import { queryKeys } from '../api/queryKeys';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, setUnauthorizedHandler: vi.fn() };
});

const summary = {
  counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
  clients: [],
};

function handler(url: string): Response {
  const body =
    url === '/plugins' ? [] :
    url === '/dashboard/summary' ? summary :
    { detail: 'not found' };
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('AppShell admin nav', () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it('shows a single Admin link for admins', async () => {
    queryClient.setQueryData(queryKeys.session, {
      username: 'op',
      role: 'admin',
      client_ids: null,
    });
    stubFetch(handler);
    render(<App />);
    const admin = await screen.findByRole('link', { name: 'Admin' });
    expect(admin).toHaveAttribute('href', '/admin');
  });

  it('hides the Admin link for non-admins', async () => {
    queryClient.setQueryData(queryKeys.session, {
      username: 'bob',
      role: 'user',
      client_ids: [1],
    });
    stubFetch(handler);
    render(<App />);
    expect(await screen.findByText('Dashboard')).toBeDefined();
    expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull();
  });
});
```

- [ ] **Step 2: Create `AdminPage.test.tsx` (failing)**

Create `frontend/src/features/admin/AdminPage.test.tsx` with EXACTLY this content:

```tsx
import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import App from '../../App';
import { queryClient } from '../../api/queryClient';
import { queryKeys } from '../../api/queryKeys';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const users = [
  { id: 1, username: 'alice', role: 'admin', is_active: true, client_ids: [] },
];
const clients = [
  { id: 3, name: 'Globex', contact_details: {}, status: 'active', created_at: '2026-01-01' },
];
const settings = {
  staging_removal_retention_days: 90,
  staging_history_retention_days: 90,
  ingestion_run_retention_days: 90,
};

function handler(url: string): Response {
  if (url === '/admin/users') return jsonResponse(users);
  if (url === '/admin/settings') return jsonResponse(settings);
  if (url === '/admin/scheduler') return jsonResponse([]);
  if (url === '/clients') return jsonResponse(clients);
  if (url === '/plugins') return jsonResponse([]);
  if (url === '/dashboard/summary')
    return jsonResponse({
      counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
      clients: [],
    });
  return jsonResponse({});
}

beforeEach(() => {
  queryClient.clear();
  stubFetch(handler);
  queryClient.setQueryData(queryKeys.session, {
    username: 'operator',
    role: 'admin',
    client_ids: null,
  });
});

describe('AdminPage', () => {
  it('defaults to the users tab at /admin', async () => {
    window.history.replaceState({}, '', '/admin');
    render(<App />);
    expect(await screen.findByTestId('admin-users-table')).toBeInTheDocument();
    expect(await screen.findByText('alice')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-clients-table')).not.toBeInTheDocument();
  });

  it('activates the clients tab at /admin/clients', async () => {
    window.history.replaceState({}, '', '/admin/clients');
    render(<App />);
    expect(await screen.findByTestId('admin-clients-table')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-users-table')).not.toBeInTheDocument();
  });

  it('activates the settings tab at /admin/settings', async () => {
    window.history.replaceState({}, '', '/admin/settings');
    render(<App />);
    expect(
      await screen.findByText('Removed-product retention (days)'),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('admin-users-table')).not.toBeInTheDocument();
  });

  it('navigates between tabs via the URL', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/admin');
    render(<App />);
    expect(await screen.findByTestId('admin-users-table')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Clients' }));

    expect(await screen.findByTestId('admin-clients-table')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/admin/clients');
  });
});
```

- [ ] **Step 3: Run the new tests to verify they fail**

```bash
npx vitest run src/features/admin/AdminPage.test.tsx src/app/AdminNav.test.tsx
```

Expected: FAIL — AdminNav finds no "Admin" link (old nav still renders Users/Clients/Settings links); AdminPage tests fail because `/admin*` routes don't exist yet (App falls through to `*` → `/`, the dashboard renders, no admin tables are found).

- [ ] **Step 4: Create `AdminPage.tsx`**

Create `frontend/src/features/admin/AdminPage.tsx` with EXACTLY this content:

```tsx
import { Stack, Tabs, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router';
import { AdminClientsPage } from './AdminClientsPage';
import { AdminSettingsPage } from './AdminSettingsPage';
import { AdminUsersPage } from './AdminUsersPage';

const TAB_VALUES = ['users', 'clients', 'settings'] as const;
type AdminTab = (typeof TAB_VALUES)[number];

function tabFromPathname(pathname: string): AdminTab {
  const segment = pathname.split('/')[2];
  return (TAB_VALUES as readonly string[]).includes(segment ?? '')
    ? (segment as AdminTab)
    : 'users';
}

export function AdminPage() {
  const { t } = useTranslation('admin');
  const { t: tCommon } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const tab = tabFromPathname(location.pathname);

  return (
    <Stack>
      <Title order={3}>{tCommon('nav.adminSection')}</Title>
      <Tabs
        value={tab}
        onChange={(value) => {
          if (value) void navigate(`/admin/${value}`);
        }}
        keepMounted={false}
      >
        <Tabs.List>
          <Tabs.Tab value="users">{t('tabs.users')}</Tabs.Tab>
          <Tabs.Tab value="clients">{t('tabs.clients')}</Tabs.Tab>
          <Tabs.Tab value="settings">{t('tabs.settings')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="users" pt="md">
          <AdminUsersPage />
        </Tabs.Panel>
        <Tabs.Panel value="clients" pt="md">
          <AdminClientsPage />
        </Tabs.Panel>
        <Tabs.Panel value="settings" pt="md">
          <AdminSettingsPage />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
```

- [ ] **Step 5: Wire the router**

In `frontend/src/app/router.tsx`, replace the three lazy admin page declarations (lines 54–62):

```tsx
const AdminUsersPage = lazy(() =>
  import('../features/admin/AdminUsersPage').then((m) => ({ default: m.AdminUsersPage })),
);
const AdminClientsPage = lazy(() =>
  import('../features/admin/AdminClientsPage').then((m) => ({ default: m.AdminClientsPage })),
);
const AdminSettingsPage = lazy(() =>
  import('../features/admin/AdminSettingsPage').then((m) => ({ default: m.AdminSettingsPage })),
);
```

with:

```tsx
const AdminPage = lazy(() =>
  import('../features/admin/AdminPage').then((m) => ({ default: m.AdminPage })),
);
```

Then replace the RequireAdmin route group (lines 155–162):

```tsx
          {
            element: <RequireAdmin />,
            children: [
              { path: 'admin/users', element: <AdminUsersPage /> },
              { path: 'admin/clients', element: <AdminClientsPage /> },
              { path: 'admin/settings', element: <AdminSettingsPage /> },
            ],
          },
```

with:

```tsx
          {
            element: <RequireAdmin />,
            children: [
              { path: 'admin', element: <AdminPage /> },
              { path: 'admin/users', element: <AdminPage /> },
              { path: 'admin/clients', element: <AdminPage /> },
              { path: 'admin/settings', element: <AdminPage /> },
            ],
          },
```

- [ ] **Step 6: Collapse the navbar**

In `frontend/src/app/AppShell.tsx`:

6a. Replace the tabler icons import (lines 21–34):

```tsx
import {
  IconActivity,
  IconBox,
  IconBuilding,
  IconChevronDown,
  IconDashboard,
  IconFileExport,
  IconGitBranch,
  IconLogout,
  IconMoon,
  IconSettings,
  IconSun,
  IconUsers,
} from '@tabler/icons-react';
```

with (removes `IconBuilding` and `IconUsers`, which only the old admin links used; adds `IconShieldCog`):

```tsx
import {
  IconActivity,
  IconBox,
  IconChevronDown,
  IconDashboard,
  IconFileExport,
  IconGitBranch,
  IconLogout,
  IconMoon,
  IconSettings,
  IconShieldCog,
  IconSun,
} from '@tabler/icons-react';
```

6b. Replace the admin nav block (lines 274–308):

```tsx
          {session?.role === 'admin' && (
            <>
              <Text size="xs" c="dimmed" mt="sm">{t('nav.adminSection')}</Text>
              <NavLink
                component={Link}
                to="/admin/users"
                label={t('nav.adminUsers')}
                leftSection={<IconUsers size={16} />}
                active={isActive('/admin/users')}
                variant={isActive('/admin/users') ? 'light' : undefined}
                color={isActive('/admin/users') ? 'blue' : undefined}
                onClick={close}
              />
              <NavLink
                component={Link}
                to="/admin/clients"
                label={t('nav.adminClients')}
                leftSection={<IconBuilding size={16} />}
                active={isActive('/admin/clients')}
                variant={isActive('/admin/clients') ? 'light' : undefined}
                color={isActive('/admin/clients') ? 'blue' : undefined}
                onClick={close}
              />
              <NavLink
                component={Link}
                to="/admin/settings"
                label={t('nav.adminSettings')}
                leftSection={<IconSettings size={16} />}
                active={isActive('/admin/settings')}
                variant={isActive('/admin/settings') ? 'light' : undefined}
                color={isActive('/admin/settings') ? 'blue' : undefined}
                onClick={close}
              />
            </>
          )}
```

with:

```tsx
          {session?.role === 'admin' && (
            <NavLink
              component={Link}
              to="/admin"
              label={t('nav.admin')}
              leftSection={<IconShieldCog size={16} />}
              active={isActive('/admin')}
              variant={isActive('/admin') ? 'light' : undefined}
              color={isActive('/admin') ? 'blue' : undefined}
              onClick={close}
            />
          )}
```

(`isActive('/admin')` uses the existing `startsWith` logic, so the link highlights on every `/admin/*` path. `Text` stays imported — it is still used by `FeedBreadcrumb` and `UserMenu`.)

- [ ] **Step 7: Remove the now-unused nav keys**

In `frontend/public/locales/en/common.json`, remove these three lines from the `nav` object:

```json
    "adminUsers": "Users",
    "adminClients": "Clients",
    "adminSettings": "Settings",
```

In `frontend/public/locales/de/common.json`, remove:

```json
    "adminUsers": "Benutzer",
    "adminClients": "Kunden",
    "adminSettings": "Einstellungen",
```

(Keep `adminSection` — `AdminPage` uses it as the page title — and keep `admin`.) Then validate both files parse and still have identical key sets:

```bash
node -e "for (const l of ['en','de']) { JSON.parse(require('node:fs').readFileSync('frontend/public/locales/'+l+'/common.json','utf8')); } console.log('valid JSON');"
node -e "
const en = require('/home/ozon/gmc_feed_master/frontend/public/locales/en/common.json');
const de = require('/home/ozon/gmc_feed_master/frontend/public/locales/de/common.json');
const keys = (o, p='') => Object.entries(o).flatMap(([k,v]) => v && typeof v === 'object' ? keys(v, p+k+'.') : [p+k]);
if (JSON.stringify(keys(en).sort()) !== JSON.stringify(keys(de).sort())) { console.error('common.json key mismatch'); process.exit(1); }
console.log('common.json parity ok');"
```

- [ ] **Step 8: Run the new and affected tests**

```bash
npx vitest run src/features/admin src/app
```

Expected: PASS — the new `AdminPage.test.tsx` and updated `AdminNav.test.tsx`, plus the existing `AdminClientsPage.test.tsx` (renders at `/admin/clients` inside the new AdminPage tabs), `AdminPages.test.tsx` (RequireAdmin), `AppShell.test.tsx`, and `router.test.tsx`.

- [ ] **Step 9: Full gates**

```bash
npx vitest run
npm run typecheck
```

Expected: full suite PASS; `tsc -b` clean (proves the removed i18n keys have no remaining usages and `IconShieldCog` exists in `@tabler/icons-react`).

- [ ] **Step 10: Report**

Return: files created/modified, test output summaries, any deviation you had to make (e.g., a tab role assertion needed adjusting). Do NOT commit.

---

### Task 5 (Wave 2): Update frontend architecture docs

**Files:**
- Modify: `frontend/docs/architecture.md`

**Interfaces:**
- Consumes: the spec's final shape (this task documents what Tasks 1–4 build; no code dependency).
- Produces: documentation consistent with the implementation (repo AGENTS.md requires same-commit doc updates).

- [ ] **Step 1: Update the routing tree (lines 116–120)**

Replace:

```
    └── (RequireAdmin)
        ├── /admin/users                     → AdminUsersPage
        ├── /admin/clients                   → AdminClientsPage
        └── /admin/settings                  → AdminSettingsPage
```

with:

```
    └── (RequireAdmin) — all four routes render AdminPage (URL-driven tabs, Users default)
        ├── /admin                           → AdminPage (Users tab)
        ├── /admin/users                     → AdminPage (Users tab)
        ├── /admin/clients                   → AdminPage (Clients tab)
        └── /admin/settings                  → AdminPage (Settings tab)
```

- [ ] **Step 2: Update the Admin Area section (lines 127–134)**

Replace the bullet:

```
- "Administration" nav group in `AppShell` (Users, Clients, Settings) renders only for admins; dashboard shows a "Manage clients" link for admins instead of inline client CRUD.
```

with:

```
- Single "Admin" NavLink in `AppShell` renders only for admins and links to `/admin`; `AdminPage` is one page with URL-driven Mantine tabs (Users, Clients, Settings; `keepMounted={false}`, so only the active tab's queries fire). The sub-paths `/admin/users|clients|settings` preselect the tab. Dashboard shows a "Manage clients" link for admins instead of inline client CRUD.
```

Then replace:

```
- `AdminUsersPage` — user table (role badge, assigned-client count, active switch), create/edit modal with role select + client multi-select, reset-password modal.
- `AdminSettingsPage` — editable retention days (`/admin/settings`), scheduler job overview (`/admin/scheduler`), plugin enable/disable toggles (reuses `useUpdatePluginEnabled`).
```

with:

```
- `AdminUsersPage` — Users tab panel: user table (role badge, assigned-client count, active switch), create/edit modal with role select + client multi-select, reset-password modal.
- `AdminSettingsPage` — Settings tab panel: editable retention days (`/admin/settings`), scheduler job overview (`/admin/scheduler`), plugin enable/disable toggles (reuses `useUpdatePluginEnabled`).
```

- [ ] **Step 3: Update the proxy list (line 210)**

Replace:

```
- Vite proxies `/auth/*`, `/health`, `/clients`, `/feed-sources`, `/dashboard`, `/plugins`, `/registry`, `/export` to `http://127.0.0.1:8000`
```

with:

```
- Vite proxies `/auth/*`, `/health`, `/admin`, `/clients`, `/feed-sources`, `/dashboard`, `/plugins`, `/registry`, `/export` to `http://127.0.0.1:8000` (production Caddyfiles mirror this list, including `/admin/*`)
```

- [ ] **Step 4: Report**

Return: the three diffs. Do NOT commit.

---

### Task 6 (Wave 3): Integration verification (orchestrator — no subagent)

**Files:** none (verification only; fix-ups only if a gate fails).

- [ ] **Step 1: Full frontend gates**

```bash
npx vitest run
npm run typecheck
npm run build
```

Expected: all PASS. `npm run build` additionally proves `vite.config.ts` (Task 1) parses and bundles cleanly.

- [ ] **Step 2: Review the combined diff**

```bash
git status
git diff --stat
git diff
```

Check: only the files listed in Tasks 1–5 changed; no stray edits; both Caddyfiles keep TAB indentation.

- [ ] **Step 3: Optional live proxy verification (needs backend + Postgres running)**

```bash
# terminal 1 (backend): uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
# terminal 2 (frontend): npm run dev
curl -ki https://localhost:5173/admin/users
```

Expected: a JSON response (`{"detail":"Not authenticated"}` without a session cookie) — NOT HTML. Before the fix this returned `index.html`.

- [ ] **Step 4: Report to the operator**

Summarize gate results and the final file list. Ask the operator whether to commit (repo rule: never commit unasked). Suggested commit split if requested: one commit per wave, or a single `feat: consolidate admin area into tabbed page and proxy /admin` plus `docs:` entries per repo convention.
