# M1 Persistence and Attribute Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit Alembic-managed PostgreSQL persistence, async SQLAlchemy authentication, Argon2id password handling, and a deterministic checked-in GMC Attribute Registry generated from `gmc_def.md`.

**Architecture:** The M1 database boundary uses SQLAlchemy 2.x async sessions with `asyncpg`, while Alembic owns an explicit baseline migration for all conceptual M1 entities. The existing `SessionStore` names and semantics remain the auth boundary, but its methods become awaitable so both the PostgreSQL implementation and injected in-memory test implementation are non-blocking. A strict Markdown parser generates `backend/registry/attributes.json`; runtime loads only that artifact and CI checks for source/artifact drift.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x async ORM, `asyncpg`, Alembic, PostgreSQL 16.4, `argon2-cffi`, Pydantic Settings, pytest, pytest-asyncio, and the existing React/Vite toolchain.

## Global Constraints

- Implement M1 only: database schema, core entity models, Attribute Registry loader, persistent auth, and password-change invalidation; readers, staging behavior, plugins, QC, XML, scheduling, and frontend database-management screens remain out of scope.
- PostgreSQL remains the only Dockerized component; backend/frontend run natively.
- Use SQLAlchemy 2.x's async engine/session API with `asyncpg`.
- Use Alembic for explicit schema migrations; application startup must not implicitly create or alter schema.
- Preserve `SessionStore` method names and semantics, but make `create`, `validate`, and `invalidate` awaitable in M1.
- PostgreSQL sessions store only a SHA-256 hash of the opaque cookie token; the raw token is never persisted.
- Preserve 30-minute configurable idle expiry and 12-hour configurable absolute expiry; reads do not renew, explicit interaction renews idle only, and absolute expiry is a hard cap.
- First startup seeds one Argon2id-hashed operator only when `users` is empty; environment credentials never overwrite an existing password.
- Password change invalidates every session, including the initiating session, and the old password no longer authenticates.
- Parse `gmc_def.md` strictly and generate deterministic `backend/registry/attributes.json`; runtime loads the checked-in artifact.
- Deprecated/removed registry attributes remain represented with non-exportable status; vehicle-feed-only attributes carry a domain marker.
- CI must fail when registry regeneration changes the checked-in artifact.
- Pin every newly introduced direct dependency to an exact version and record it in `docs/decisions.md`.
- Every task follows RED-GREEN-REFACTOR, runs focused verification, and commits its deliverable.

---

## File Map

- `backend/pyproject.toml`, `backend/uv.lock`: exact M1 dependency pins and test commands.
- `backend/app/db/engine.py`: async engine/session factory and FastAPI database dependency.
- `backend/app/db/base.py`: SQLAlchemy declarative base and model metadata import boundary.
- `backend/app/models/*.py`: focused SQLAlchemy entity models.
- `backend/app/persistence/users.py`: user seeding, lookup, password update, and revocation generation operations.
- `backend/app/persistence/sessions.py`: PostgreSQL `SessionStore` implementation.
- `backend/app/security/passwords.py`: Argon2id hashing/verification wrapper.
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`: Alembic configuration and async migration environment.
- `backend/alembic/versions/20260824_0001_m1_baseline.py`: reviewed complete M1 schema migration.
- `backend/registry/model.py`: typed normalized registry model.
- `backend/registry/parser.py`: strict `gmc_def.md` Markdown parser.
- `backend/registry/generate.py`: deterministic JSON generator and check mode.
- `backend/registry/loader.py`: runtime checked-in artifact loader and validation.
- `backend/registry/attributes.json`: generated checked-in runtime artifact.
- `backend/scripts/registry_check.py`: CI/local registry generation check command.
- `backend/tests/test_db_engine.py`: engine/session dependency tests.
- `backend/tests/test_models.py`: metadata and constraint tests.
- `backend/tests/test_migrations.py`: upgrade/downgrade/re-upgrade tests.
- `backend/tests/test_passwords.py`: Argon2id wrapper tests.
- `backend/tests/test_postgres_auth.py`: persisted auth/session/password-change tests.
- `backend/tests/test_registry_parser.py`: parser fixture tests.
- `backend/tests/test_registry_generation.py`: deterministic generation and stale check tests.
- `backend/tests/test_registry_loader.py`: artifact validation tests.
- `.github/workflows/ci.yml`: explicit Alembic and registry checks.
- `docs/decisions.md`: exact M1 dependency versions and implementation details.

---

### Task 1: Add M1 Dependencies and Async Database Configuration

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/app/config.py`
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/engine.py`
- Create: `backend/tests/test_db_engine.py`
- Modify: `docs/decisions.md`

**Interfaces:**
- Produces `create_engine(settings: Settings) -> AsyncEngine`.
- Produces `create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]`.
- Produces `async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]`.
- Produces a settings-normalized async database URL from the existing `DATABASE_URL` value.

- [ ] **Step 1: Write failing dependency/config tests**

Add tests that require an async URL and verify the factory does not connect at
construction time:

```python
def test_database_url_is_converted_to_asyncpg(settings):
    settings.database_url = "postgresql://postgres:postgres@localhost:5432/gmc_feed"
    assert async_database_url(settings) == (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed"
    )


