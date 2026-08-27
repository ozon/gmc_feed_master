# Task 4: Update Models — Report

## Status: DONE

## Commit
`9d15c8b` feat(models): update for M7 QC engine schema

## Changes
- `backend/app/models/export.py`: Renamed `error_finding_count` → `critical_finding_count`, added `ingestion_run_id` FK column + index
- `backend/app/models/quality.py`: Replaced `staging_product_id` FK with `feed_source_id` (CASCADE), added `product_id` (String), `field` (String nullable), updated indexes
- `backend/app/models/feed_source.py`: Added `volume_drop_threshold_pct` (Integer, NOT NULL, default=20)
- `backend/app/models/image_dimension.py`: New model for `image_dimensions` table (url unique, width/height nullable, fetch_error, fetched_at)
- `backend/app/models/__init__.py`: Added `ImageDimension` to imports and `__all__`
- `backend/tests/test_models.py`: Updated table set, updated `critical_finding_count` assertion, added `feed_source_id`/`product_id` assertions and `staging_product_id` negation check

## Test Summary
8/8 tests passed (test_models.py)

## Concerns
None — models match the migration schema exactly.
