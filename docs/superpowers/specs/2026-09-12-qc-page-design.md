# Z2: QC Page — Findings Visualization & Quality Improvement — Design

Date: 2026-09-12
Status: Approved in brainstorming (operator)
Baseline: main at 24157dc (Z1 spec committed, not yet implemented)
Roadmap: `2026-09-12-ai-restarbeiten-design.md` — this is cycle Z2.

## Decisions (operator)
- Live in the **existing MonitoringFindingsPage** (in-place upgrade, no new route).
- Delta depth: **fixed/new/remaining counters** computed at persist time on the ExportRun (no finding history, no storage growth).
- Charts: **@mantine/charts** (+ recharts peer dep) — operator-approved new dependency.
- No composite quality score (YAGNI); no arbitrary run comparison (always latest vs previous; trend covers history); no dashboard badge.

## Backend

### 1. Migration
`export_runs` gains `fixed_finding_count`, `new_finding_count`, `remaining_finding_count` (Integer, NOT NULL, default 0, server_default "0"). No new tables.

### 2. persist_findings computes the delta
In `backend/app/qc/persistence.py`, before the feed-keyed delete: SELECT the existing findings' keys `(code, product_id, field)` for the feed source; build the new run's key set from the incoming findings; then
- fixed = |old ∖ new|, new = |new ∖ old|, remaining = |old ∩ new|
- store the three counters on the ExportRun row created in the same transaction.
First run ever: old set is empty → new = |N|, fixed = 0, remaining = 0 (raw semantics; UI decides display via `has_previous`).
Delta key is `(code, product_id, field)` — a message-only change counts as remaining (documented behavior).

### 3. New endpoint: quality history
`GET /feed-sources/{feed_source_id}/quality-history?limit=30` (limit 1–100, default 30)
Rows from `ExportRun` (desc by id), same router dependencies/scoping as the existing quality route:
`{id, created_at, product_count, critical_finding_count, warning_finding_count, info_finding_count, fixed_finding_count, new_finding_count, remaining_finding_count}` — exact column names verified at implementation; ExportRun rows survive ingestion-run purge (detached), so the trend is durable.

### 4. Existing quality-findings response extended
`GET /feed-sources/{id}/quality-findings` additionally returns:
- `product_count` (from latest ExportRun)
- `delta: {fixed, new, remaining}` (latest ExportRun counters)
- `has_previous: bool` (a second ExportRun exists)
- `prev_counts: {critical, warning, info}` (second-latest ExportRun) for "12 → 7" displays.

## Frontend

### Dependencies
`@mantine/charts@9.5.2` + `recharts` (required peer). Chart styles imported at root after core Mantine styles. MonitoringFindingsPage is lazy-loaded → charts land in that chunk only.

### MonitoringFindingsPage restructure (top → bottom)
1. **Summary cards**: critical / warning / info counts with delta badges — "↓ N fixed" (green), "↑ N new" (red) — derived from `delta` + `prev_counts`; badge section renders only when `has_previous`. Context line "of N products" from `product_count`.
2. **Trend**: `LineChart` (3 series: critical red, warning yellow, info blue), x-axis = run timestamp, data from new `useQualityHistory` hook (`queryKeys.feedSource(id).qualityHistory`).
3. **Rule distribution**: horizontal `BarChart` — count per `code`, sorted desc, all rule codes (~12). Filtering stays Select-based: existing severity MultiSelect + new code Select (data = distinct codes from findings) drive the table. No chart click events.
4. **FindingsTable**: unchanged below.

i18n keys en + de for all new labels.

## Testing
- Backend: delta computation (fixed/new/remaining; first run; message-change-stays-remaining), quality-history endpoint (limit, ordering, scoping), extended quality-findings response.
- Frontend: summary cards + delta badges render (has_previous true/false), code Select filters the table, chart data passed (mocked fetch); existing MonitoringFindingsPage tests updated.

## Docs (same commit)
`backend/docs/api.md` (2 endpoints), `backend/docs/data-model.md` (3 new export_runs columns), `docs/decisions.md` (Z2 entry + @mantine/charts dependency), `frontend/docs/architecture.md` (new dep, page structure).

## Out of scope
Composite score; finding-level history; arbitrary run-pair comparison; dashboard quality badge; AI-QC rules (Z3).