def test_engine_creation_is_lazy(settings):
    engine = create_engine(settings)
    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"
```

- [ ] **Step 2: Run focused tests to verify RED**

Run from `backend/`: `uv run pytest tests/test_db_engine.py -q`

Expected: FAIL because the M1 dependencies, URL helper, engine factory, and
session dependency do not exist.

- [ ] **Step 3: Add exact dependencies and implement the async boundary**

Add exact pins for SQLAlchemy 2.x, asyncpg, Alembic, argon2-cffi, and
pytest-asyncio. Use current Context7 documentation for the APIs, resolve
compatible exact versions from the package index, update `uv.lock`, and record
the selected versions in `docs/decisions.md`.

Implement `engine.py` with `create_async_engine`, `async_sessionmaker` using
`expire_on_commit=False`, and an async generator that yields a session and
closes it. Do not call `create_all()` or connect during import/factory setup.
Use the existing root `.env` settings behavior.

- [ ] **Step 4: Run tests and compile checks**

Run:

```bash
cd backend
uv run pytest tests/test_db_engine.py -q
uv run python -m compileall app
uv lock --check
```

Expected: focused tests pass, compilation succeeds, and the lockfile is
consistent.

- [ ] **Step 5: Commit the database boundary**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/config.py backend/app/db backend/tests/test_db_engine.py docs/decisions.md
git commit -m "feat: add async SQLAlchemy database boundary"
```

### Task 2: Define SQLAlchemy Models and Alembic Async Environment

**Files:**
- Create: `backend/app/db/base.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/user.py`
- Create: `backend/app/models/session.py`
- Create: `backend/app/models/client.py`
- Create: `backend/app/models/feed_source.py`
- Create: `backend/app/models/plugin.py`
- Create: `backend/app/models/pipeline.py`
- Create: `backend/app/models/ingestion.py`
- Create: `backend/app/models/staging.py`
- Create: `backend/app/models/quality.py`
- Create: `backend/app/models/export.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/.gitkeep`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Produces `Base.metadata` containing all 15 M1 tables: `users`, `sessions`, `clients`, `feed_sources`, `plugins`, `plugin_configs`, `plugin_data`, `module_pipelines`, `module_instances`, `ingestion_runs`, `staging_products`, `staging_history`, `quality_findings`, `export_runs`, and `export_versions`.
- Produces typed SQLAlchemy models with explicit foreign keys, indexes, unique constraints, JSONB fields, timestamps, and revocation/hash columns.
- Produces an Alembic async environment that imports `Base.metadata` and calls migrations through `connection.run_sync`.

- [ ] **Step 1: Write metadata contract tests**

Assert exact table coverage and key constraints:

```python
def test_m1_table_set_is_complete():
    assert set(Base.metadata.tables) == {
        "users", "sessions", "clients", "feed_sources", "plugins",
        "plugin_configs", "plugin_data", "module_pipelines",
        "module_instances", "ingestion_runs", "staging_products",
        "staging_history", "quality_findings", "export_runs",
        "export_versions",
    }


def test_session_stores_hash_and_revocation_generation():
    columns = Base.metadata.tables["sessions"].c
    assert {"token_hash", "user_id", "absolute_expires_at", "revocation_generation"} <= set(columns)
    assert Base.metadata.tables["sessions"].indexes
```

Add tests for staging uniqueness, export-version uniqueness, feed/client and
pipeline/plugin foreign keys, and JSONB columns for conceptual JSON fields.

