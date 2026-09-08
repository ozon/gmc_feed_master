# Basic User Management & Admin Area — Design

Date: 2026-09-08
Status: Approved (brainstorm session)

## Goal

Add role-based access to GMC Feed Master:

1. Two user groups: **admin** and **user**.
2. A `user` can be assigned to **multiple clients** and sees only those clients (full functional scope inside them).
3. An **admin area** for user management, client management, and global settings.

Non-goals: more than two roles, fine-grained permissions, OAuth/SSO, user deletion.

## Decisions (from brainstorm)

| Question | Decision |
|---|---|
| Clients per user | Multiple (many-to-many) |
| First admin | Seed user created at startup (`INITIAL_USERNAME`/`INITIAL_PASSWORD`) is admin; existing users promoted by migration |
| User scope inside assigned clients | Full: view products, run pipelines, trigger runs, monitoring, exports, plugin configs |
| Client CRUD | Admin only (users can view assigned clients only) |
| Removing users | Deactivate (`is_active=false`), never delete (preserves FK/session integrity and run attribution) |
| Global settings | DB-persisted and editable from Admin area (retention days), replacing hardcoded constants |

## Data model

One Alembic migration (`uv run alembic revision --autogenerate` + data steps):

- `users.role` — `String`, NOT NULL, default `'user'`
- `users.is_active` — `Boolean`, NOT NULL, default `true`
- `user_clients` — join table: `id` PK, `user_id` FK `users.id` ON DELETE CASCADE, `client_id` FK `clients.id` ON DELETE CASCADE, `UniqueConstraint(user_id, client_id)`
- `global_settings` — single-row table: `id` PK (fixed value 1), `staging_removal_retention_days INT`, `staging_history_retention_days INT`, `ingestion_run_retention_days INT`, `updated_at`. Defaults 90 each; row is seeded lazily on first read.

Migration data steps:
- All pre-existing users get `role='admin'`.
- `seed_initial_user` (backend/app/persistence/users.py) creates the first user with `role='admin'`.

## Backend

### Dependencies (backend/app/auth.py)

- `get_current_user` — runs session validation, then loads the `User` row (username, role, `is_active`, assigned client ids). Raises 401 if user missing or inactive.
- `require_admin` — 403 unless `role == 'admin'`.

### Enforcement matrix

| Resource | admin | user (assigned) | user (not assigned) |
|---|---|---|---|
| `GET /clients`, dashboard summary | all clients | assigned clients only | n/a (filtered out) |
| `clients/{id}/…` routes, feed-source-scoped routes (`/feed-sources/{id}`, products, pipeline, monitoring, export-history, plugin config/data with client/feed scope) | full | full | **404** (no existence leak) |
| Client create/update/delete | allowed | **403** | **404** |
| `/admin/*` | allowed | **403** | **403** |
| Public export endpoint (token) | unchanged (token-auth) | unchanged | unchanged |

Implementation notes:
- Client access check lives in one helper used by all client/feed-source-scoped routes: resolve feed source → client when only `feed_source_id` is given, then check assignment.
- `POST /auth/login` rejects inactive users.
- `/auth/me` returns `{username, role, client_ids}`.
- Role/assignment changes take effect on the next request (user row loaded per request); password reset bumps `revocation_generation`, invalidating existing sessions.

### Admin API

- `GET /admin/users` — list with role, active, clients
- `POST /admin/users` — create (username, password, role, client ids)
- `PATCH /admin/users/{id}` — update role, `is_active`, client assignments
- `POST /admin/users/{id}/password` — set new password (bumps revocation generation)
- `GET /admin/settings` / `PUT /admin/settings` — global retention settings
- `GET /admin/scheduler` — registered job overview (id, cron) from SchedulerService
- Plugin enable/disable: reuse existing plugin endpoints; admin-only visibility in UI

### Purge jobs

`purge_expired` / `purge_expired_ingestion_runs` (backend/app/staging/purge.py) read retention days from `global_settings` (fallback to 90 if row missing), replacing module constants `REMOVAL_RETENTION_DAYS`, `HISTORY_RETENTION_DAYS`, `INGESTION_RUN_RETENTION_DAYS`.

## Frontend

- Session type extended: `/auth/me` → `{username, role, client_ids}`.
- "Administration" nav group in AppShell, visible only to admins, with route guard (non-admin → redirect away from `/admin/*`).
- Pages:
  - `AdminUsersPage` (`/admin/users`): table (username, role, clients, status) + create/edit modal with client multi-select, reset password, activate/deactivate.
  - `AdminClientsPage` (`/admin/clients`): client CRUD (moved from dashboard for admins; dashboard keeps read-only listing for all).
  - `AdminSettingsPage` (`/admin/settings`): editable retention form, read-only system info (export dir, public base URL, session TTLs), scheduler job overview, plugin enable/disable toggles.
- Dashboard: "Add Client" button hidden for non-admins; client accordion already filtered server-side.
- i18n keys added to all locales.
- Server state via TanStack Query only (per ADR-0001).

## Error handling

- 404 (not 403) for unassigned client/feed-source access — avoids resource enumeration.
- 403 for admin-only operations by authenticated non-admins.
- 401 for inactive/unknown users (session treated as invalid).

## Testing

- Backend (pytest): role enforcement on client-scoped routes (404 for unassigned, 403 for client CRUD by user), `/admin/*` 403 for users, user CRUD happy paths, settings GET/PUT, purge honors configured retention, inactive user login rejected, seed user is admin, migration promotes existing user.
- Frontend (vitest): admin nav visibility by role, admin route guard, user management form interactions.
- Commands: `uv run pytest -n auto`, `uv run ruff check .`, `uv run mypy .`; frontend `npm run test`, `npm run typecheck`, `npm run build`.

## Documentation (same-change requirement)

- `backend/docs/api.md` — new `/admin/*` endpoints, auth changes, enforcement matrix
- `backend/docs/data-model.md` — users.role/is_active, user_clients, global_settings
- `backend/docs/architecture.md` — authorization layer
- `frontend/docs/architecture.md` — admin routes, nav, guards
- New ADR for role model (docs/decisions/0009-basic-rbac.md)
