# Findings-Detail Version Diff — Design

**Date:** 2026-09-18
**Status:** Approved (design), pending implementation plan
**Scope:** Retain QC findings per ingestion run, scope the feed-latest readers to the latest run, and extend the export version diff with a rule-grouped findings delta (added / fixed / persisted). No new dependencies, no DB migration.

## Problem

The version diff can compare **product data** but not **QC findings**: it shows only the counts delta (critical/warning/info) from `ExportRun`. Showing which findings appeared, were fixed, or persisted is impossible today because `persist_findings` does a feed-keyed delete before inserting the current run's findings (`backend/app/qc/persistence.py:36-51`), so `quality_findings` holds only the latest run's set. `ExportRun` stores counts plus `fixed/new/remaining`, but not finding identities.

## Decision

| Topic | Decision |
|-------|----------|
| Findings storage | Retain findings per ingestion run; no feed-keyed delete |
| Delta computation | `fixed/new/remaining` computed against the **previous** run's findings (not the accumulated set) |
| Idempotency | Re-persisting a run deletes that run's rows first, then inserts |
| Retention | Existing `purge_expired_ingestion_runs` deletes findings by `ingestion_run_id`; no change |
| Readers | Scope `routes/quality.py`, `chat/tools.py` (feed case), and `pipeline/steps.py _ai_qc_context` to the feed's latest run |
| Diff shape | Extend the existing `GET …/export-history/{v}/diff` response with a `findings` block, grouped by rule code with capped sample product ids |
| Rollback versions | `a_qc`/`b_qc` false (no ingestion run) → not-QC'd notice |
| Schema | None (only write/read strategy changes) |

## Backend design

### 1. Retain findings per run — `app/qc/persistence.py`

Replace the feed-keyed delete and feed-wide delta with:

```python
prev_run_id = (await session.execute(
    select(func.max(QualityFinding.ingestion_run_id)).where(
        QualityFinding.feed_source_id == feed_source_id,
        QualityFinding.ingestion_run_id < ingestion_run_id,
    )
)).scalar_one_or_none()
old_keys: set[tuple[str, str, str | None]] = set()
if prev_run_id is not None:
    rows = (await session.execute(
        select(QualityFinding.code, QualityFinding.product_id, QualityFinding.field)
        .where(
            QualityFinding.feed_source_id == feed_source_id,
            QualityFinding.ingestion_run_id == prev_run_id,
        )
    )).all()
    old_keys = {(row.code, row.product_id, row.field) for row in rows}

# idempotent replace of this run's rows (does not touch other runs)
await session.execute(
    delete(QualityFinding).where(QualityFinding.ingestion_run_id == ingestion_run_id)
)
```

`new_keys`, `fixed`, `added`, `remaining` keep their current formulas; only the source of `old_keys` changes. Insert and `ExportRun` write are unchanged (`func` import added for `func.max`).

### 2. Scope the latest-run readers

- `routes/quality.py get_quality_findings` (`:54-59`): filter `QualityFinding.ingestion_run_id == export_run.ingestion_run_id`. When `export_run.ingestion_run_id` is `None` → `findings = []`.
- `chat/tools.py _query_qc_findings` (`:101-122`): when `args.feed_source_id` is given, add `.where(QualityFinding.ingestion_run_id == <that feed's max ingestion_run_id>)`. The no-feed global case keeps its current "most recently persisted, limited" behavior.
- `pipeline/steps.py _ai_qc_context` (`:559-565`): scope to `QualityFinding.ingestion_run_id == func.max(ingestion_run_id) for this feed` so `previous_ai_product_ids` remains the previous run's set, preserving today's behavior.

### 3. Findings diff — `app/export/service.py`, `app/schemas/export.py`

`ExportService.diff` already loads both `ExportVersion` rows. Additionally resolve each version's `ExportRun.ingestion_run_id` (via `ExportVersion.export_run_id`), load each run's findings, and compute the delta.

Keying mirrors persistence: `(code, product_id, field)`, with `product_id` already normalized to `"cross_product"` at write time.

Response models added to `schemas/export.py`:

```python
class FindingRuleDiffOut(BaseModel):
    code: str
    severity: str
    added: int
    fixed: int
    persisted: int
    sample_added: list[str]
    sample_fixed: list[str]
    sample_persisted: list[str]


class FindingsDeltaTotals(BaseModel):
    added: int
    fixed: int
    persisted: int


class FindingsDiffOut(BaseModel):
    a_qc: bool
    b_qc: bool
    totals: FindingsDeltaTotals
    rules: list[FindingRuleDiffOut]
```

