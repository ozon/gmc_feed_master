# Dual-Scope Navigation & Feed Dashboards with Mantine Charts — Design

Date: 2026-09-12
Status: Approved (approach B + review delta: shared dashboard layer)

## Context

The current interface is a flat global dashboard: the sidebar shows feed tools
(`Setup`, `Products`, `Pipeline Editor`, `Monitoring`, `Export`) as disabled
placeholders with a "Select a feed source first" hint until a feed-scoped URL
is active. `/` already carries global KPI cards and a client accordion
launchpad, and feed-scoped routes (`/clients/:clientId/feeds/:feedSourceId/*`)
already exist. This design transitions the app into a deterministic
**Dual-Scope Model**:

1. **Global Fleet Scope (`/`)** — portfolio overview, fleet charts, client/feed
   launchpad.
2. **Feed Scope (`/clients/:clientId/feeds/:feedSourceId/*`)** — a dedicated
   per-feed dashboard at the subtree index, with active sidebar tooling.

Scope is URL-derived only (route params), never component state. Charts use
the already-installed `@mantine/charts`.

## Decisions (from brainstorming)

- **Global sidebar**: full spec items — `Fleet Overview`, `Clients`,
  `System Logs`, `Global Rules` — all real links. `System Logs` (`/logs`) and
  `Global Rules` (`/rules`) are **placeholder pages** (empty-state "coming
  soon") in this iteration.
- **Sidebar scoping**: feed tools are **hidden entirely** in global scope (no
  disabled placeholders). The current disabled-placeholder branch in
  `AppShell` is deleted.
- **Feed dashboard route**: index route of the feed subtree
  (`/clients/:clientId/feeds/:feedSourceId`), not an explicit `/dashboard`
  path.
- **Backend**: one new aggregate endpoint per scope —
  `GET /feed-sources/{id}/dashboard` for the feed dashboard, and
  `runs_by_day` (14-day fleet trend) **extended onto the existing**
  `GET /dashboard/summary`. No schema changes, no new dependencies.
- **Fleet donut**: one slice per feed source, top 8 feeds + "Other" bucket.

## Architecture

### 1. Routing (`frontend/src/app/router.tsx`)

Additive changes to the existing route tree:

- New index route `clients/:clientId/feeds/:feedSourceId` →
  `FeedDashboardPage` (lazy-loaded, same pattern as other pages).
- New global routes `/logs` → `SystemLogsPage`, `/rules` → `GlobalRulesPage`
  (placeholders, lazy).
- All existing feed sub-routes (`setup`, `products`, `pipeline`,
  `monitoring/*`, `export`, `plugins/:pluginId`) remain unchanged — they are
  already path-scoped siblings; the index route is one new entry.

Deep-link persistence: the feed switcher in the header preserves the active
area when switching feeds. The existing regex fallback in `FeedBreadcrumb`
(`AppShell.tsx:166`) defaults to `'setup'`; change the default to `''` (feed
base) so switching feeds from the dashboard lands on the next feed's
dashboard instead of `/setup`.

### 2. Sidebar & header (`frontend/src/app/AppShell.tsx`)

**Feed scope** (feedBase non-null): `Dashboard` (→ feedBase, new item),
`Setup`, plugin nav items, `Products`, `Pipeline`, `Monitoring`, `Export`.
All enabled. `Dashboard` active state uses exact pathname match against
feedBase (a `startsWith` match would shadow every sub-item); the rest keep
`startsWith`.

**Global scope** (feedBase null): `Fleet Overview` (→ `/`), `Clients`
(→ `/#clients` anchor on the dashboard), `System Logs` (→ `/logs`),
`Global Rules` (→ `/rules`), plus the existing admin-gated `Admin` item.
The disabled-placeholder branch (`selectFeedSourceHint` NavLinks) is deleted.

**Header**: keep the existing `FeedBreadcrumb` client > feed switcher. Add an
"All Clients" reset item at the top of the client menu navigating to `/`. In
global scope the breadcrumb remains hidden (existing behavior — returns null
without `clientId`).

### 3. Backend aggregates

#### 3a. `GET /dashboard/summary` — add `runs_by_day`

`backend/app/routes/dashboard.py` gains one grouped query over
`ingestion_runs` for the user's allowed feeds, last 14 days:

```json
"runs_by_day": [
  { "date": "2026-09-01", "success": 12, "error": 1 },
  ...
]
```

- `GROUP BY date(started_at), status` where status in
  (`success`, `error`); other statuses (running/pending/skipped) are excluded
  from the chart.
- Day-bucketed array shape is shared with `volume_trend` (see convention
  below), so one frontend gap-filling helper serves both charts.
- Access filtering identical to the existing summary logic (`user.client_ids`).

#### 3b. `GET /feed-sources/{id}/dashboard` — new endpoint

`backend/app/routes/clients.py` (or a sibling route module) returns a single
aggregate for `FeedDashboardPage`:

```json
{
  "kpi": {
    "raw_items": 1234,
    "valid_items": 1100,
    "excluded_items": 57,
    "last_duration_s": 42.5,
    "readiness_rate": 0.94
  },
  "volume_trend": [
    { "date": "2026-08-14", "raw": 1234, "exportable": 1100 },
    ...
  ],
  "stage_funnel": [
    { "stage": "ingest", "passed": 1234, "dropped": 12 },
    { "stage": "mapping", "passed": 1234, "dropped": 4 },
    { "stage": "staging", "passed": 1230, "dropped": 4 },
    { "stage": "run_plugins", "passed": 1215, "dropped": 15 },
    { "stage": "quality_check", "passed": 1215, "dropped": 0 },
    { "stage": "export", "passed": 1100, "dropped": 0 }
  ],
  "quality": { "critical": 3, "warning": 12, "info": 40, "readiness_rate": 0.94 },
  "recent_runs": [
    { "id": 99, "status": "success", "started_at": "...", "duration_s": 42.5, "failed_count": 0 },
    ...
  ]
}
```

Data sources (all existing, no schema changes):

- `kpi.raw_items` — latest ingestion run's `processed_count` (ingest step);
  `last_duration_s` — `completed_at - started_at` of latest completed run;
  `valid_items` / `excluded_items` — staging counts (same filter as the
  dashboard summary's `item_counts` query, plus excluded count);
  `readiness_rate` — `1 - critical_finding_count / product_count` from the
  latest `export_runs` row (guard divide-by-zero; 1.0 when product_count is
  0).
- `volume_trend` — last 30 days from `export_runs` joined with the matching
  ingestion runs: `raw` = ingestion `processed_count`, `exportable` =
  `export_runs.product_count`, bucketed per day.
- `stage_funnel` — parsed from the latest ingestion run's `statistics` JSONB
  (`ingest`, `mapping`, `staging`, `run_plugins`, `quality_check`, `export`
  step statistics; `passed` from `processed_count`, `dropped` derived per step
  from the step statistics keys — e.g. staging `failed`, plugins `dropped`).
  Missing steps are omitted rather than zero-filled.
- `quality` — from the latest `export_runs` row (critical/warning/info
  counts) plus the same readiness rate.
- `recent_runs` — last 10 ingestion runs: id, status, started_at, duration,
  failed_count.

404 when feed not found; access-filtered per user like the summary route.
Empty data (no runs yet) returns zeroed KPIs, empty arrays, readiness 1.0 —
the frontend renders empty states.

#### Shared data shape convention

Both new aggregates use day-bucketed arrays:
`{ date: string; [seriesKey: string]: number }[]`. One frontend helper
(`formatChartDate` + zero-fill for missing days) serves both charts.

### 4. Frontend

#### Shared dashboard layer (first task, before pages)

`frontend/src/components/dashboard/`:

- **`StatCard.tsx`** — the existing private `StatCard` from
  `DashboardPage.tsx`, promoted to a shared component. Props: `label`,
  `value`, optional `variant: 'neutral' | 'warning' | 'critical'` (feed KPIs
  like excluded items and readiness rate get status colors; fleet counts stay
  neutral). `DashboardPage` is refactored to import it in the same PR — the
  diff stays honest that this is a promotion, not a parallel implementation.
- **`ChartCard.tsx`** — `Paper withBorder p="md"` + title + optional
  subtitle, with a structural empty-state branch:
  `data.length === 0 ? <EmptyState/> : children`. All five charts render
  inside it; empty-state handling becomes a structural guarantee instead of
  per-component discipline.
- **`dashboardColors.ts`** — semantic series names (`success`, `error`,
  `warning`, `raw`, `exportable`) mapped once to Mantine theme tokens
  (`var(--mantine-color-*)`), so fleet and feed charts can't drift on colors
  and both color schemes work from one file.

Not extracted (deliberately): `IngestionRunsTable` stays as-is with a
`compact` prop (or trimmed variant) for the recent-runs table — a fully
generic table abstraction for two call sites is premature. The two dashboard
pages stay separate — their KPI counts, chart types, and headers diverge
enough that a shared shell would need more branching than the duplication
costs.

#### Global dashboard (`features/dashboard/DashboardPage.tsx`)

- Keep the 4 KPI `StatCard`s (now shared) and client accordion launchpad.
- Add **Catalog Volume `DonutChart`**: per-feed `item_count`, top 8 feeds +
  "Other" bucket, 180px, `withLabels`, `withTooltip`, placed with the KPI
  row/overview section.
- Add **Pipeline Health `AreaChart`**: 14-day `runs_by_day`, stacked,
  success/error series, curve natural, height 220px, legend.
- `FeedSourceCard` body becomes clickable → navigates to
  `/clients/:clientId/feeds/:feedId` (feed dashboard). Settings/delete icons
  stay; add `id="clients"` anchor target for the sidebar `Clients` link.

#### Feed dashboard (`features/feedDashboard/FeedDashboardPage.tsx`)

1. **Context header** — breadcrumb `Clients / {clientName} / {feedName}`
   (from `useDashboardSummary` + `useFeedSource`), badges: format
   (`TSV`), status, actions: `Run Pipeline Now` (existing `useTriggerRun` +
   `withLoadingNotification`), `Edit Pipeline` (→ `/pipeline`),
   `Copy Export URL` (reuse `CopyField`; export URL from `useFeedSource`).
2. **KPI cards** — 4 shared `StatCard`s: Raw Items, Valid Items, Excluded
   Items, Readiness Rate (percentage, `critical` variant when < threshold),
   plus Processing Duration.
3. **Charts** —
   - Volume & pass-through `AreaChart` (30-day `volume_trend`, `raw`
     neutral-gray, `exportable` teal, 240px, in `ChartCard`).
   - Stage funnel horizontal stacked `BarChart` (`stage_funnel`, passed /
     dropped series, 200px, in `ChartCard`).
   - Quality `DonutChart` (critical/warning/info, center label with readiness
     percentage, in `ChartCard`).
4. **Recent runs** — last 10 runs via `compact` mode of
   `IngestionRunsTable` (status badge, duration, failed count; rows link to
   the monitoring runs page).

Single query: `useFeedDashboard(id)` hook → the one new endpoint. Empty
states via `ChartCard`/`EmptyState`; loading/error via existing
`LoadingState`/`ErrorState`.

#### Placeholder pages

`features/systemLogs/SystemLogsPage.tsx`,
`features/globalRules/GlobalRulesPage.tsx` — `EmptyState` with "coming soon"
copy (i18n), no logic.

#### i18n

All new copy goes through i18next (`dashboard`, `feedDashboard`, `common`
namespaces) following existing key conventions.

### 5. Testing & documentation

- **Backend pytest**: both endpoints — auth required, client access
  filtering, empty-data shapes (zeroed KPIs, empty arrays), statistics
  parsing for the stage funnel, 404 on unknown feed.
- **Frontend vitest**: `FeedDashboardPage` (mocked hook: render, empty
  state, navigation actions), global dashboard charts (mocked summary with
  `runs_by_day`), `AppShell` scope-swap (global items in global scope, feed
  items + Dashboard in feed scope, no disabled placeholders), `StatCard` /
  `ChartCard` unit tests, placeholder pages render.
- **Docs** (same commit): `backend/docs/api.md` — the two endpoint changes;
  `frontend/docs/architecture.md` — new routes and the shared dashboard
  layer; `docs/decisions/` untouched (no new dependency, no schema change).
  Docs contradicting `gmc-feed-engine-spec.md` are bugs — fix the doc.

## Chart specifications

| Location | Component | Data | Config |
| :--- | :--- | :--- | :--- |
| Global Fleet | `DonutChart` | per-feed `item_count`, top 8 + Other | 180px, `withLabels`, `withTooltip` |
| Global Fleet | `AreaChart` | `runs_by_day` (14d) | stacked, success/error, curve natural, h 220, legend |
| Feed | `AreaChart` | `volume_trend` (30d) | raw (neutral) / exportable (teal), h 240 |
| Feed | `BarChart` | `stage_funnel` | horizontal, stacked passed/dropped, h 200 |
| Feed | `DonutChart` | `quality` counts | center label = readiness % |

All charts: colors from `dashboardColors.ts` theme tokens, empty state via
`ChartCard`, wrapped in `Paper withBorder p="md"`.

## Scope boundaries

- No schema changes, no migrations, no new dependencies (backend or
  frontend).
- No changes to pipeline step order or extension points.
- System Logs / Global Rules are placeholders only — real implementations
  are future work.
- The per-feed run lock, atomic publish, and all backend boundaries are
  untouched; `Run Pipeline Now` uses the existing trigger endpoint.
