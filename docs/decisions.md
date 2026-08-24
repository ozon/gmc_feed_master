# Implementation Decisions

Decisions recorded here are implementation-level choices derived from the
binding product specification. Dates use ISO 8601 calendar dates.

## 2026-08-24

### M0 dependency and workspace layout

- **Topic:** Initial tooling and repository structure
- **Decision:** Keep backend and frontend as separate projects under
  `backend/` and `frontend/`, use `uv` with a committed lockfile for Python,
  and use Vite/npm with a committed lockfile for the frontend. Pin each
  dependency to an exact version on first use.
- **Rationale:** This preserves the specified deployment boundaries while
  keeping dependency ownership clear in a greenfield repository. Exact pins
  make CI and milestone verification reproducible.

### M0 session persistence

- **Topic:** Session store implementation
- **Decision:** M0 uses an in-process session store behind a `SessionStore`
  interface exposing `create`, `validate`, and `invalidate`. A PostgreSQL
  implementation is a named M1 deliverable and must not require changes at
  auth call sites.
- **Rationale:** The M0 schema is not yet available, but the interface keeps
  persistence replaceable and makes the temporary deployment constraint
  explicit rather than leaking process-local state through the API layer.

### M0 in-process session constraints

- **Topic:** Operational limits of the M0 session store
- **Decision:** M0 supports a single backend process with one worker. A
  process restart invalidates all sessions. The session secret is loaded from
  the environment. The session cookie is `HttpOnly`, `Secure`, and
  `SameSite=Lax`.
- **Rationale:** These constraints are required for safe use of process-local
  state and reduce cookie exposure while PostgreSQL persistence is pending.

### M0 session expiry and renewal

- **Topic:** Session lifetime
- **Decision:** Idle expiry defaults to 30 minutes and absolute expiry defaults
  to 12 hours. Both are configurable with `SESSION_IDLE_MINUTES` and
  `SESSION_ABSOLUTE_HOURS`. Idle expiry is sliding only after explicit user
  interactions. Automated polling and read-only status/finding endpoints do
  not renew it. Absolute lifetime is a hard cap and is aligned with cookie
  expiry.
- **Rationale:** A dashboard's polling must not keep an unattended session
  alive indefinitely, while normal operator activity should remain usable.

### M1 password-change invalidation

- **Topic:** Acceptance gate for persistent auth
- **Decision:** M1 must include PostgreSQL session persistence and verify that
  a password change invalidates all existing sessions. Every session issued
  before the password change must return `401` at its next validation.
- **Rationale:** Password changes must revoke previously issued credentials;
  this is a concrete milestone acceptance criterion rather than an unnamed
  future hardening task.
