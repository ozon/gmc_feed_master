# Findings & Quality Surfaces — Design

Date: 2026-09-16
Status: Approved in brainstorming (operator)
Baseline: main at 233ba90 (M14 hardening cycle 2 close-out)

## Goal
Deepen the quality-findings experience on the frontend and unify the quality surfaces, without new
dependencies, new endpoints, or schema changes. Scope selected by the operator:

- **Deeper findings UX:** group + collapse by rule or GMC attribute; rule descriptions + remediation
  hints; product drill-down; table ergonomics.
- **Unify surfaces:** one shared severity + rule catalog; cross-links from the feed dashboard;
  a quality badge on dashboard feed cards.

## Decisions (operator)
- Approach **A — shared findings module + client-side explorer**. Grouping, counting, sorting and
  pagination are client-side over the existing `quality-findings` response (which already returns
  every finding). Server-driven grouping/pagination is deliberately deferred (see Ceilings).
- Rule descriptions/remediation are **frontend i18n** (the 13 rule codes are a fixed set).
- Product drill-down reuses the existing `useProductDetail` hook and `ProductDrawer`; no new route.
- One tiny backend addition: per-feed quality counts in `/dashboard/summary`. No migration.
- Supersedes the Z2 out-of-scope line "no dashboard badge" (`2026-09-12-qc-page-design.md` §Out of
  scope) — a feed-card quality badge is now in scope for this cycle.

## Module architecture
New domain module `frontend/src/features/monitoring/findings/`; `monitoring` remains the consuming
feature.

- `severity.ts` — `SEVERITIES` tuple (`critical | warning | info`), severity order, Mantine color,
  chart color, i18n label key. Sole severity source of truth; removes the duplicated
  `SEVERITY_COLOR` map in `FindingsTable` and the inline severity arrays in `MonitoringFindingsPage`,
  `FeedDashboardPage` and `QualitySummaryCards`.
- `ruleCatalog.ts` — static map of the 13 backend `rule_id`s
  (`baseline_required`, `brand_required`, `gtin_mpn`, `enum_values`, `conditional_required`,
  `date_format`, `length_limits`, `cardinality`, `currency_consistency`, `image_requirements`,
  `variant_consistency`, `volume_drop`, `ai_policy_check`) to i18n keys
  `rules.<code>.{title,description,remediation}`. Unknown code → raw code + generic description
  fallback (never throws).
- `groupFindings.ts` — pure helpers: `countBySeverity`, `groupByRule`, `groupByAttribute`
  (findings with no `field`, i.e. cross-product rules, bucket into a `__feed__` group),
  `filterFindings` (free-text search over message/product/field), and group-count helpers.
- `SeverityBadge.tsx` — shared severity badge (color + localized label).
- `RuleLabel.tsx` — friendly rule title with description/remediation in a tooltip.
- `FindingsSummary.tsx` — severity cards + delta badges + "of N products"; replaces
  `QualitySummaryCards` and lives in the module.
- `FindingsExplorer.tsx` — the explorer:
  - toolbar: `Group by: Rule | Attribute | Flat` segmented control, free-text search, severity
    MultiSelect, rule filter (when not grouped by rule);
  - grouped mode: Mantine `Accordion` (multiple open) — group header shows friendly rule
    title/attribute name, total count and per-severity chips; body is a compact findings table with
    a "show all (N more)" toggle above 20 rows;
  - flat mode: sortable, paginated table built with TanStack Table (already a dependency; follow the
    `ProductsTable` patterns), page sizes 25/50/100.
- `QualityTrendChart.tsx` / `RuleDistributionChart.tsx` — moved into the module, consuming the shared
  severity colors; the distribution chart labels rules by friendly title.

## Data flow
`useQualityFindings(feedSourceId, active)` (unchanged) returns all findings plus counts/delta; the
explorer derives groups, group counts, filtered rows and pagination client-side (memoized). Product
drill-down reuses `useProductDetail` + `ProductDrawer`; a row click sets `selectedProductId`. No new
hooks, no server-state duplication (TanStack Query remains the only server-state store).

## Unification & cross-links
- **Feed dashboard** quality card gains a total and a "View findings" `Link` to
  `/clients/:clientId/feeds/:feedSourceId/monitoring/findings` (`clientId` is already in the route).
- **Dashboard feed card** shows a severity indicator: if `critical > 0` a red badge with the critical
  count, otherwise if `warning > 0` a yellow badge with the warning count, otherwise no badge.
  Clicking it stops propagation and navigates to the feed's findings page instead of the feed
  dashboard.
- **Dry-run** keeps its bare findings table, but its `SeverityBadge` and rule titles come from the
  shared module.

## Backend change
`GET /dashboard/summary` per-feed dict gains `quality: {critical, warning, info}` read from the
latest `ExportRun` already fetched via `_latest_runs(session, ExportRun)`. No migration, no new
endpoint, no extra query. `FeedSourceSummary` type and `backend/docs/api.md` updated.

## Error handling
Pending/error/empty states reuse `LoadingState`/`ErrorState`/`EmptyState`. Findings with no `field`
appear in a "feed-level" group with `—` for product. Unknown rule codes render the raw code with a
generic description. `ProductDrawer` keeps its existing loading/error handling.

## Testing
- Unit: `groupFindings` (by rule, by attribute, feed-level bucketing, counts, search/filter);
  `ruleCatalog` guard test asserting every backend `rule_id` is present; `severity` mapping.
- Component: explorer grouping + collapse, per-group counts, flat sort/pagination, search, unknown
  code fallback, product drill-down opens the drawer (mocked detail); existing
  `MonitoringFindingsPage.test.tsx` extended (it already stubs both endpoints).
- Feed card badge renders from the summary and links to findings.
- Backend: extend the dashboard test to assert per-feed `quality` counts.

## i18n & docs
`frontend/public/locales/{en,de}/monitoring.json` gain `rules.*` (13 codes) and
`findings.groupBy/search/showMore/feedLevel/openProduct`; the `dashboard` locale gains the badge
label. Docs in the same commit: `frontend/docs/architecture.md` (findings module + surfaces),
`backend/docs/api.md` (summary response), `docs/decisions.md` (dated entry incl. the Z2 supersession).

## Ceilings
- Grouping/pagination are client-side over the full findings list. `ponytail:` ceiling — if a feed
  ever produces findings in the thousands, move grouping/pagination server-side (new grouped-count
  and paginated endpoints) behind the same explorer; the module boundary (`groupFindings` +
  `FindingsExplorer`) is the upgrade seam.

## Out of scope
Server-side grouped/paginated findings endpoints; finding-level history; export of findings (CSV/JSON);
richer cross-surface filter state sharing; changes to QC rules or severities.
