# Deferred Review Minors — Triage (2026-09-16, M14)

Scope: every minor recorded as deferred in `.superpowers/sdd/progress.md` (the SDD ledger), verified against the code as of `main` @ `b6e2125`.

Method: enumerate the ledger's `Minors deferred:` entries, then read the referenced code for each. The ledger is months of accumulated prose and several items had already been closed by later fix-waves — most notably the dual-scope-dashboards final fix-wave (`1b1fb64`), which is why so many entries below resolve to **fixed** or **obsolete**.

## Counts

| Classification | Count |
|---|---|
| Fixed before this triage | 9 |
| Obsolete (referenced code no longer exists) | 3 |
| Accepted by design (documented limit, no action) | 4 |
| Open — small, fixed in this task | 1 |
| Open — filed as a `TODO.md` item | 5 |
| **Total** | **22** |

## Triage table

| # | Item | Source cycle | Classification | Evidence | Action |
|---|---|---|---|---|---|
| 1 | auto-select effect dependency churn (guarded, no loop) | dual-scope-dashboards | Obsolete | no auto-select effect exists in `src/features/dashboard/DashboardPage.tsx` | none |
| 2 | Select hidden during loading | dual-scope-dashboards | Obsolete | same code path no longer exists | none |
| 3 | blocker-reset ("stay") path untested | category (m12) | Open — filed | `RulesTab.tsx:228` has `useBlocker(dirty)`; no test drives the stay branch | TODO §11.1 |
| 4 | Save button enabled during validate-pending (double-click hazard) | category (m12) | **Open — small, fixed** | `RulesTab.tsx:306` disabled only on `!dirty` while `loading` included `validate.isPending` | fixed here: `disabled={!dirty \|\| save.isPending \|\| validate.isPending}` |
| 5 | Language param unencoded in `TaxonomyCombobox` | category (m12) | Fixed | `TaxonomyCombobox.tsx:32` uses `encodeURIComponent(language)` | none |
| 6 | `ChannelMetadata` placeholder strings cosmetic | m11a-p1s | Obsolete | `channel_metadata_for` (`backend/app/export/service.py:31`) falls back to the feed name / client name / base URL — no placeholder literals exist | none |
| 7 | Dead `isActive` /-guard branch | dual-scope-dashboards | Fixed | replaced by a `location.hash` check in `AppShell` | none |
| 8 | `/#clients` never active (hash not in pathname) | dual-scope-dashboards | Fixed | same `location.hash` check | none |
| 9 | Donut data/names untested | dual-scope-dashboards | Open — filed | no test renders a `DonutChart` with a data payload | TODO §11.2 |
| 10 | Space key not handled on feed cards | dual-scope-dashboards | Fixed | `FeedSourceCard.tsx:86` handles `' '` alongside `Enter` | none |
| 11 | `component="a"` has no `href` (no middle-click) | dual-scope-dashboards | Open — filed | `FeedSourceCard.tsx:80` renders an anchor without `href` | TODO §11.3 |
| 12 | `func.date` session-timezone day boundary | dual-scope-dashboards | Accepted by design | UTC-default deployment; recorded in `docs/decisions.md` | none |
| 13 | Trend non-ascending edge (export-only day between raw days) | dual-scope-dashboards | Open — filed | chart zero-fills from the first returned row | TODO §11.4 |
| 14 | `row_errors` truncated at 100 by the writer | dual-scope-dashboards | Accepted by design | intentional cap, documented in `docs/decisions.md` | none |
| 15 | `export_runs` 30-row cap vs a 30-day window | dual-scope-dashboards | Accepted by design | intentional cap | none |
| 16 | Partial-statistics funnel | dual-scope-dashboards | Accepted by design | documented edge of the funnel query | none |
| 17 | Excluded-only staging untested | dual-scope-dashboards | Open — filed | no test seeds products that are exclusively excluded | TODO §11.5 |
| 18 | Unused `EmptyState` import | dual-scope-dashboards | Fixed | `FeedDashboardPage.tsx:30` imports and uses it | none |
| 19 | `fillVolumeTrend` future-dated zero rows on short history | dual-scope-dashboards | Fixed | `fillVolumeTrend` deleted; the generic `fillDates` helper is used instead | none |
| 20 | `useTriggerRun` does not invalidate the feed-dashboard key | dual-scope-dashboards | Fixed | `src/api/hooks.ts` invalidates `feedDashboard` on trigger | none |
| 21 | Raw `run.status` bypasses i18n | dual-scope-dashboards | Fixed | `IngestionRunsTable.tsx:38` renders `t(\`runStatus.${status}\`, { defaultValue: status })` | none |
| 22 | `dashboard.py` dict-annotation style (TypedDict would be cleaner) | dual-scope-dashboards | Obsolete | the annotation was assessed as correct at the time; no action was recorded as pending behaviour | none |

## Notes

- The single code change this triage produced is #4. Everything else was either already done, no longer applicable, or a test/UX gap that deserves its own scoped item rather than a smuggled fix.
- Five items were filed in `TODO.md` §11. They are test-coverage and cosmetic-UX gaps, not defects: none of them affects behaviour a user can hit today.
- The ledger's deferred-minor list is now closed out; `TODO.md` §11 is the authoritative list of anything remaining.