- [ ] **Step 2: Run model tests to verify RED**

Run from `backend/`: `uv run pytest tests/test_models.py -q`

Expected: FAIL because the model metadata does not exist.

- [ ] **Step 3: Implement focused models and async Alembic environment**

Use SQLAlchemy 2.x typed declarative mappings. Keep each model file focused;
avoid relationships that trigger implicit lazy IO in async code unless they
are explicitly eager-loaded. Use timezone-aware timestamp columns, PostgreSQL
JSONB, SHA-256 token hash, integer revocation generation, and explicit
indexes/constraints. Use restrictive foreign keys where deleting history
would be unsafe.

Configure `alembic.ini` with the backend database URL placeholder and async
`env.py` using the documented `async_engine_from_config` and
`connection.run_sync` pattern. Import every model before assigning
`target_metadata = Base.metadata`.

- [ ] **Step 4: Run model tests and compile checks**

Run:

```bash
cd backend
uv run pytest tests/test_models.py -q
uv run python -m compileall app alembic
```

Expected: all metadata tests pass and compilation succeeds.

- [ ] **Step 5: Commit models and migration environment**

```bash
git add backend/app/db/base.py backend/app/models backend/alembic.ini backend/alembic backend/tests/test_models.py
git commit -m "feat: define M1 SQLAlchemy models"
```

### Task 3: Create and Verify the Baseline Migration

**Files:**
- Create: `backend/alembic/versions/20260824_0001_m1_baseline.py`
- Create: `backend/tests/test_migrations.py`
- Modify: `.env.example` for explicit migration URL documentation
- Modify: `README.md` for explicit migration command

**Interfaces:**
- Produces `alembic upgrade head` and `alembic downgrade base` for the M1 schema.
- Produces a migration test fixture that creates an isolated PostgreSQL database/schema and runs Alembic explicitly.

- [ ] **Step 1: Write failing migration tests**

Use a PostgreSQL test database configured by `TEST_DATABASE_URL`. Tests must
fail clearly when the variable is absent rather than silently switching to
SQLite. Cover upgrade, required table names, constraints/indexes, downgrade,
and re-upgrade:

```python
@pytest.mark.asyncio
async def test_baseline_upgrade_downgrade_reupgrade(alembic_config, database_url):
    command.upgrade(alembic_config, "head")
    assert await table_names(database_url) == EXPECTED_TABLES
    command.downgrade(alembic_config, "base")
    assert await table_names(database_url) == set()
    command.upgrade(alembic_config, "head")
    assert await table_names(database_url) == EXPECTED_TABLES
```

- [ ] **Step 2: Run migration tests to verify RED**

Run from `backend/` with a PostgreSQL service available:
`TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest tests/test_migrations.py -q`

Expected: FAIL because the baseline revision and test fixture do not exist.

- [ ] **Step 3: Generate and review the baseline migration**

Create one Alembic baseline revision from the model metadata, then review it
as a concrete migration. It must explicitly create all M1 tables, indexes,
foreign keys, unique constraints, JSONB columns, timestamps, token hash, and
revocation fields. The downgrade must remove all objects created by upgrade in
reverse dependency order. Do not call `Base.metadata.create_all()` in runtime
code.

- [ ] **Step 4: Run migration verification against PostgreSQL**

Run:

```bash
docker compose up -d --wait postgres
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest tests/test_migrations.py -q
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run alembic upgrade head
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run alembic downgrade base
cd .. && docker compose down --volumes
```

Expected: upgrade/downgrade/re-upgrade tests pass and CLI commands exit 0.

- [ ] **Step 5: Commit the baseline schema**

```bash
git add backend/alembic/versions backend/tests/test_migrations.py README.md backend/.env.example
git commit -m "feat: add M1 baseline migration"
```

### Task 4: Implement Argon2id Password and User Persistence

**Files:**
- Create: `backend/app/security/__init__.py`
- Create: `backend/app/security/passwords.py`
- Create: `backend/app/persistence/__init__.py`
- Create: `backend/app/persistence/users.py`
- Create: `backend/tests/test_passwords.py`
- Create: `backend/tests/test_user_persistence.py`

