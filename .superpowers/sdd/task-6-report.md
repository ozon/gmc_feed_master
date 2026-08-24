# Task 6 report

Implemented persistent authentication integration on top of Task 5:

- Added async database-session dependency wiring and PostgreSQL session-store selection when a session factory is configured.
- Added persisted password verification for login while preserving in-memory auth injection and M0 response shapes.
- Added `POST /auth/password` with non-empty new-password validation, generic credential failures, transactional password hash/revocation-generation update, caller-session invalidation, and cookie clearing.
- Added explicit startup first-user seeding after migrations without schema mutation or overwriting an existing user.
- Added PostgreSQL API integration tests covering multiple sessions, password rotation, old/new password behavior, wrong current password, and validation.
- Documented explicit migration and startup-seeding behavior.

Verification:

- PostgreSQL Compose service started and Alembic migrations upgraded to head.
- `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest -q`: 68 passed.
- `uv run python -m compileall app alembic`: passed.

Concerns:

- Test output retains existing dependency/deprecation warnings.
- PostgreSQL integration tests require the Compose database and `TEST_DATABASE_URL`.

## Task 6 review-fix follow-up

- `create_app(settings=...)` now creates the async SQLAlchemy engine and session
  factory from settings when no factory is injected, stores the engine on app
  state, disposes it during lifespan shutdown, and retains explicit injected
  factory/session-store precedence. Startup still performs no schema creation.
- Startup seeding is exercised through the actual lifespan after Alembic
  migrations. Tests cover first-user seeding, idempotent second startup without
  credential overwrite, and authentication/session persistence across a newly
  created app instance.
- PostgreSQL integration fixtures now create a unique temporary database,
  apply Alembic `head`, and drop the database with force cleanup. The
  PostgreSQL auth, user, and session tests no longer call
  `Base.metadata.create_all`; M0 in-memory injection tests remain isolated.
- Repository transactions now use a nested transaction when a caller already
  owns a transaction instead of unconditionally rolling it back, preserving
  unrelated caller work while retaining atomic password hash and revocation
  generation updates.
- Added/retained coverage for persisted login, logout, `me`, interaction idle
  renewal, password change, all-session invalidation, caller cookie clearing,
  old/new password behavior, and migration-backed schema.

Review-fix verification outputs:

- `docker compose up -d postgres`: PostgreSQL Compose service running.
- `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run alembic upgrade head`: passed.
- `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest tests/test_postgres_auth.py -q`: 3 passed, 4 warnings.
- `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest -q`: 69 passed, 21 warnings.
- `uv run python -m compileall app alembic`: passed.
- Temporary isolated PostgreSQL databases were dropped by fixture cleanup.

Remaining concerns:

- Existing Starlette/httpx and Alembic configuration deprecation warnings remain.
