# M1 Persistence and Attribute Registry Design

Status: approved

Implements milestone M1 and the binding conceptual data model in
`gmc-feed-engine-spec.md` section 4, plus the GMC Attribute Registry
requirements in section 5.6. M1 adds PostgreSQL persistence, Alembic
migrations, persistent authentication, and a checked-in generated registry
artifact derived from `gmc_def.md`.

## Scope and Acceptance

M1 is complete when:

- Alembic upgrades an empty PostgreSQL database to the baseline schema.
- The baseline migration downgrades and re-upgrades cleanly.
- SQLAlchemy metadata and migrations agree on the schema's tables,
  relationships, constraints, and indexes.
- The application uses PostgreSQL for users and sessions without mutating
  schema implicitly at startup.
- The first startup seeds one Argon2id-hashed operator from environment
  variables, while later startups never overwrite the persisted password.
- Login, logout, `/auth/me`, and explicit interaction work through the
  PostgreSQL-backed session store.
- Session idle/absolute semantics remain unchanged, including non-renewing
  reads and hard absolute expiry.
- Password change invalidates every existing session, including the session
  that initiated the change; the old password stops working and the new one
  works.
- Registry generation from the current `gmc_def.md` is deterministic and
  check mode detects a stale generated artifact.
- The generated registry contains representative scalar, repeated,
  structured, enum, date, price, deprecated, and vehicle-only definitions.
- M0 in-memory store tests remain green through dependency injection.

Readers, staging, plugins, QC, XML writing, scheduling, and frontend database
management screens remain out of scope.

## Persistence and Migration Architecture

M1 uses SQLAlchemy 2.x's async engine and session API with `asyncpg`. Alembic
owns schema migrations. The application receives an async database session
through a dependency/lifecycle boundary, and repositories isolate persistence
operations from route handlers.

The existing `SessionStore` interface remains the auth boundary. A
`PostgresSessionStore` implements `create`, `validate`, and `invalidate` so
auth call sites do not depend on SQLAlchemy details. Tests may continue to
inject `InMemorySessionStore`.

The first migration is a reviewed baseline migration. It creates the complete
M1 schema in one step; later milestones add migrations incrementally.
Application startup does not silently create or alter schema. Development,
CI, and deployment procedures run Alembic explicitly.

The M0 idle and absolute expiry rules remain unchanged. PostgreSQL sessions
store creation time, last explicit interaction, idle expiry, absolute expiry,
and the user revocation generation observed when the session was created.
Validation rejects missing, malformed, expired, or revoked sessions. Explicit
interaction updates only the idle expiry and last-interaction timestamp.

## Database Schema

The baseline migration includes:

- `users`
- `sessions`
- `clients`
- `feed_sources`
- `plugins`
- `plugin_configs`
- `plugin_data`
- `module_pipelines`
- `module_instances`
- `ingestion_runs`
- `staging_products`
- `staging_history`
- `quality_findings`
- `export_runs`
- `export_versions`

`users` stores the operator username, Argon2id password hash, timestamps,
and a password/session revocation generation. A unique constraint enforces
one row per username. `sessions` stores only a SHA-256 hash of the opaque
cookie token, the user ID, timestamps, expiry values, and the revocation
generation observed at creation. The raw token is never persisted.

The first startup seeds exactly one user only when the user table is empty.
Environment credentials never overwrite an existing password. Password
changes update the hash, increment the user revocation generation, and
invalidate all existing sessions transactionally.

The schema uses explicit foreign keys, unique constraints, check constraints,
and indexes. Important constraints include:

- `feed_sources.client_id` references `clients`.
- `module_instances.pipeline_id` references `module_pipelines`.
- `module_instances.plugin_id` references `plugins`.
- Staging products are unique on `(feed_source_id, product_id)`.
- Session lookup is indexed by token identifier and user ID.
- Export versions are unique on `(feed_source_id, version_number)`.
- JSONB stores the conceptual JSON fields specified by the product spec.

Application/domain validation owns enum-like values unless a PostgreSQL
constraint materially improves integrity without making later evolution
brittle. Foreign keys use restrictive defaults where deleting a parent could
silently remove operational history. Retention and purge behavior remains an
application concern and is not implemented prematurely in M1.

## Authentication Persistence

Existing login, logout, `/auth/me`, and `/auth/interaction` routes keep their
API shape while using persisted users and sessions.

`POST /auth/password` is added for the operator password change. It requires
the current authenticated session and accepts the current password plus a new
password. Current-password failure returns `401`; invalid new-password input
returns `422`; success invalidates the caller's session and returns a generic
success response. The client must log in again.

The password hash uses Argon2id. First startup hashes the initial password;
subsequent starts do not replace it from the environment. Password hashes and
session data never appear in API responses or cookies.

## Attribute Registry Pipeline

The registry is generated deterministically from `gmc_def.md`:

1. A strict parser reads the documented Markdown tables and extracts canonical
   attributes, types, requirement levels, limits, enums, and structured
   sub-attributes.
2. A normalized internal model records canonical name, kind, ordered
   sub-fields, type metadata, enum values, length/cardinality limits,
   requirement/conditionality metadata, export status, feed-domain marker,
   and source-line diagnostics.
3. A generator writes `backend/registry/attributes.json` with stable ordering
   and formatting.
4. Runtime loads only the checked-in JSON artifact and validates its schema.
5. CI runs generation in check mode and fails if regeneration changes the
   committed artifact.

The parser rejects duplicate canonical attributes, malformed rows, unsupported
type syntax, and structured fields whose order cannot be determined.
Deprecated and removed attributes remain represented with status metadata but
are marked non-exportable. Vehicle-feed-only attributes receive a feed-domain
marker and are not treated as standard primary-feed attributes.

The runtime loader fails clearly when the artifact is missing or invalid. M1
does not store the registry in PostgreSQL. The checked-in artifact is
versioned with the application and becomes the source consumed by later
readers, field mapping, QC, and XML writer milestones.

## Verification

Tests use a real PostgreSQL service for migration and persistence checks:

- Empty database upgrade, downgrade, and re-upgrade.
- Metadata/migration agreement for names, relationships, constraints, and
  indexes.
- First-user seeding and no-overwrite behavior.
- Persisted login/logout/session validation and restart persistence.
- Non-renewing reads, explicit idle renewal, absolute expiry, and revocation.
- Password-change invalidation of every session, including the initiating one.
- Old-password rejection and new-password success after a password change.
- Representative parser fixtures and full-source registry generation.
- Deterministic generation and stale-artifact check failure.
- Invalid/missing artifact and malformed source diagnostics.
- Continued M0 in-memory store, frontend, and build checks.