**Interfaces:**
- Produces `hash_password(password: str) -> str`.
- Produces `verify_password(password: str, password_hash: str) -> bool`.
- Produces async user operations `get_user_by_username`, `seed_initial_user`, `verify_user_password`, and `change_password`.
- Produces transactional password-change behavior that increments revocation generation.

- [ ] **Step 1: Write failing password/user tests**

```python
def test_password_hash_is_argon2id_and_not_plaintext():
    password_hash = hash_password("correct")
    assert password_hash.startswith("$argon2id$")
    assert password_hash != "correct"
    assert verify_password("correct", password_hash)
    assert not verify_password("wrong", password_hash)
```

Add PostgreSQL tests proving first-user seeding is idempotent, environment
credentials do not overwrite an existing user, current password is required,
and password change increments the revocation generation in one transaction.

- [ ] **Step 2: Run focused tests to verify RED**

Run from `backend/`: `uv run pytest tests/test_passwords.py tests/test_user_persistence.py -q`

Expected: FAIL because hashing and repositories do not exist.

- [ ] **Step 3: Implement Argon2id wrapper and repository operations**

Wrap `argon2.PasswordHasher`, which uses Argon2id by default. Catch
`VerifyMismatchError`, `VerificationError`, and `InvalidHashError` and return
`False` from verification. Keep hashes opaque. Implement `seed_initial_user`
with an insert-if-empty transaction and `change_password` with row locking,
hash replacement, and `revocation_generation + 1`.

- [ ] **Step 4: Run focused and migration-backed tests**

Run:

```bash
cd backend
uv run pytest tests/test_passwords.py tests/test_user_persistence.py -q
uv run pytest tests/test_models.py tests/test_migrations.py -q
```

Expected: all tests pass against PostgreSQL where persistence is required.

- [ ] **Step 5: Commit password and user persistence**

```bash
git add backend/app/security backend/app/persistence backend/tests/test_passwords.py backend/tests/test_user_persistence.py
git commit -m "feat: persist Argon2id operator credentials"
```

### Task 5: Implement Async PostgreSQL SessionStore

**Files:**
- Modify: `backend/app/session_store.py`
- Create: `backend/app/persistence/sessions.py`
- Modify: `backend/app/auth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_postgres_sessions.py`
- Modify: `backend/tests/test_session_store.py`

**Interfaces:**
- Produces `class PostgresSessionStore(SessionStore)` with awaitable `create`, `validate`, and `invalidate`.
- Updates `SessionStore` and `InMemorySessionStore` methods to the same awaitable signatures without changing expiry semantics.
- Produces token hashing helper behavior: cookie token remains signed/opaque; DB stores only `sha256(token)`.
- `create_app` defaults to PostgreSQL-backed auth when a DB session factory is configured, while injected in-memory store remains available for unit tests.

- [ ] **Step 1: Write failing persistence/session tests**

Add async tests covering restart persistence, token-hash-only storage,
non-renewing read, explicit renewal, exact idle/absolute expiry, logout,
missing/tampered tokens, and revocation-generation mismatch:

```python
@pytest.mark.asyncio
async def test_password_revocation_invalidates_existing_postgres_session(db):
    first = await postgres_store.create("operator", now())
    second = await postgres_store.create("operator", now())
    await change_password(db, "operator", "old", "new")
    assert await postgres_store.validate(first, now(), renew_idle=False) is None
    assert await postgres_store.validate(second, now(), renew_idle=False) is None
```

Update M0 store tests to `await` the async protocol while retaining the same
boundary and expiry assertions.

- [ ] **Step 2: Run session tests to verify RED**

Run from `backend/`: `uv run pytest tests/test_session_store.py tests/test_postgres_sessions.py -q`

Expected: FAIL because the protocol is synchronous and the PostgreSQL store
does not exist.

- [ ] **Step 3: Implement async protocol and PostgreSQL store**

Make protocol methods `async def`. Convert the in-memory implementation to
awaitable methods without adding I/O. Implement PostgreSQL operations with an
`AsyncSession`: store `sha256(raw_token)` plus user ID, expiry values,
timestamps, and current revocation generation; validate signature before the
database lookup; reject/delete expired or revoked rows; update idle expiry
only when `renew_idle=True`; invalidate by token hash.

Use transactions for validation updates and invalidation. Ensure no raw token
or password hash is logged or returned. Keep the cookie token format and
cookie attributes unchanged.