`DiffOut` gains `findings: FindingsDiffOut`.

Semantics:
- `added` = B−A, `fixed` = A−B, `persisted` = A∩B (on the `(code, product_id, field)` key).
- `a_qc`/`b_qc` = the version's `ExportRun.ingestion_run_id is not None` (rollback → false). A false side yields empty rules and zero totals; the UI shows the not-QC'd notice.
- Group by `code`; `severity` = the highest severity seen for that code across both runs (`critical` > `warning` > `info`).
- Sort rules by severity rank, then `code` ascending.
- `sample_*` = deduplicated, sorted product ids, capped at **20** per bucket. Counts are true totals regardless of the cap. (Bounded payload on large finding sets.)

### 4. Retention and docs

- Retention is unchanged: `purge_expired_ingestion_runs` deletes findings whose `ingestion_run_id` is purged (`staging/purge.py:115-119`). Findings can now outlive an export version pruned by `history_retention_count` (export-version retention) until the ingestion-run purge (default 90 days); documented as an accepted consequence.
- `backend/docs/data-model.md`: findings retention changes from "one set per feed" to "per ingestion run, purged with the run".
- `backend/docs/api.md`: document the `findings` block on the diff endpoint.

## Frontend design

- `frontend/src/api/types.ts`: add `FindingRuleDiffOut`, `FindingsDiffOut`, `FindingsDeltaTotals`, and `DiffOut.findings`.
- `frontend/src/features/export/ExportVersionDiff.tsx`: add a **QC findings** section (after the counts delta, before the product list):
  - If `!findings.a_qc || !findings.b_qc` → the not-QC'd note.
  - Totals as compact badges: `+added`, `−fixed`, `=persisted`.
  - A per-rule list: `RuleLabel` + `SeverityBadge` (reused from `frontend/src/features/monitoring/findings/`), added/fixed/persisted counts, and a collapsed expander showing the sample product ids.
  - No changes needed to hooks/`queryKeys` — the data rides the existing diff query.
- i18n (`export` namespace, en + de): `findingsDiff.title`, `findingsDiff.added`, `findingsDiff.fixed`, `findingsDiff.persisted`, `findingsDiff.notQcd`, `findingsDiff.rule`, `findingsDiff.noChanges`, `findingsDiff.products`.

## Testing

**Backend** (`uv run pytest`):
- `persist_findings` retains prior runs' rows; delta computed vs the previous run only; re-persisting the same run replaces rather than duplicates; a new run does not delete older runs' findings.
- `GET quality-findings` returns only the latest run's findings (an older run's rows are excluded) while counts/prev_counts are unchanged.
- `_ai_qc_context` sees only the latest run's `ai_policy_check` ids.
- Diff `findings`: added/fixed/persisted on a two-version fixture; grouping and severity ordering; sample cap; rollback side → `a_qc`/`b_qc` false and empty rules; total counts unaffected by the cap.
- Update existing suites that assumed feed-wide findings: `test_qc_delta.py`, `test_quality_api.py`, `test_m7_acceptance.py`, `test_chat_tools.py`; `test_purge_ingestion_runs.py` should already pass (delete-by-run).

**Frontend** (`npm run test`):
- `ExportVersionDiff.test.tsx`: renders the findings section with totals and a rule row; not-QC'd when a side is not QC'd; empty state when no findings changes.
- Namespace `monitoring` must be loaded in the test if `RuleLabel`/`SeverityBadge` are reused.

## Risks and non-goals

- **QC delta semantics change** is the main risk; TDD covers retention, previous-run delta, and idempotency, and the full backend suite gates it.
- **Storage growth**: findings are now per run instead of per feed. Bounded by the ingestion-run purge; documented. If it proves heavy, a dedicated findings retention is a future follow-up.
- **Payload size**: capped samples keep the diff response bounded; persisted/new/fixed totals remain exact.
- **Non-goals:** migrating existing single-set findings (none persisted historically beyond the latest), a findings-history UI beyond the version diff, per-finding severity filtering in the diff, and any schema change.

## References

- `backend/app/qc/persistence.py`, `backend/app/routes/quality.py`, `backend/app/chat/tools.py`, `backend/app/pipeline/steps.py` (`_ai_qc_context`), `backend/app/staging/purge.py`, `backend/app/models/quality.py`, `backend/app/models/export.py`.
- `frontend/src/features/export/ExportVersionDiff.tsx`, `frontend/src/api/types.ts`, `frontend/src/features/monitoring/findings/` (`RuleLabel`, `SeverityBadge`, `ruleCatalog`).
- `backend/docs/data-model.md`, `backend/docs/api.md`.
