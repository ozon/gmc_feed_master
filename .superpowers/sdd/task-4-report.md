# Task 4 Report

## Files

- `backend/app/security/__init__.py`
- `backend/app/security/passwords.py`
- `backend/app/persistence/__init__.py`
- `backend/app/persistence/users.py`
- `backend/tests/test_passwords.py`
- `backend/tests/test_user_persistence.py`

Implemented the Argon2id `PasswordHasher` wrapper and async PostgreSQL user repository. Initial seeding locks the users table and inserts only when empty; existing credentials are preserved. Password verification is safe for mismatches and invalid hashes. Password changes lock the user row, require the current password, replace the hash, and increment revocation generation within one transaction.

## Commands and output

- `uv run pytest tests/test_passwords.py tests/test_user_persistence.py -q` (with `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed`): **6 passed, 1 warning**
- `uv run pytest tests/test_models.py tests/test_migrations.py -q` (with PostgreSQL): **9 passed, 4 warnings**
- `uv run pytest -q` (with PostgreSQL): **55 passed, 4 warnings**
- `uv run python -m compileall app`: **passed**
- `git diff --check`: **passed**

## Concerns

- Existing project test suite emits pre-existing deprecation warnings from Starlette/httpx and Alembic configuration.
- PostgreSQL persistence tests require a healthy `TEST_DATABASE_URL`; no SQLite fallback is used.

## Review Fixes

- Repository write operations now own their transaction boundary: if a normal
  SQLAlchemy autobegin read transaction is active, it is rolled back before the
  repository starts its single explicit transaction. This makes
  `change_password` usable immediately after a lookup/verification on the same
  request-scoped `AsyncSession`, while retaining one row-lock/hash-update/
  revocation-increment transaction. Initial seeding uses the same boundary.
- Added regression coverage for read/verify followed immediately by password
  change and for seeding after a normal autobegun read. Persistence fixtures
  require the `postgresql+asyncpg://` URL explicitly.
- Moved exact `argon2-cffi==25.1.0` to runtime dependencies and regenerated
  `backend/uv.lock`.

## Review Fix Verification

- `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest tests/test_passwords.py tests/test_user_persistence.py -q`: **7 passed, 1 warning**
- `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest -q`: **56 passed, 4 warnings**
- `uv run python -m compileall app alembic`: **passed**
- `uv lock --check`: **passed**
