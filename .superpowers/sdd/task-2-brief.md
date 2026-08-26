### Task 2: Template-database fixture rework

**Files:**
- Modify: `backend/tests/conftest.py` (replace `isolated_database_url` internals; add plugin wiring)
- Possibly modify: `backend/tests/test_migrations.py`, `backend/tests/test_m2_migration.py`, `backend/tests/test_m5_migration.py` ONLY if their assumptions break (see Step 4)

**Interfaces:**
- Consumes: `TEST_DATABASE_URL` env var; Alembic programmatic API; `pytest_postgresql.factories`.
- Produces: unchanged `isolated_database_url(request)` fixture yielding `postgresql+asyncpg://user:pass@host:port/dbname` for a fully-migrated per-test database. All other test files untouched.

- [ ] **Step 1: Rework conftest.py**

Replace the imports block and the whole `isolated_database_url` fixture with the following. Keep every other existing fixture (`artifact_path`, `clock`, `store`, `settings`, `client`) byte-identical.

New/changed imports (top of file):

```python
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest
from alembic import command
from alembic.config import Config
from pytest_postgresql import factories
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.config import Settings
from app.main import create_app
from app.session_store import InMemorySessionStore
```

Remove now-unused imports (`asyncio`, `uuid`, `urlunsplit`, `asyncpg`) unless something else in the file still uses them — nothing else does.

Module-level wiring (place after the `_ARTIFACT_PATH` definition):

```python
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _server_params() -> dict:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL via asyncpg")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg:// dialect")
    parts = urlsplit(value)
    return {
        "host": parts.hostname or "localhost",
        "port": parts.port or 5432,
        "user": parts.username or "postgres",
        "password": parts.password or "",
    }


def _load_alembic_schema(**kwargs):
    """Populate the plugin's template database with the full migration chain."""
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    password = quote(kwargs.get("password") or "", safe="")
    url = (
        f"postgresql+asyncpg://{kwargs['user']}:{password}"
        f"@{kwargs['host']}:{kwargs['port']}/{kwargs['dbname']}"
    )
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    # alembic's env.py disposes its own engine before returning, so no
    # connections hold the template open when the plugin clones it.


_server = _server_params()

gmc_postgres_noproc = factories.postgresql_noproc(
    host=_server["host"],
    port=_server["port"],
    user=_server["user"],
    password=_server["password"],
    load=[_load_alembic_schema],
)

gmc_database = factories.postgresql("gmc_postgres_noproc")


def _asyncpg_url(info) -> str:
    password = quote(info.password or "", safe="")
    return (
        f"postgresql+asyncpg://{info.user}:{password}"
        f"@{info.host}:{info.port}/{info.dbname}"
    )


@pytest.fixture
def isolated_database_url(request):
    _server_params()
    connection = request.getfixturevalue("gmc_database")
    return _asyncpg_url(connection.info)
```

Delete the entire old `isolated_database_url` fixture (the asyncpg CREATE/DROP DATABASE version).

Notes for the implementer:
- `_server_params()` is called twice by design: once at import to parametrize the factory, once inside the fixture to preserve the fail-fast contract when the env var is missing (the check runs *before* `getfixturevalue` spins up the plugin machinery).
- The plugin's `postgresql` fixture yields a psycopg `Connection`; `.info` exposes host/port/dbname/user/password.
- If the installed pytest-postgresql version names the loader parameter or kwarg shape differently than `load=[callable]` / `**kwargs` with `dbname`, consult its docs (`uv run python -c "import pytest_postgresql.factories as f; help(f.postgresql_noproc)"`) and adapt the call — the behavioral contract above is binding, not the literal signature.

- [ ] **Step 2: Verify serially against the DB-heavy suites**

```bash
cd backend && export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
uv run pytest tests/test_config_bundle.py tests/test_staging_step.py -q -n0
```
Expected: PASS. First test pays the one-time template migration; subsequent setups should be visibly faster (look at `--durations=5` if curious).

- [ ] **Step 3: Full suite, serial**

```bash
uv run pytest -q -n0 2>&1 | tail -1
```
Expected: 366 passed. If any of the three migration-driving test files fail because they assumed an empty database, adapt ONLY those tests minimally (e.g. begin with `command.downgrade(config, "base")` before their upgrade flow) and justify each change in the report. Anything beyond those three files failing = stop and report BLOCKED.

- [ ] **Step 4: Measure and record**

Record the `-n0` wall time (from pytest's summary line) in a working note (final numbers go into decisions.md in Task 4).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/conftest.py backend/tests/test_migrations.py backend/tests/test_m2_migration.py backend/tests/test_m5_migration.py
git commit -m "feat: template-database test isolation via pytest-postgresql"
```
(Include migration-test files only if actually modified.)

---

