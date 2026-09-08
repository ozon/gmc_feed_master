# Admin Area Tabs + /admin Proxy Fix — Design

Date: 2026-09-08
Status: Approved (brainstorm session)
Builds on: `docs/decisions/0009-basic-rbac.md`, `docs/superpowers/specs/2026-09-08-user-management-admin-area-design.md`

## Goal

1. **Fix the `["admin","users"]` query error**: "Query data cannot be undefined" when opening Admin > Users.
2. **Consolidate the Admin Area** into one separate page with tabs (Users, Clients, Settings) and a single "Admin" entry in the navbar (replacing the 3-item "Administration" nav group).

## Root cause of the query error

`GET /admin/*` requests never reach the backend:

- `frontend/vite.config.ts` proxies `/auth`, `/health`, `/clients`, `/feed-sources`, `/dashboard`, `/plugins`, `/registry`, `/export` — **`/admin` is the only backend prefix missing**.
- Same gap in `Caddyfile` and `Caddyfile.dev` (`handle /admin/*` absent).
- In dev, Vite's SPA fallback answers with `index.html` (HTTP 200, `text/html`).
- `frontend/src/api/client.ts` `request()` returns `undefined as T` for any 2xx response with a non-JSON content type (line ~52).
- TanStack Query v5 rejects `undefined` query data → the reported error for key `["admin","users"]` (`queryKeys.adminUsers`, `queryKeys.ts:27`).

The backend is unaffected: `/admin/users|settings|scheduler` exist and are admin-guarded (`backend/app/routes/admin.py`).

## Decisions (from brainstorm)

| Question | Decision |
|---|---|
| Admin page tabs | Users, Clients, Settings (Settings keeps scheduler overview + plugin toggles) |
| Tab ↔ URL | Sub-paths stay: `/admin/users`, `/admin/clients`, `/admin/settings` preselect the tab; `/admin` defaults to Users |
| Visual separation | Inside the current AppShell; sidebar admin group collapses into one "Admin" NavLink |
| client.ts behavior | Harden: throw on 2xx non-JSON instead of silently returning `undefined` |

## Design

### 1. Proxy fix (root cause)

- `frontend/vite.config.ts`: add `'/admin': { target: 'http://127.0.0.1:8000', changeOrigin: true }`.
- `Caddyfile` and `Caddyfile.dev`: add `handle /admin/* { reverse_proxy <backend> }` before the static/SPA catch-all. All `/admin` API paths have sub-paths (`/admin/users`, `/admin/settings`, `/admin/scheduler`), so `/admin/*` covers them.

### 2. client.ts hardening (defense-in-depth)

In `request()`: for 2xx responses **that carry a `content-type` header which is not `application/json`**, throw an `ApiError` (status from response, detail naming the unexpected content type) instead of returning `undefined`. Rationale: a routing misconfiguration must surface as a visible error state, not as "Query data cannot be undefined".

- 204 handling and empty-body handling stay unchanged (including responses without a `content-type` header, which keep the existing text-parse path).
- Safe: the only non-JSON endpoint (`/export/*` XML via `FileResponse`) is fetched by Google Merchant Center, never by the frontend (verified by search).

### 3. Routing (`frontend/src/app/router.tsx`)

```
(RequireAdmin)
├── /admin               → AdminPage (Users tab)
├── /admin/users         → AdminPage (Users tab)
├── /admin/clients       → AdminPage (Clients tab)
└── /admin/settings      → AdminPage (Settings tab)
```

- One lazy `AdminPage`; the three existing page components are imported statically inside it (still code-split as one admin chunk).
- `RequireAdmin` guard unchanged; old links/bookmarks keep working; tabs are refresh-safe and shareable.

### 4. AdminPage (`frontend/src/features/admin/AdminPage.tsx`)

- Mantine `Tabs` with `keepMounted={false}` (same pattern as `SetupPage`) so only the active tab's queries fire.
- Tab value derived from `useLocation().pathname` segment (`users` | `clients` | `settings`, fallback `users`); `onChange` navigates to `/admin/<tab>`.
- Tabs: Users (`IconUsers`), Clients (`IconBuilding`), Settings (`IconSettings`) — labels from new `admin.tabs.*` i18n keys.
- Panels render the existing `AdminUsersPage`, `AdminClientsPage`, `AdminSettingsPage` components unchanged.
- One `Title order={3}` "Administration" above the tabs (reuses `nav.adminSection`).

### 5. Navbar (`frontend/src/app/AppShell.tsx`)

- Replace the "Administration" section header + 3 NavLinks with a single `NavLink`:
  - `to="/admin"`, label `t('nav.admin')` (new key: en "Admin", de "Verwaltung"), `leftSection` `IconShieldCog`.
  - Rendered only for `session?.role === 'admin'`; active when the pathname starts with `/admin`.

### 6. i18n

- `common.json` (en/de): add `nav.admin`; remove the now-unused `nav.adminUsers`, `nav.adminClients`, `nav.adminSettings` (verified: only the removed AppShell NavLinks use them); keep `nav.adminSection` (reused as the AdminPage title).
- `admin.json` (en/de): add `tabs.users`, `tabs.clients`, `tabs.settings` (en: Users/Clients/Settings; de: Benutzer/Kunden/Einstellungen — match existing de wording in the file).
- Keep en/de key parity (i18n parity test exists: `src/i18n/i18n.test.tsx`).

## Testing

- New `AdminPage.test.tsx`: tab↔URL sync (each sub-path activates its tab), `/admin` defaults to Users, tab click navigates, panels render.
- New test for `client.ts` hardening: 2xx non-JSON → `ApiError` thrown (test-first).
- Existing `AdminClientsPage.test.tsx` (full-App render at `/admin/clients`) and `AdminPages.test.tsx` (RequireAdmin redirect) must still pass.
- Run: `npm run test`, `npm run typecheck`, `npm run build` from `frontend/`.

## Docs updates (same commit)

- `frontend/docs/architecture.md`: routing tree (admin routes → AdminPage tabs), Admin Area section (single Admin NavLink, tabbed page), proxy prefix list (add `/admin`).
- Note in AGENTS.md boundary docs is not required; ADR-0009 statements remain accurate (frontend nav is UX only; backend enforces).

## Out of scope

- Backend/API changes (none).
- Splitting scheduler/plugins into their own tabs.
- New admin functionality.
- Renaming the existing admin page components (they remain the tab panels).
