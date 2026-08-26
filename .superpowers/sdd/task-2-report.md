# Task 2 Report: Template-database fixture rework

## Status: DONE

Commit: `af8e3cf` — `feat: template-database test isolation via pytest-postgresql`

## What changed

`backend/tests/conftest.py` only (+62/−41):

- Replaced imports: dropped `asyncio`, `uuid`, `urlunsplit`, `asyncpg`; added
  `quote`, `pytest_postgresql.factories`. Kept `from fastapi.testclient
  import TestClient` — the brief's import block omitted it, but the untouched
  `client` fixture requires it.
- Added module-level wiring after `_ARTIFACT_PATH`: `_BACKEND_ROOT`,
  `_server_params()`, `_load_alembic_schema()` loader,
  `gmc_postgres_noproc` / `gmc_database` factories, `_asyncpg_url()`.
- Deleted the old asyncpg CREATE/DROP DATABASE `isolated_database_url`
  fixture entirely; new fixture delegates to `gmc_database` and returns the
  asyncpg URL built from the plugin connection's `.info`.

Installed pytest-postgresql 8.1.0 factory signatures were verified via
`inspect.signature`: `postgresql_noproc(host=..., port=..., user=...,
password=..., load=[callable])` and `postgresql(process_fixture_name)` match
the brief's literal code exactly — no adaptation needed.

## Verification

Step 2 (DB-heavy suites, serial):

```
uv run pytest tests/test_config_bundle.py tests/test_staging_step.py -q -n0 --durations=5
14 passed, 2 warnings in 3.81s
slowest: 0.66s setup test_config_bundle (template clone); calls ≤0.18s
```

Template cloning confirmed working — no "database is being accessed by other
users" errors; alembic's engine disposal frees the template as expected.

Step 3 + Step 4 (full suite, serial):

```
time uv run pytest -q -n0
366 passed, 11 warnings in 51.88s   (real 55.8s)
```

Baseline was 366 passed; wall time recorded for decisions.md (Task 4):
**51.88s** pytest-reported / **~56s** real.

## Migration-test adaptations

None required. `test_migrations.py`, `test_m2_migration.py`,
`test_m5_migration.py` all pass unmodified against a pre-migrated clone.

## Self-review

- Contract preserved: fixture still named `isolated_database_url`, yields
  `postgresql+asyncpg://user:pass@host:port/dbname` for a fully-migrated DB;
  all ~56 consuming tests untouched and passing.
- Fail-fast preserved: `_server_params()` runs inside the fixture *before*
  `getfixturevalue`, so missing/malformed `TEST_DATABASE_URL` fails with the
  original messages before plugin machinery spins up.
- No dead imports: `asyncio`, `uuid`, `urlunsplit`, `asyncpg` all removed;
  nothing else in the file referenced them (grep-verified during edit).
- Other fixtures (`artifact_path`, `clock`, `store`, `settings`, `client`)
  byte-identical to the original.

## Notes

- LSP flagged `Import "pytest_postgresql" could not be resolved` and
  `No parameter named "_env_file"` — both false positives (LSP not using the
  uv venv; `_env_file` is a pydantic-settings kwarg). Runtime is clean.
- Untracked scratch files under `.superpowers/sdd/task-1-*` /
  `task-2-brief.md` modifications are controller bookkeeping, not committed
  with this task.
