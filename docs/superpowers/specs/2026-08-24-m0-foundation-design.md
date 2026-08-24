# M0 Foundation Design

Status: approved

Implements milestone M0 and the binding architecture and API decisions in
`gmc-feed-engine-spec.md` sections 2 and 8. M0 establishes the repository,
local development tooling, CI, PostgreSQL service, FastAPI and Vite/React
skeletons, and a working single-operator login/logout vertical slice.

## Scope and Acceptance

M0 is complete when:

- The backend starts through an application factory and exposes health and
  session-authenticated endpoints.
- The frontend provides login, an authenticated shell, and logout.
- The initial operator is configured from environment variables.
- PostgreSQL runs as the only Dockerized component and has a health check.
- CI runs backend tests, frontend tests, and frontend type/build checks.
- Session behavior is covered by tests for login, logout, invalid sessions,
  idle expiry, absolute expiry, renewal rules, and cookie attributes.

M0 does not create the business database schema. M1 introduces the schema and
replaces the in-process session store with a PostgreSQL-backed implementation.

## Repository and Tooling

The repository keeps backend and frontend dependencies separate:

- `backend/pyproject.toml` and its lockfile own Python dependencies and test
  commands.
- `frontend/package.json` and its lockfile own TypeScript, Vite, React, and
  frontend test dependencies.
- `backend/app/` contains the FastAPI application, settings, auth service,
  and session stores.
- `frontend/src/` contains the React application and login flow.
- `tests/` contains cross-cutting or contract-level tests; backend-local and
  frontend-local tests remain alongside their respective projects when that
  provides clearer ownership.
- `.env.example` documents settings without including credentials or secrets.
- `.github/workflows/ci.yml` runs all required checks.

Dependencies are pinned to exact versions on first use, with the selected
versions recorded in `docs/decisions.md`. Current, version-specific library
documentation is consulted before code is written against each third-party
library.

## Backend Boundaries

The backend uses a FastAPI application factory so tests can create isolated
applications and dependency overrides without relying on import-time global
state. Settings are loaded from environment variables and include database
connection settings, initial operator credentials, the session secret, and
session expiry configuration.

The auth route layer is intentionally thin:

- `POST /auth/login` validates the configured operator credentials, creates a
  session, sets the session cookie, and returns the authenticated user.
- `POST /auth/logout` invalidates the current session and clears the cookie.
- `GET /auth/me` validates the current session and returns the authenticated
  user. It is a read endpoint and does not renew idle expiry.
- A protected explicit-interaction endpoint is used by the frontend to prove
  that user activity can renew idle expiry without making all authenticated
  requests renew it.
- Health endpoints are available for local development and CI. They do not
  require an authenticated session.

The auth service depends on a `SessionStore` interface with exactly these
operations:

- `create(user_id, now)`: creates and returns an opaque session identifier.
- `validate(session_id, now, renew_idle)`: returns the session identity when
  valid and optionally renews idle expiry.
- `invalidate(session_id)`: removes or invalidates one session.

The interface is the only session persistence dependency at auth call sites.
M1 can therefore provide a PostgreSQL implementation without changing route
or service consumers.

## Session Semantics

M0 uses a process-local in-memory session store. Session records contain the
user identity, creation time, last explicit interaction time, idle expiry,
and absolute expiry. Session identifiers are opaque, cryptographically random
values; session data is not serialized into the cookie.

Defaults are configurable through environment variables:

- `SESSION_IDLE_MINUTES=30`: sliding idle timeout.
- `SESSION_ABSOLUTE_HOURS=12`: hard absolute lifetime and cookie lifetime.

Idle expiry is renewed only by explicit user interaction. Automated dashboard
polling and other read-only endpoints, including status and quality-finding
reads, must call validation without renewal. The absolute expiry is never
extended and is aligned with the cookie's expiry. Expired sessions return
`401` and cannot be renewed.

The cookie uses the following attributes:

- `HttpOnly` enabled.
- `Secure` enabled.
- `SameSite=Lax`.
- An expiry/max-age bounded by the absolute session lifetime.

The in-process store requires a single backend process and one worker. A
restart invalidates all sessions. These are documented operational limits,
not hidden fallback behavior.

## Frontend Flow

The React application starts at a login view when no authenticated user is
known. It submits credentials to `POST /auth/login`, displays validation
errors, and transitions to an authenticated shell on success. The shell reads
the current user, provides an explicit interaction path, and logs out through
`POST /auth/logout`, returning to the login view after the session is cleared.

The frontend uses React built-ins only for client state. M0 does not introduce
a global store. Server state is fetched through the selected HTTP/query
boundary and is not copied into a client-side store.

## PostgreSQL and CI

`docker-compose.yml` provisions PostgreSQL only. The service has a health
check and configurable credentials/port. Backend and frontend run natively on
the host, matching the binding architecture decision.

CI starts or provisions PostgreSQL as needed, waits for readiness, installs
the pinned backend and frontend dependencies, and runs:

- backend unit/API tests;
- frontend component/flow tests;
- frontend TypeScript validation and production build.

The CI checks also verify that the backend can load its settings and that the
health endpoint responds.

## Testing Strategy

Backend tests cover the session store independently and the API behavior
through an application factory. They use a controllable clock so idle and
absolute expiry boundaries are deterministic. Tests explicitly prove that:

- `GET /auth/me` and polling-style reads do not slide idle expiry;
- explicit interaction renewal slides idle expiry;
- renewal never moves the absolute expiry;
- logout invalidates the session;
- cookie attributes and absolute expiry are emitted as designed;
- restart semantics are inherent to the in-memory implementation.

Frontend tests cover the login form, failed login, successful authenticated
state, and logout transition. The M0 plugin system, database schema,
ingestion, staging, pipeline, QC, XML writer, scheduling, and export API are
explicitly out of scope.

## M1 Auth Persistence Gate

M1 includes the PostgreSQL-backed `SessionStore` as a named deliverable. Its
acceptance criterion is: changing the operator password invalidates all
existing sessions, so every previously issued session receives `401` on its
next validation. The behavior must be tested at the store/service boundary
and through the authenticated API.
