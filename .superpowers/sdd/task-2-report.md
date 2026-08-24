# M1 Task 2 Report

## Files changed

- `backend/app/db/base.py`: SQLAlchemy 2.x `DeclarativeBase`.
- `backend/app/models/__init__.py`: imports and exports all 15 mapped models.
- `backend/app/models/user.py`: users model with username uniqueness and revocation generation.
- `backend/app/models/session.py`: hashed-token session model with expiry, revocation, and lookup indexes.
- `backend/app/models/client.py`: clients model with JSONB settings.
- `backend/app/models/feed_source.py`: feed sources with restrictive client foreign key and JSONB configuration.
- `backend/app/models/plugin.py`: plugins, plugin configs, and plugin data with JSONB fields and foreign keys.
- `backend/app/models/pipeline.py`: module pipelines and instances with pipeline/plugin foreign keys and JSONB fields.
- `backend/app/models/ingestion.py`: ingestion runs with feed-source foreign key and JSONB statistics.
- `backend/app/models/staging.py`: staging products/history, restrictive foreign keys, and product uniqueness.
- `backend/app/models/quality.py`: quality findings with JSONB details.
- `backend/app/models/export.py`: export runs/versions with JSONB options and version uniqueness.
- `backend/alembic.ini`: PostgreSQL async database URL placeholder and Alembic logging configuration.
- `backend/alembic/env.py`: async Alembic environment importing all models and using `connection.run_sync`.
- `backend/alembic/script.py.mako`: migration revision template.
- `backend/alembic/versions/.gitkeep`: empty versions directory marker; no baseline revision created.
- `backend/tests/test_models.py`: metadata table, key constraint/foreign-key, uniqueness, session, and JSONB contract tests.

No persistence repositories, authentication persistence, registry, or baseline migration revision was added.

## Commands and output

### TDD RED

```text
$ cd backend && uv run pytest tests/test_models.py -q
ERROR collecting tests/test_models.py
ModuleNotFoundError: No module named 'app.db.base'
```

### Model tests and compile checks

```text
$ cd backend && uv run pytest tests/test_models.py -q
....                                                                     [100%]
4 passed, 1 warning in 0.25s

$ cd backend && uv run python -m compileall app alembic
Listing 'app'...
Listing 'app/db'...
Listing 'app/models'...
Listing 'alembic'...
Compiling 'alembic/env.py'...
Listing 'alembic/versions'...
```

## Concerns

- The focused test run retains the pre-existing `StarletteDeprecationWarning` about the installed httpx/Starlette combination; it does not fail the tests.
- The requested baseline Alembic revision is intentionally deferred to Task 3.

## Review fixes

- Added the binding §4 representation fields: feed-source field mappings; pipeline/feed-source ownership and ordered module positions; staging content/config hashes, status, and last-seen timestamp; plugin manifest; declared plugin scopes and client/feed-source owners; quality finding ingestion-run linkage; ingestion error details and processed/failed counts; export product/severity counts and stored export-version linkage.
- Added indexes for the required foreign-key lookup columns and strengthened metadata tests for all reviewed contracts, JSONB fields, scope owners, and indexes.
- Kept exactly 15 tables and did not add a baseline migration, repositories, authentication persistence, or registry.

## Review-fix verification

```text
$ cd backend && uv run pytest tests/test_models.py -q && uv run python -m compileall app alembic
......                                                                   [100%]
6 passed, 1 warning in 0.31s
Listing 'app'...
Listing 'app/db'...
Listing 'app/models'...
Listing 'alembic'...
Listing 'alembic/versions'...

$ cd backend && uv run pytest -q
..............................................                           [100%]
46 passed, 1 warning in 1.23s
```

The warning is the pre-existing `StarletteDeprecationWarning` for the installed httpx/Starlette combination.

## Remaining review-fix verification

- Reworked `PluginConfig` and `PluginData` scoped persistence to use three explicit PostgreSQL partial unique indexes per table (global, client, and feed-source), including the scoped owner columns in each index. This permits the same plugin/key at different scopes while rejecting duplicates for the same scope/owner, including NULL global owners.
- Added `ck_plugin_configs_scope_owner` and `ck_plugin_data_scope_owner` check constraints enforcing global-with-no-owner, client-with-client-only, and feed-source-with-feed-source-only records. `PluginData` now has the conceptual `key` needed by scoped uniqueness.
- Added nullable `FeedSource.active_pipeline_id` as the direct active-pipeline reference. Kept `ModulePipeline.feed_source_id` as the required ownership FK and `ModuleInstance.position` plus its per-pipeline uniqueness. Added explicit relationships with foreign-key selection on both sides so the circular FK metadata configures cleanly.
- Tightened JSON metadata tests to require PostgreSQL `JSONB` exactly and added metadata assertions for partial indexes, scope-owner checks, and active-pipeline FK.
- Preserved exactly 15 tables; no migration, repository, authentication, or registry implementation was added.

Commands and output:

```text
$ cd backend && uv run pytest tests/test_models.py -q
........                                                                 [100%]
8 passed, 1 warning in 0.33s

$ cd backend && uv run pytest -q
................................................                         [100%]
48 passed, 1 warning in 1.12s

$ cd backend && uv run python -m compileall app alembic
Listing 'app'...
Listing 'app/db'...
Listing 'app/models'...
Listing 'alembic'...
Listing 'alembic/versions'...

$ metadata inspection
tables: 15 ['clients', 'export_runs', 'export_versions', 'feed_sources', 'ingestion_runs', 'module_instances', 'module_pipelines', 'plugin_configs', 'plugin_data', 'plugins', 'quality_findings', 'sessions', 'staging_history', 'staging_products', 'users']
CREATE UNIQUE INDEX uq_plugin_configs_client_plugin_key ON plugin_configs (plugin_id, client_id, key) WHERE scope = 'client' AND client_id IS NOT NULL AND feed_source_id IS NULL
CREATE UNIQUE INDEX uq_plugin_configs_feed_source_plugin_key ON plugin_configs (plugin_id, feed_source_id, key) WHERE scope = 'feed_source' AND client_id IS NULL AND feed_source_id IS NOT NULL
CREATE UNIQUE INDEX uq_plugin_configs_global_plugin_key ON plugin_configs (plugin_id, key) WHERE scope = 'global' AND client_id IS NULL AND feed_source_id IS NULL
CREATE UNIQUE INDEX uq_plugin_data_client_plugin_key ON plugin_data (plugin_id, client_id, key) WHERE scope = 'client' AND client_id IS NOT NULL AND feed_source_id IS NULL
CREATE UNIQUE INDEX uq_plugin_data_feed_source_plugin_key ON plugin_data (plugin_id, feed_source_id, key) WHERE scope = 'feed_source' AND client_id IS NULL AND feed_source_id IS NOT NULL
CREATE UNIQUE INDEX uq_plugin_data_global_plugin_key ON plugin_data (plugin_id, key) WHERE scope = 'global' AND client_id IS NULL AND feed_source_id IS NULL
active_pipeline_fk: ['module_pipelines.id']
```
