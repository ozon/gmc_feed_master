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
