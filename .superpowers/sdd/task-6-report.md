# Task 6 Report

## Status

Implemented PostgreSQL Compose and environment documentation on top of Task 5
commit `2260d86`.

## Files changed

- `docker-compose.yml` — PostgreSQL-only Compose configuration using
  `postgres:16.4-alpine`, configurable database credentials and host port, a
  named persistent volume, and a `pg_isready` health check.
- `.env.example` — safe local-only environment placeholders for Compose and
  backend settings, including the M0 one-worker requirement.
- `backend/app/config.py` — aligns the default lazy database URL with the
  host-published local PostgreSQL service; no ORM, schema, or connection is
  created.
- `backend/tests/test_environment_docs.py` — environment key coverage and
  PostgreSQL-only Compose structure/health-check coverage.

## Verification commands and output

From `backend/`:

```text
uv run pytest tests/test_environment_docs.py -q
2 passed, 1 warning in 0.01s

uv run pytest -q
32 passed, 1 warning in 0.71s

uv run python -m compileall app
Listing 'app'...
```

From the repository root:

```text
git diff --check
exit 0

docker compose config -q
exit 0

docker compose up -d postgres
health=starting
health=starting
health=starting
health=healthy

docker compose ps
postgres container: Up 6 seconds (healthy)

docker compose down
container and network removed without errors.
```

## Concerns

- Backend tests emit the existing Starlette deprecation warning about using
  `httpx` with `starlette.testclient`; all tests pass.
- The Compose file intentionally starts only PostgreSQL. M0 still uses its
  in-process session store and requires one backend worker; PostgreSQL remains
  available for the later persistence milestone.

## Review-fix details

- `.env.example` explicitly documents that changes to any `POSTGRES_*` value
  require the corresponding `DATABASE_URL` update, and identifies the
  host-local default relationship.
- `backend/tests/test_environment_docs.py` parses the Compose YAML through
  `docker compose config --format json` and the standard-library JSON parser;
  it asserts exactly one service named `postgres` and a health check without
  adding an unpinned YAML dependency.

## Review-fix verification

From `backend/`:

```text
uv run pytest -q
................................                                         [100%]
32 passed, 1 warning in 0.85s
```

From the repository root:

```text
docker compose config -q
(no output; exit 0)

docker compose up -d --wait postgres && docker compose ps && docker compose down
Container m0-foundation-postgres-1 Healthy
m0-foundation-postgres-1   postgres:16.4-alpine   ...   Up 5 seconds (healthy)
container and network removed without errors.
```

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

## Preserved prior Task 6 report details

The preceding report also recorded the following historical verification and
documentation details; they are retained here as an append-only audit trail:

- The Compose file is PostgreSQL-only and uses `postgres:16.4-alpine`,
  configurable credentials and host port, a named `postgres_data` volume, and
  a `pg_isready` health check.
- `.env.example` contains safe local placeholders, including the
  non-production session-secret marker and the M0 one-worker requirement.
- The environment documentation states that changing any `POSTGRES_*` value
  requires the matching `DATABASE_URL` update and identifies the host-local
  default relationship.
- `backend/tests/test_environment_docs.py` parses `docker compose config
  --format json` with the standard-library JSON parser, asserts exactly one
  service named `postgres`, and checks the health check without adding an
  unpinned YAML dependency.
- Historical focused verification: `uv run pytest
  tests/test_environment_docs.py -q` reported `2 passed, 1 warning`; the
  historical full suite reported `32 passed, 1 warning`; and
  `uv run python -m compileall app` completed successfully.
- Historical repository verification included successful `git diff --check`,
  `docker compose config -q`, a healthy Compose PostgreSQL service, and clean
  `docker compose down` cleanup.
- M0 continues to use its in-process session store and requires one backend
  worker; PostgreSQL remains available for the persistence milestone.

## Task 6 review-fix follow-up: injection precedence and persisted API coverage

- Explicit `session_store` injection now prevents settings-based engine/factory
  construction, startup user seeding, and DB session dependency creation. This
  keeps an injected `InMemorySessionStore` as the sole auth boundary even when
  settings contain a PostgreSQL URL.
- The password route now returns the tested `501` response
  `Password changes require the configured PostgreSQL persistence boundary`
  when an explicit session store is injected, rather than silently changing a
  different database-backed user store.
- Default settings-backed PostgreSQL behavior and explicit
  `db_session_factory` injection remain unchanged.
- The temporary database fixture now wraps database creation, migration setup,
  yielding, and forced drop cleanup in one outer `try/finally`, including
  migration setup failures.
- Added persisted API coverage for logout cookie clearing and invalidation,
  `/auth/interaction` idle renewal, and explicit injection precedence/password
  behavior. Invalid sessions remain rejected after persisted logout.

## Review-fix verification outputs

From the repository root/worktree:

```text
docker compose up -d --wait postgres
Container m1-persistence-registry-postgres-1 Healthy
```

From `backend/`:

```text
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest tests/test_auth_api.py tests/test_postgres_auth.py -q
................                                                         [100%]
16 passed, 7 warnings in 5.68s

TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest -q
........................................................................ [ 98%]
.
73 passed, 24 warnings in 19.27s

uv run python -m compileall app alembic
Listing 'app'...
Listing 'app/db'...
Listing 'app/models'...
Listing 'app/persistence'...
Listing 'app/security'...
Listing 'alembic'...
Listing 'alembic/versions'...

DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run alembic upgrade head
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

Cleanup:

```text
docker compose down --volumes
Container m1-persistence-registry-postgres-1 Stopped
Container m1-persistence-registry-postgres-1 Removed
Volume m1-persistence-registry_postgres_data Removed
Network m1-persistence-registry_default Removed

git diff --check
exit 0
```

Concerns remain limited to the existing Starlette/httpx and Alembic
configuration deprecation warnings reported by the test run.

## Remaining M1 Task 6 finding fix

- The module-level ASGI app now resolves `get_settings()` when `create_app()`
  receives no explicit settings, session store, or database session factory.
  With configured environment settings this constructs the async SQLAlchemy
  engine/session factory and selects `PostgresSessionStore` by default.
- Settings validation failures are treated as an unconfigured M0 import path,
  so `import app.main` remains safe without persistence credentials.
- Explicit `session_store` precedence, explicit `db_session_factory` injection,
  and in-memory test paths remain unchanged. No schema creation was added.
- Added a regression subprocess test proving the default ASGI app resolves
  configured settings and selects PostgreSQL persistence.

## Remaining-finding verification outputs

From `backend/`:

```text
uv run pytest tests/test_tooling.py -q
9 passed, 1 warning in 1.81s

TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest tests/test_auth_api.py tests/test_postgres_auth.py -q
16 passed, 7 warnings in 6.39s

TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest -q
74 passed, 24 warnings in 20.47s

uv run python -m compileall app alembic
completed successfully

DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run alembic upgrade head
completed successfully (M1 baseline)
```

From the repository root:

```text
docker compose up -d --wait postgres
Container m1-persistence-registry-postgres-1 Healthy
docker compose config -q
completed successfully
docker compose down --volumes
completed successfully
git diff --check
completed successfully
```

The initial combined command was retried from `backend/` after root-level `uv`
reported that `pytest` was unavailable; no test failure resulted. Existing
Starlette/httpx, Pytest collection, and Alembic deprecation warnings remain.