- [ ] **Step 4: Run all backend auth/session tests**

Run:

```bash
cd backend
uv run pytest tests/test_session_store.py tests/test_postgres_sessions.py tests/test_postgres_auth.py -q
uv run python -m compileall app
```

Expected: all async store and auth persistence tests pass.

- [ ] **Step 5: Commit the PostgreSQL SessionStore**

```bash
git add backend/app/session_store.py backend/app/persistence/sessions.py backend/app/auth.py backend/app/main.py backend/tests
git commit -m "feat: add PostgreSQL session store"
```

### Task 6: Integrate Persistent Auth and Password Change API

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/auth.py`
- Modify: `backend/app/db/engine.py`
- Create: `backend/tests/test_postgres_auth.py`
- Modify: `backend/tests/conftest.py`
- Modify: `README.md`

**Interfaces:**
- Produces `POST /auth/password` with current/new password validation and generic success response.
- Produces async FastAPI dependencies for `AsyncSession` and persisted user/session repositories.
- Keeps M0 routes and response shapes stable.
- Startup seeding runs explicitly after migrations and only when the user table is empty.

- [ ] **Step 1: Write failing API integration tests**

With PostgreSQL and migrations applied, test:

```python
@pytest.mark.asyncio
async def test_password_change_revokes_every_session(client_factory):
    first = await login(client_factory, "old")
    second = await login(client_factory, "old")
    response = await first.post("/auth/password", json={"current_password": "old", "new_password": "new"})
    assert response.status_code == 200
    assert (await first.get("/auth/me")).status_code == 401
    assert (await second.get("/auth/me")).status_code == 401
    assert (await login(client_factory, "old")).status_code == 401
    assert (await login(client_factory, "new")).status_code == 200
