# Task 7: Image Probe — Pillow + Cache

## Status: DONE

## Commits

- `05b217d` feat(qc): image probe with Pillow and DB cache

## Test Summary

6 tests pass: cache hit, cache hit (error), fetch success, HTTP error, content too large, corrupt image.

## Files Created

- `backend/app/qc/image_probe.py` — `ImageProbeImpl` class
- `backend/tests/test_image_probe.py` — unit tests with `FakeTransport` and mocked sessions

## Notes

- `session.begin()` in `_cache_dimensions`/`_cache_error` is a sync method returning an async context manager; the task brief's mock setup (`AsyncMock` for `begin`) was incorrect — fixed to `MagicMock` returning an async context manager mock.
