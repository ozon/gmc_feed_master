# Task 3: Migration — Schema Changes

**Status:** DONE

## Commits

- `9a3c383` — feat(migration): M7 schema changes for QC engine

## Test Summary

2 tests passed: `test_upgrade_adds_qc_columns` and `test_downgrade_reverses_qc_changes` — verifies all M7 schema changes apply and revert cleanly.

## What Was Created

- `backend/alembic/versions/20260827_0002_m7_quality_check.py` — Alembic migration with upgrade/downgrade
- `backend/tests/test_m7_migration.py` — Migration tests using isolated PostgreSQL database

## Schema Changes Applied

1. `export_runs.error_finding_count` renamed → `critical_finding_count`
2. `export_runs.ingestion_run_id` added (nullable FK → `ingestion_runs`)
3. `image_dimensions` table created (id, url, width, height, fetch_error, fetched_at)
4. `feed_sources.volume_drop_threshold_pct` added (server_default="20")
5. `quality_findings`: added `feed_source_id`, `product_id`, `field`; dropped `staging_product_id` + FK + index

## Concerns

None.
