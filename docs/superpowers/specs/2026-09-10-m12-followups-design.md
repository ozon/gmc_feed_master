# M12 Follow-ups Micro-cycle — Design

**Date:** 2026-09-10
**Cycle branch:** `m12-followups` (off main `dc785b5`)
**Workflow:** subagent-driven development (per-task review), final whole-branch review before merge
**Source:** Category plugin (M12) final whole-branch review triage (`m12-category` cycle ledger) + TODO.md working notes

## §0 Context and operator decisions

The M12 category cycle merged at `dc785b5`. Its final review triaged 8 deferred minors; two TODO working-note items join them. This micro-cycle closes the quality/hygiene set. Nothing here changes the engine spec.

Operator decisions (2026-09-10 brainstorming, binding):

1. **`POST /plugins/category/validate` returns ALL errors**, not just the first: validation collects every rule's errors into the 422 `{"errors": [...]}` list; the Rules tab therefore shows all problems in one save attempt.
2. **MatchesModal load-more appends** the next page to the accumulated list (replaces the current replace-paging with no way back).
3. **ProductsPage.test.tsx de-flake = deterministic waits first, no fake timers**: assert via `findBy*` polling with explicit generous timeouts instead of fire-and-sleep; prove stability with 10 consecutive full-suite runs under parallel load before accepting. Fake-timer control of the `useDebouncedValue` clock only if deterministic waits cannot stabilize it (disclosed deviation, not expected).

## §1 Backend test hardening (pure test additions)

- `TaxonomyIndex` staleness: same-file-edit case — write a different en-US CSV to the same path (mtime/size change, no `invalidate()`), assert the index rebuilds on next access (backend/tests/test_category_taxonomy.py).
- `validate_config` error branches currently untested: non-dict rule, non-bool `is_excluded`, `in`-list with non-string/empty entries, empty-string `source_field` (backend/tests/test_category_rules.py).
- Fetch route 500 path: `_taxonomy_directory` pointing at a non-writable location (a file path used as directory, or a read-only dir — use a path under a file) → 502/500 as implemented, assert the detail (backend/tests/test_category_routes.py).
- 503 paths for `stats`/`matches`/`product`: the app_factory pattern always wires a DB; these routes' `db_session is None` guards are reached only via an app created WITHOUT a session factory. Add one focused test mounting the plugin router on a `create_app(settings)` without `db_session_factory` and assert 503 for each of the three routes (the most production-relevant deferred item per the final review).

## §2 Validate endpoint: collect all errors

`validate_config` currently raises `ValueError` on the first bad rule. Change: keep raising `ValueError` (the platform contract — pipeline instance validation + contract checker rely on it), and add `collect_config_errors(config) -> list[str]` that reuses the same per-rule checks and returns every error (`rules[i]: …` prefixes preserved). `POST /validate` switches to `collect_config_errors` (empty list → `{"status": "ok"}`; else 422 with the full list). `validate_config` becomes a thin wrapper: `errors = collect_config_errors(config); if errors: raise ValueError("; ".join(errors))` — single source of truth, first-error message shape unchanged for the contract suite. `CategoryPlugin.validate_config` still calls `validate_config`.

Frontend: `useValidateCategoryRules` already surfaces the 422 `errors` array via `notifyApiError` — no frontend change required beyond the existing error-summary path; one test asserts a multi-error draft yields a 422 with 2+ entries end-to-end.

## §3 RulesTab robustness + TaxonomyCombobox tidy

- Save button: `loading={save.isPending || validate.isPending}` — a fast double-click can no longer fire two validate→save chains (test: click Save twice quickly, assert one PUT).
- Dirty-guard blocker.reset (stay) path test: navigate away with a dirty draft → ConfirmModal → Cancel → stays on page (draft intact).
- `TaxonomyCombobox`: `encodeURIComponent(language)` in the search URL (values are controlled, but encode anyway); remove the unused `TaxonomyEntry` import from `frontend/src/features/category/hooks.ts` (or use it in a return type if trivially natural — otherwise delete).

## §4 MatchesModal: append paging

`loadMore` currently replaces items with the next offset page. Change: accumulate — keep fetched pages in component state keyed by rule; "Load more" shows when `accumulated < query.data.total`; rule change or modal close resets. Test: two pages of stubbed matches → Load more → both pages' products visible.

## §5 DashboardTab polish

- Auto-select effect: depend on the client's `feed_sources` identity (derive inside the effect from the summary query data) instead of the re-created `feedSources` array; no loop (guarded by `feedSourceId === undefined`).
- Feed-source Select renders during stats loading (loading state applies only to the stats area, not the whole tab).

## §6 ProductsPage.test.tsx de-flake

Replace fire-and-sleep/implicit timing with `findBy*` + explicit timeouts; assert stable conditions (rendered row count, pagination total) rather than intermediate states. Acceptance: 10 consecutive `npm test -- --run` passes with the full suite under parallel load (a backend suite may run concurrently for at least 2 of the 10, mirroring the observed failure conditions). If any flake persists, record it and STOP for an operator decision on fake timers (per decision 3).

## §7 German findings pluralization

`frontend/public/locales/de/export.json` findings tooltips: `{{count}} Warnungen` etc. → `_one`/`_other` suffix pairs (en already pluralized where needed; mirror the en tree). Update tests asserting the old single-key strings (ExportPage.test.tsx '0 warning'→'0 warnings' precedent already exists).

## §8 Testing and gates

- Backend: focused category suites + `uv run pytest -n auto` (995 baseline, expect 995+new); ruff 506 zero-new; mypy 42/17 zero-new.
- Frontend: focused feature tests + full suite (407 baseline, expect +new), typecheck, build; §6 stability runs.
- Docs: `backend/docs/api.md` — validate route doc line changes if the errors semantics are described there (multi-error list); decisions.md entry recording operator decisions 1-3.
- No locale key additions beyond §7's plural re-shaping (en+de trees stay identical).

## §9 Out of scope

- Assignments read-modify-write race (needs an optimistic-locking or refetch-before-write design — separate item).
- Mypy baseline cleanup (10.1, 42 errors — its own cluster-cycle).
- Labelizer leftovers 9.2–9.6, icon registry 3.5, test hygiene 6.1/6.2.
- M13 supplemental feeds (roadmap candidate, needs its own brainstorming session).
