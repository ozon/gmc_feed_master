# ADR-0009: Basic RBAC — Two Roles, Client Assignment, Admin Area

## Status
Accepted

## Context
GMC Feed Master started with single-user auth: one seeded operator account,
every authenticated user sees and manages every client (agency model:
1 client → n feed sources). Multi-person agencies need client isolation —
a client's operator should see only their client(s) — and an administrative
surface for user lifecycle and global configuration. Prior to this ADR all
runtime settings came from the environment (.env) and retention days were
hardcoded constants in `app/staging/purge.py`.

## Decision
1. **Two roles** as literal strings on `users.role`: `admin` and `user`.
   No roles/permissions tables, no permission matrix (YAGNI — exactly two
   groups are required). Adding a third role later is a small migration.
2. **Client assignment** via a `user_clients` join table (many-to-many,
   CASCADE on both FKs). A `user` gets full functional scope inside their
   assigned clients (runs, exports, plugin configs, monitoring); admins are
   unrestricted and carry no assignment rows.
3. **Enforcement in FastAPI dependencies** (`app/access.py`), not middleware
   or Postgres RLS:
   - `get_current_user` loads role + assigned client ids per request
     (fresh: role/assignment changes apply immediately; inactive users get
     401);
   - `require_admin` guards `/admin/*` and client CRUD (403);
   - `enforce_scope_access` is a router-level dependency reading
     `client_id`/`feed_source_id` from path AND query params, returning
     **404** (not 403) for unassigned resources — no existence leak.
   - `GET /clients` and the dashboard summary filter server-side for
     `user` role.
4. **Deactivation, never deletion** (`users.is_active`): preserves FK and
   session integrity and run attribution. Password reset bumps
   `revocation_generation`, killing existing sessions.
5. **Seed user is admin**; the m11 migration promoted all pre-existing
   users to admin. The non-DB fallback mode (session store injected
   without a PostgreSQL boundary) is treated as admin/unrestricted so
   single-user installs stay fully functional.
6. **DB-backed global settings**: a single-row `global_settings` table
   (lazy-seeded with 90-day defaults) holds the three retention values the
   purge jobs read; editable via `PUT /admin/settings` (admin only).
   Replaces the hardcoded 90-day constants.

## Consequences
- One extra user-load query per request (acceptable; sessions already hit
  the DB once per validation).
- Client CRUD moved from the dashboard into the admin area
  (`/admin/clients`); the dashboard is a read-only listing for everyone.
- 404-instead-of-403 for unassigned access trades explicitness for
  anti-enumeration (consistent with the existing "client not found"
  responses).
- The frontend nav group and `RequireAdmin` guard are UX only — the backend
  is the enforcement boundary.
- `role` is a free String column (no CHECK constraint); app-level
  validation (pydantic `Literal["admin", "user"]`) is the gate. A future
  migration can add a CHECK.
- Plugins contributing routes under `/plugins/{id}/...` inherit router-level
  scope enforcement only where mounted on the guarded routers; plugin-owned
  custom routes must apply their own checks if they expose client-scoped
  data beyond the reserved config/data routes.
