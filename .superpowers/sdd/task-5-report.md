# Task 5 Report: Migration — `removed_at`, cascade FK, purge index

## Status
COMPLETE

## Commits (branch `m5-staging-delta`)
- `41a2cf1` — `feat: staging removed_at column, history cascade, purge index`
  (`backend/app/models/staging.py`, `backend/alembic/versions/20260826_0001_m5_staging_delta.py`, `backend/tests/test_m5_migration.py`)
- `73f2562` — `test: pin m2 migration downgrade target to 20260824_0001` (required follow-up, see "Deviations")

## Implementation
- **Model** (`app/models/staging.py`, exactly two edits as specified):
  - `StagingProduct.removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)` added after `last_seen_at`.
  - `StagingHistory.staging_product_id` FK changed from `ondelete="RESTRICT"` to `ondelete="CASCADE"`.
- **Migration** (`alembic/versions/20260826_0001_m5_staging_delta.py`): verbatim per brief.
  - upgrade: add nullable timestamptz `removed_at`; create partial index `ix_staging_products_removed_purge ON staging_products (removed_at) WHERE status = 'removed'`; drop + recreate FK `staging_history_staging_product_id_fkey` with `ON DELETE CASCADE`.
  - downgrade: exact reverse (FK back to RESTRICT, drop index, drop column).
- The baseline FK name `staging_history_staging_product_id_fkey` was confirmed live (PostgreSQL default naming), matching `_HISTORY_FK`.

## TDD evidence

### RED (before model/migration changes)
```
tests/test_m5_migration.py::test_upgrade_adds_removed_at_cascade_and_index FAILED
tests/test_m5_migration.py::test_downgrade_reverses_all_three FAILED
tests/test_m5_migration.py::test_removal_deletes_history_via_cascade FAILED
E   AssertionError: assert 'removed_at' in {'config_hash', 'content_hash', ...}
E   asyncpg.exceptions.ForeignKeyViolationError: update or delete on table
    "staging_products" violates foreign key constraint
    "staging_history_staging_product_id_fkey" on table "staging_history"
```
Failures are for exactly the reasons the brief predicts (missing column; non-cascading FK blocks delete).

### GREEN
```
tests/test_m5_migration.py          3 passed
tests/test_migrations.py            1 passed
tests/test_models.py                8 passed
======================== 12 passed in 3.95s ========================
```

### Full suite (before commit)
```
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q
343 passed, 93 warnings in 85.15s
```
340 baseline + 3 new tests. First full run had 1 failure (`tests/test_m2_migration.py`) — see Deviations; fixed and re-run to full green.

### Downgrade verification
- `test_downgrade_reverses_all_three` downgrades to `20260825_0001` against real Postgres, asserts no `removed_at`, no purge index, FK restored with `ondelete=RESTRICT`, then re-upgrades to head. PASSED.
- `tests/test_m2_migration.py` now also cycles up → down to `20260824_0001` → up through the new revision. PASSED.

## Files changed
- Modified: `backend/app/models/staging.py`
- Created: `backend/alembic/versions/20260826_0001_m5_staging_delta.py`
- Created: `backend/tests/test_m5_migration.py`
- Modified: `backend/tests/test_m2_migration.py` (one-line fix, separate commit)

## Deviations from brief (all forced by environment, intent preserved)
1. **Test inserts extended**: raw-SQL INSERTs needed NOT NULL JSONB columns that ORM defaults would normally supply: `clients.settings`/`contact_details`, `feed_sources.field_mapping`/`configuration`, `ingestion_runs.processed_count/failed_count/statistics`. Brief anticipated this ("extend the column list accordingly").
2. **Alembic commands run via `asyncio.to_thread`** in the async test: `alembic/env.py` calls `asyncio.run()` internally, which raises `RuntimeError` when invoked from the running pytest-asyncio loop. Offloading to a thread keeps the brief's structure.
3. **FK `ondelete` read helper**: SQLAlchemy 2.0.43's inspector nests `ondelete` under `fk["options"]` rather than top-level; added tiny `_fk_ondelete()` helper checking both locations so assertions work across versions.
4. **`test_m2_migration.py` downgrade target pinned** from relative `-1` to `"20260824_0001"`: adding a new head changed what `-1` resolves to, breaking that pre-existing test's assumptions. Pinned explicitly to preserve its original semantics.

## Self-review
- Model diff contains only the two specified line changes — verified against committed diff.
- Migration matches brief verbatim (style header, single-quoted identifiers).
- Upgrade AND downgrade both verified against real PostgreSQL (isolated DB per test via `isolated_database_url` fixture).
- Full suite green before committing; commits contain only intended files.
- No concerns remaining.
