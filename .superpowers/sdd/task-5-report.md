## Task 5: QC Engine — Types and Core

**Status:** DONE

### Commit

`d78f903` — feat(qc): engine types, protocols, and run_engine()

### Test Summary

4/4 tests pass: per-product rule attachment, cross-product rule execution, clean data produces no findings, rule exceptions are caught without crashing the engine.

### Files Created

- `backend/app/qc/__init__.py` — Package exports
- `backend/app/qc/constants.py` — EXEMPT_TAXONOMY_IDS, IMAGE_FORMATS, IMAGE_SIZE_ENFORCEMENT_DATE, IMAGE_FETCH_CAP_BYTES, IMAGE_CONCURRENCY
- `backend/app/qc/engine.py` — QcContext, Finding (with product_id: str = ""), PerProductRule, CrossProductRule, ImageProbe, ExportRun protocols, run_engine()
- `backend/tests/test_qc_engine.py` — 4 unit tests

### Concerns

- The `field` name in the `Finding` dataclass conflicts with `dataclasses.field`; used `dc_field` alias to resolve.
- Tests require `--noconftest` to avoid the database-dependent conftest.py (not a concern for this task, but relevant for CI).
