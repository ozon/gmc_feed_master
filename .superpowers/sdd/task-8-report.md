## Task 8: QC Persistence — Feed-Keyed Replace + ExportRun

**Status:** DONE

### What was done
Created `backend/app/qc/persistence.py` with `persist_findings()` that:
- Deletes existing `QualityFinding` rows by `feed_source_id` (feed-keyed replace)
- Inserts all findings with `product_id` (using `"cross_product"` fallback for cross-product findings)
- Counts findings by severity (critical/warning/info)
- Creates an `ExportRun` row with status="completed" and severity counts
- All within a single transaction

### Commits
- `0b822e0` feat(qc): persistence layer with feed-keyed replace semantics

### Test summary
No dedicated unit tests — this task's tests are embedded in Task 10 integration tests (as specified in the brief).

### Concerns
None. Models were already updated for M7 (feed_source_id, product_id, critical_finding_count, field columns).

### Report file
`.superpowers/sdd/task-8-report.md`
