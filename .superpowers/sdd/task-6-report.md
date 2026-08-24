# Task 6 Report

## Status

Implemented PostgreSQL Compose and environment documentation on top of Task 5
commit `2260d86`.

## Files changed

- `docker-compose.yml` — PostgreSQL-only Compose configuration using
  `postgres:16.4-alpine`, configurable database credentials and host port, a
  named persistent volume, and a `pg_isready` health check.
- `.env.example` — safe local placeholders for Compose and backend settings,
  including a non-production session-secret marker and the M0 one-worker
  requirement.
- `backend/app/config.py` — aligns the default lazy database URL with the
  host-published local PostgreSQL service; no ORM, schema, or connection is
  created.
- `backend/tests/test_environment_docs.py` — repository-root environment key
  coverage and PostgreSQL-only Compose structure/health-check coverage.

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

docker compose config
valid PostgreSQL-only configuration; image postgres:16.4-alpine, named
postgres_data volume, configurable POSTGRES_* values and port, and pg_isready
health check.

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

- `.env.example` now explicitly documents that changes to any `POSTGRES_*`
  value require the corresponding `DATABASE_URL` update, and identifies the
  host-local default relationship.
- `backend/tests/test_environment_docs.py` now parses the Compose YAML through
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
docker compose config
name: m0-foundation
services:
  postgres:
    environment:
      POSTGRES_DB: gmc_feed
      POSTGRES_PASSWORD: postgres
      POSTGRES_USER: postgres
    healthcheck:
      test:
        - CMD-SHELL
        - pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}
      timeout: 5s
      interval: 5s
      retries: 5
    image: postgres:16.4-alpine
    networks:
      default: null
    ports:
      - mode: ingress
        target: 5432
        published: "5432"
        protocol: tcp
    volumes:
      - type: volume
        source: postgres_data
        target: /var/lib/postgresql/data
        volume: {}
networks:
  default:
    name: m0-foundation_default
volumes:
  postgres_data:
    name: m0-foundation_postgres_data

docker compose up -d --wait postgres && docker compose ps && docker compose down
Container m0-foundation-postgres-1 Healthy
m0-foundation-postgres-1   postgres:16.4-alpine   ...   Up 5 seconds (healthy)
container and network removed without errors.

git diff --check
(no output; exit 0)

The focused parser test was also run directly:

```text
uv run pytest tests/test_environment_docs.py -q
..                                                                       [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/ozon/gmc_feed_master/.worktrees/m0-foundation/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
2 passed, 1 warning in 0.11s

docker compose config -q
(no output; exit 0)
```
```