```

Also test wrong current password (`401`), invalid new password (`422`),
first-user seeding, second startup no-overwrite, and persisted session
survival across a newly created application/store instance.

- [ ] **Step 2: Run API tests to verify RED**

Run from `backend/`: `uv run pytest tests/test_postgres_auth.py -q`

Expected: FAIL because persistent dependencies and `/auth/password` are not
wired.

- [ ] **Step 3: Integrate persisted dependencies and route**

Add the async DB session dependency to the app factory. Run explicit seeding
from a startup/lifecycle command used by local/CI setup, not from implicit
schema creation. Make default auth use the PostgreSQL user repository and
`PostgresSessionStore` when configured. Keep unit tests able to inject the
in-memory store.

Implement a Pydantic password-change request with a non-empty new password
policy, verify the current persisted hash, update the hash and revocation
generation transactionally, invalidate the caller session, clear its cookie,
and return `{"status": "ok"}`. Preserve generic auth failures.

- [ ] **Step 4: Run complete backend regression suite**

Run:

```bash
cd backend
uv run pytest -q
uv run python -m compileall app alembic
```

Expected: M0 tests, migration tests, registry-independent tests, and M1
persistence/auth tests all pass.

- [ ] **Step 5: Commit persistent auth integration**

```bash
git add backend/app backend/tests README.md
git commit -m "feat: integrate persistent authentication"
```

### Task 7: Implement Strict Registry Model, Parser, and Generator

**Files:**
- Create: `backend/registry/__init__.py`
- Create: `backend/registry/model.py`
- Create: `backend/registry/parser.py`
- Create: `backend/registry/generate.py`
- Create: `backend/scripts/registry_check.py`
- Create: `backend/tests/fixtures/registry/*.md`
- Create: `backend/tests/test_registry_parser.py`
- Create: `backend/tests/test_registry_generation.py`

**Interfaces:**
- Produces `parse_gmc_markdown(path: Path) -> RegistryDocument`.
- Produces `generate_registry(source: Path, output: Path) -> None`.
- Produces `check_registry(source: Path, output: Path) -> bool`.
- Produces stable normalized models for scalar, repeated scalar, structured single, and structured repeated attributes.
- Produces explicit export status and feed-domain metadata for deprecated/removed and vehicle-only rows.

- [ ] **Step 1: Write parser fixture tests**

Create fixtures covering:

```markdown
| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `title` | REQUIRED* | String | max. 150 chars |
| `additional_image_link` | OPTIONAL | URL, repeatable (up to 10×) | max. 2000 chars |
| `installment` | OPTIONAL | Object: `months` (Integer, req), `amount` (Price, req) | payment |
| `availability` | REQUIRED | Enum: `in_stock`, `out_of_stock` | exact values |
```

Assert parsed kind, ordered sub-fields, enum values, repeated/cardinality,
length limits, and requirement metadata. Add malformed-row, duplicate-field,
unsupported-type, ambiguous-structured-order, deprecated, and vehicle-only
fixtures with exact diagnostic assertions.

- [ ] **Step 2: Run parser tests to verify RED**

Run from `backend/`: `uv run pytest tests/test_registry_parser.py -q`

Expected: FAIL because the normalized model and parser do not exist.

- [ ] **Step 3: Implement strict normalized model and parser**

Use Pydantic models or dataclasses with explicit enums for attribute kind,
requirement status, export status, and feed domain. Parse only the documented
Markdown table shape. Normalize backticks, Unicode multiplication markers,
sub-attribute order, enum alternatives, repeatability/cardinality, and
length/format constraints. Preserve source line numbers for errors.

Reject malformed or ambiguous input instead of silently guessing. Map known
source sections to feed domains; mark vehicle-listing-only rows as
`vehicle_listings`, standard Shopping rows as `primary`, and deprecated/
removed rows as non-exportable.

- [ ] **Step 4: Implement deterministic generator and check mode**

Serialize a versioned JSON document with sorted attribute names, stable list
ordering, stable indentation, and a source fingerprint. `check_registry`
regenerates in memory and compares bytes with the checked-in artifact. The
CLI exits 0 when current and 1 with a useful diff/staleness message when
different.

- [ ] **Step 5: Run fixture and full-source generation tests**

Run:

```bash
cd backend
uv run pytest tests/test_registry_parser.py tests/test_registry_generation.py -q
uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check
```

Expected: fixtures pass, full-source generation succeeds, and check mode
passes after the artifact is generated.

- [ ] **Step 6: Commit parser and generator**

```bash
git add backend/registry backend/scripts/registry_check.py backend/tests/fixtures/registry backend/tests/test_registry_parser.py backend/tests/test_registry_generation.py
git commit -m "feat: generate GMC attribute registry"
```

### Task 8: Add Runtime Registry Loader and CI Drift Check

**Files:**
- Create: `backend/registry/loader.py`
- Create: `backend/tests/test_registry_loader.py`
- Create: `backend/registry/attributes.json`
- Modify: `.github/workflows/ci.yml`
- Modify: `backend/pyproject.toml` if a registry command is added
- Modify: `README.md`

**Interfaces:**
- Produces `load_registry(path: Path | None = None) -> RegistryDocument`.
- Produces schema validation for the generated JSON artifact.
- Produces a clear exception for missing, invalid, stale, or unsupported artifact versions.
- CI runs registry check mode and fails on drift.

- [ ] **Step 1: Write failing loader tests**

Test missing artifact, invalid JSON, unsupported artifact version, valid
representative attributes, and `load_registry()` default path:

```python
def test_loader_rejects_missing_artifact(tmp_path):
    with pytest.raises(RegistryLoadError, match="missing"):
        load_registry(tmp_path / "missing.json")


def test_loader_exposes_representative_attribute(artifact_path):
    registry = load_registry(artifact_path)
    assert registry.attributes["shipping"].kind == AttributeKind.STRUCTURED_REPEATED
    assert registry.attributes["shipping"].sub_fields[0].name == "country"
```

- [ ] **Step 2: Run loader tests to verify RED**

Run from `backend/`: `uv run pytest tests/test_registry_loader.py -q`

Expected: FAIL because the loader, artifact, and validation error do not
exist.

- [ ] **Step 3: Implement loader and generate the checked-in artifact**

Validate JSON shape/version with the same normalized model used by the
generator. Default to `backend/registry/attributes.json` resolved from the
module path, not the process working directory. Raise a dedicated exception
with path and validation details. Generate the artifact from the current
`gmc_def.md` and inspect representative output before committing.

- [ ] **Step 4: Add CI and local documentation**

Add a CI step after backend dependency installation:

```yaml
- name: Check GMC registry artifact
  working-directory: backend
  run: uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check
```

Document the generation/check command in `README.md`. Do not load Markdown at
runtime and do not add a registry database table.

- [ ] **Step 5: Run complete registry verification**

Run:

```bash
cd backend
uv run pytest tests/test_registry_parser.py tests/test_registry_generation.py tests/test_registry_loader.py -q
uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check
```

Expected: all tests and check mode pass.

- [ ] **Step 6: Commit runtime registry and CI check**

```bash
git add backend/registry/attributes.json backend/registry/loader.py backend/tests/test_registry_loader.py .github/workflows/ci.yml backend/pyproject.toml README.md
git commit -m "feat: load checked-in GMC registry"
```

### Task 9: Complete M1 CI and Full Milestone Verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/decisions.md`
- Create: `backend/tests/test_m1_acceptance.py`

**Interfaces:**
- Produces one explicit M1 acceptance test module covering migration, registry, persisted auth, and password-change revocation.
- Produces CI lifecycle steps that start PostgreSQL, run Alembic, run registry check, run backend tests, and clean up volumes.
- Keeps existing frontend tests/typecheck/build green.

- [ ] **Step 1: Write the M1 acceptance test**

Create one test module that asserts the complete externally relevant gate:

```python
@pytest.mark.asyncio
async def test_m1_acceptance(m1_database, app_factory):
    await apply_migrations(m1_database)
    await seed_initial_user(m1_database, "operator", "old")
    first = await login(app_factory, "old")
    second = await login(app_factory, "old")
    response = await first.post(
        "/auth/password",
        json={"current_password": "old", "new_password": "new"},
    )
    assert response.status_code == 200
    assert (await first.get("/auth/me")).status_code == 401
    assert (await second.get("/auth/me")).status_code == 401
    assert (await login(app_factory, "old")).status_code == 401
    assert (await login(app_factory, "new")).status_code == 200
```

Also assert registry check mode and expected table names as part of the
milestone command sequence.

- [ ] **Step 2: Run the acceptance test to verify RED**

Run from repository root with PostgreSQL healthy:

```bash
docker compose up -d --wait postgres
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run pytest tests/test_m1_acceptance.py -q
```

Expected: FAIL until all M1 layers are integrated.

- [ ] **Step 3: Implement CI migration/registry lifecycle**

Update CI to run `docker compose up -d --wait postgres`, apply Alembic against
the test database, run registry check, run the full backend suite, run the
frontend suite/build, and always execute `docker compose down --volumes`.
Do not add another container or production credentials.

- [ ] **Step 4: Run all M1 verification locally**

Run:

```bash
docker compose up -d --wait postgres
(cd backend && uv run pytest -q && uv run python -m compileall app alembic registry && uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check)
(cd frontend && npm test -- --run && npm run typecheck && npm run build)
docker compose config -q
docker compose down --volumes
git diff --check
```

Expected: every command passes; the only allowed existing warning is the
Starlette/httpx TestClient deprecation warning.

- [ ] **Step 5: Record final exact dependencies and commit**

Update `docs/decisions.md` with exact SQLAlchemy, asyncpg, Alembic,
argon2-cffi, and pytest-asyncio versions and any concrete Argon2 parameters.
Then commit:

```bash
git add .github/workflows/ci.yml README.md docs/decisions.md backend/tests/test_m1_acceptance.py
git commit -m "ci: verify M1 persistence and registry"
```

---

## Plan Self-Review

- **Spec coverage:** M1 schema and core entities are covered by Tasks 1-3;
  persistent sessions, first-user seeding, Argon2id, password-change
  invalidation, and async auth are covered by Tasks 4-6; registry generation,
  checked-in artifact, runtime loading, and CI drift checks are covered by
  Tasks 7-8; complete M1 acceptance and CI lifecycle are covered by Task 9.
- **Scope:** Readers, staging behavior, plugins, QC, XML, scheduling, and
  frontend management screens are explicitly excluded.
- **Placeholder scan:** No step uses TODO/TBD or unspecified error handling.
  Newly selected package versions are required to be exact and documented in
  the first dependency task and final decision-log update.
- **Type consistency:** `SessionStore.create`, `validate`, and `invalidate`
  remain the same named operations across the protocol, in-memory store,
  PostgreSQL store, auth dependencies, and tests; M1 changes only their
  awaitability. `RegistryDocument`, `RegistryAttribute`, `load_registry`,
  `generate_registry`, and `check_registry` are introduced before consumers.
