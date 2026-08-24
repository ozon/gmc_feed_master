# M1 Task 1 Report

## Files changed

- `backend/pyproject.toml`: added exact pins for SQLAlchemy, asyncpg, Alembic,
  argon2-cffi, pytest 8.4.2, and pytest-asyncio.
- `backend/uv.lock`: regenerated with the resolved dependency graph.
- `backend/app/config.py`: added settings-owned async database URL
  normalization for PostgreSQL URLs.
- `backend/app/db/__init__.py`: exported the database boundary functions.
- `backend/app/db/engine.py`: added lazy `AsyncEngine` creation,
  `async_sessionmaker` with `expire_on_commit=False`, and the FastAPI async
  session dependency with cleanup.
- `backend/tests/test_db_engine.py`: added focused URL, lazy engine, session
  factory, and dependency cleanup tests.
- `docs/decisions.md`: recorded exact resolved versions and the pytest
  compatibility rationale.

No models, migrations, authentication persistence, or registry code was added.

## Commands and output

### Dependency resolution

```text
$ uv add 'sqlalchemy==2.0.43' 'asyncpg==0.30.0' 'alembic==1.16.4' 'argon2-cffi==25.1.0' --dev 'pytest==8.4.2' 'pytest-asyncio==1.1.0'
Resolved 38 packages in 186ms
Installed: alembic==1.16.4, argon2-cffi==25.1.0, asyncpg==0.30.0,
pytest==8.4.2, pytest-asyncio==1.1.0, sqlalchemy==2.0.43
```

The initial attempt to retain pytest 9.1.1 was rejected because
pytest-asyncio 1.1.0 requires pytest >=8.2 and <9; the exact pytest 8.4.2 pin
was selected to resolve that documented compatibility constraint.

### Focused tests

```text
$ cd backend && uv run pytest tests/test_db_engine.py -q
4 passed, 1 warning in 0.28s
```

### Full tests and compile/lock checks

```text
$ cd backend && uv run pytest -q
40 passed, 1 warning in 1.19s

$ uv run python -m compileall app
Listing 'app'...
Listing 'app/db'...

$ uv lock --check
Resolved 38 packages in 1ms
```

## Concerns

- The existing FastAPI/httpx combination emits a pre-existing
  `StarletteDeprecationWarning` about httpx; it does not fail tests.
- `get_db_session` expects the application or request state to provide
  `db_session_factory`; wiring an application-wide factory is intentionally
  deferred because this task does not alter app startup or persistence.

## Review fixes

### Files changed

- `backend/pyproject.toml`: moved the runtime packages
  `sqlalchemy==2.0.43` and `asyncpg==0.30.0` from the dev dependency group into
  `[project].dependencies`.
- `backend/uv.lock`: regenerated with the runtime dependency declarations and
  exact pins preserved.
- `backend/app/db/engine.py`: configured sessions with
  `close_resets_only=False`, making generator finalization permanently close
  the yielded `AsyncSession`.
- `backend/tests/test_db_engine.py`: strengthened the lifecycle test to assert
  that executing on the finalized session raises `InvalidRequestError` for a
  permanently closed session.
- `docs/decisions.md`: clarified that the M1 pytest pin `8.4.2` supersedes the
  M0 historical pin `9.1.1` for the backend development environment.

### Commands and output

```text
$ cd backend && uv lock
Resolved 38 packages in 41ms

$ uv run pytest tests/test_db_engine.py -q
4 passed, 1 warning in 0.23s

$ uv run pytest -q
40 passed, 1 warning in 1.12s

$ uv run python -m compileall app
Listing 'app'...
Listing 'app/db'...

$ uv lock --check
Resolved 38 packages in 1ms
```

The warning is the pre-existing `StarletteDeprecationWarning` documented above.
