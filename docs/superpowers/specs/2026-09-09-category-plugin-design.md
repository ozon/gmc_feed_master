# Category Plugin (M12) — Design

**Date:** 2026-09-09
**Cycle branch:** `m12-category` (off main `354064f`; merge to main at cycle end)
**Workflow:** subagent-driven development (per-task review), final whole-branch review before merge
**Source:** TODO 8.1 (M11+ scope planning) — operator picked the Category plugin, the last of the four core plugins (spec §5, §5.9, UI §9.7). Closes TODO 5.1 (core plugin UIs) once shipped.

## §0 Context and operator decisions

The engine spec defines Category fully: mapping rules + manual assignments → `google_product_category` (gmc-feed-engine-spec.md §5.9 line 199), the provenance sidecar, and the v1 UI (§9.7 line 265: 4-bucket dashboard, drag-and-drop rule editor with taxonomy autocomplete, per-rule match counts, matched-products modal, dirty-state guard; Manual Categorization tab working; AI/Uncategorized tabs and Generate/Copy/Bulk-delete as disabled-with-tooltip placeholders). Nothing in this milestone changes the engine spec; the design below implements it.

Operator decisions from the 2026-09-09 brainstorming session (binding):

1. **M11+ scope = Category plugin.** One milestone covering backend + full v1 UI.
2. **Taxonomy model:** one ID-keyed index with per-language paths. The shipped file is the operator-provided CSV `taxonomy-with-ids.en-US.csv` (committed at `cbb1867`, 5595 rows, format `id,segment1,…,segment7` — 8 columns, path = segments joined with `" > "`), moved into the plugin directory as part of this milestone (`git mv` from the repo root). v1 supports exactly two languages: en-US (shipped, committed) and de-DE (fetched server-side from Google's official URL, converted to the same CSV format, and merged into the same index).
3. **Fetch mechanism:** backend route fetches Google's official `.txt` file for de-DE, converts it to the house CSV format, and persists it (no manual file upload in v1).
4. **Architecture:** platform-native (Approach A) — rules as scoped PluginConfig, manual assignments as PluginData, custom `register_routes` only for what the generic surface cannot serve.
5. **Stats basis:** stored sidecars ("as of last run"), like QC findings; live rule-preview evaluation is a follow-up cycle (Labelizer precedent: live matching shipped in a later cycle, ADR-0008 era).

## §1 Plugin manifest and scopes

Directory `plugins/core/category/`:

- `__init__.py` (empty), `plugin.json`, `plugin.py`, `taxonomy-with-ids.en-US.csv` (committed; `git mv` of the operator's `cbb1867` file from the repo root), `.gitignore` (ignores `taxonomy-with-ids.de-DE.csv`), `frontend/component.tsx`.

`plugin.json`:

- `id: "category"`, `name: "Category"`, `version: "1.0.0"`, `extension_point: "pipeline_module"`, `entry_point: "plugin:CategoryPlugin"`
- `config_scope: ["global", "client"]`, `data_scope: ["global", "client"]` — spec §5.3 line 130 verbatim (Category declares only global+client; no feed_source). In practice only client-scope data rows are ever written (manual assignments); no global data rows exist because fetched taxonomy is file-based (§2), so nothing bloats the config bundle.
- `config_merge: {"rules": {"strategy": "union_by_key", "key": "id"}}` — global rules define the walk order; client tiers override same-id rules in place and append unseen rules at the end. First-match-wins requires this stable ordering; identical to Labelizer `slotRules` (ADR-0005).
- `config_schema`: object with `rules: array` of spec-exact rule objects: `{id: string, source_field: string (default "product_type"), operator: enum [eq, ne, contains, regex, in], source_value: string | array-of-string, taxonomy_id: string, is_excluded: boolean (default false)}`. `source_value` is a plain string for eq/ne/contains/regex and a list for `in`.
- `data_schema`: object with `assignments: object` mapping `product_id → taxonomy_id` (both strings).
- `frontend`: `{menu_item: "Category", icon: "sitemap", component: "component.tsx"}`. The current `PluginIconMap.ts` has only letter icons + `IconCircle` fallback; this milestone adds one entry (`sitemap` → `IconSitemap` from `@tabler/icons-react`, verified against the installed export map). TODO 3.5 (full registry) stays out of scope.

Single-file constraint: the loader execs exactly one module (`backend/app/plugins/loader.py:40-47`), so the taxonomy parser, index, rule engine, and routes all live in `plugin.py` (sized ≈600-700 lines; custom_labels is the precedent at 364 lines with a smaller surface).

## §2 Taxonomy subsystem

- **Canonical storage format:** the house CSV — one category per line, `id,segment1,…,segment7` (8 columns; trailing empties pad); path renders as segments joined with `" > "`. Parsed with the stdlib `csv` module (RFC-4180 quoting), so segments containing commas/quotes are safe — relevant because converted de-DE data may contain them.
- **Fetch-time input format:** Google's official `.txt` (lines `ID - Path > Segments`; `#` comments and blanks skipped). Only the fetch route reads this format; it converts to the house CSV before persisting, so storage has exactly one format.
- **Index:** `{taxonomy_id → {language → path}}`, one merged structure (operator decision 2). Built from every `taxonomy-with-ids.<lang>.csv` present in the plugin directory (en-US always; de-DE once fetched). IDs are language-independent, so paths merge by ID.
- **Lifecycle:** the index is UI/route-facing only — `process()` writes IDs and never consults it (rules store `taxonomy_id` directly). Built lazily on the plugin instance, cached, invalidated by file mtime. Restart needs no re-fetch: files persist in the plugin dir.
- **Fetch route:** `POST /plugins/category/taxonomy/fetch` with `{language: "de-DE"}`. v1 whitelist: de-DE only (en-US is the committed shipped file, updated via git, not overwritten by the server). Flow: GET `https://www.google.com/basepages/producttype/taxonomy-with-ids.de-DE.txt` using the backend's existing HTTP client → parse `.txt` → sanity-validate (unique IDs, plausible entry count) → convert to house CSV → atomic write (temp file + `os.replace` in the plugin dir) → index rebuild. Failure modes: upstream fetch/parse failure → 502 with detail; unwritable plugin dir → 500 with clear detail. No DB rows, no config-hash impact (fetching a language never changes feed output, which is written as IDs).

## §3 Processing semantics

- `validate_config(config)`: strict validation on the generic config write path (custom_labels precedent). Checks: `rules` is an array; each rule is an object with non-empty string `id` (unique), `source_field` non-empty string, `operator` in the enum, `source_value` a non-empty string (or non-empty list of non-empty strings for `in`), `taxonomy_id` non-empty string present in the taxonomy index (IDs are language-independent; index always has en-US), `is_excluded` boolean if present; regex operator must compile. Empty config passes.
- `prepare_run(config, data, ctx)`: compile the ordered rule list into run state: `eq`/`ne` compare via `strip().casefold()`; `contains`/`regex`/`in` are case-sensitive; `in` tests membership in the value list. Manual assignments compile to a `product_id → taxonomy_id` dict.
- `process(product, config, data, ctx, state)`: evaluates against the mapped canonical product via `resolve_path` (Labelizer's helper semantics, duplicated locally since plugins cannot import each other):
  1. Manual assignment for `product["id"]` wins first → `google_product_category = taxonomy_id`, provenance `manual`.
  2. Else walk rules top-to-bottom, first match wins → `google_product_category = taxonomy_id`, provenance `auto`; if the matched rule has `is_excluded: true` → `google_product_category = ""` and provenance `excluded`.
  3. No assignment and no match → the product is untouched (no provenance key → uncategorized bucket).
- **Sidecars** attached to the returned dict: `_category_provenance` (string: `manual | auto | excluded`; absent → uncategorized) per spec §5.9, plus `_category_rule_id` (the matched rule's id, for auto/excluded rows). `_category_rule_id` is an extension the spec does not name but its UI mandates (per-rule match counts, matched-products modal); it is spec-consistent: `_`-prefixed keys are stripped from the content hash by `strip_derived` (`backend/app/staging/hashing.py:8-17`) and the XML renderer writes registry attributes only (`backend/app/export/renderer.py:72-78`), so neither sidecar is hashed or exported. Flagged in docs.
- `process` returns a new dict (copy-on-write) and never mutates `original_product` (runtime contract).
- **Reprocessing** is automatic: rule edits change resolved config, assignment edits change resolved data, and both are in the config bundle hash (data-model.md "Config Hash"), so any change reprocesses affected feed sources on the next run (spec §5.9: "Rule changes trigger reprocessing via the config_hash").
- **Run-time taxonomy drift:** if Google prunes an ID between save and run, `validate_config` has already accepted the rule and `process` writes the ID as-is (save-time validation is the guard; `prepare_run` does not re-consult the index, so a taxonomy fetch mid-history can never alter pipeline output).

## §4 Contributed routes (`register_routes`, mounted under `/plugins/category/…`)

Pattern: custom_labels `register_routes` (plugin.py:314-360) — inline Pydantic models, `get_current_user` dependency, direct model imports, reserved paths avoided.

- `GET /plugins/category/stats?feed_source_id` → `{total, buckets: {manual, auto, excluded, uncategorized}, rules: {rule_id: count}}`. SQL over active, non-excluded staging rows: `GROUP BY processed_data->>'_category_provenance'` and `GROUP BY processed_data->>'_category_rule_id'` (JSONB column, backend/app/models/staging.py:22). Counts are "as of last run"; rule ids absent from the current config are still returned (the UI maps only existing rules). Guards: `ensure_feed_source_access` + 404 for unknown/foreign feed sources (spec §5.9 cross-tenant rule).
- `GET /plugins/category/matches?feed_source_id&rule_id&limit&offset` → paged `{product_id, title}` for products whose `_category_rule_id` equals `rule_id`. Same guards.
- `GET /plugins/category/product?feed_source_id&product_id` → single product's category state: `{product_id, title, provenance, rule_id, google_product_category, assignment}` — powers the Manual Categorization tab. Same guards.
- `GET /plugins/category/taxonomy/languages` → `["en-US"]` plus `"de-DE"` iff the fetched file exists.
- `GET /plugins/category/taxonomy/search?language&q&limit&offset` → autocomplete: case-insensitive contains-match on path in the selected language, starts-with matches ranked first; returns `{id, path}` items.
- `GET /plugins/category/taxonomy/validate?taxonomy_id` → `{valid, path?}`.
- `POST /plugins/category/taxonomy/fetch` → §2.

Taxonomy routes are client-agnostic (global data) and require only an authenticated user; feed-source-scoped routes are cross-tenant guarded.

## §5 Frontend — `frontend/component.tsx`

One custom component (Labelizer architecture precedent; ADR-0006/0007 two-surface model: pipeline editor adds the module instance, the plugin page is this component). Nav routes client-scoped (`/clients/:clientId/plugins/category`) automatically via the existing scope-based nav logic.

- **Tabs** (spec §9.7 line 265): Dashboard, Rules, Manual Categorization; plus AI and Uncategorized tabs rendered disabled with tooltips (placeholders), and Generate/Copy/Bulk-delete controls disabled with tooltips.
- **Language selector** (en-US / de-DE): shared taxonomy autocomplete language; if de-DE is not yet fetched the selector offers a fetch action calling the fetch route, then invalidates the languages query.
- **Dashboard tab:** feed-source selector (client context; Labelizer feed-source selection precedent), 4-bucket progress (manual/auto/excluded/uncategorized + total) from the stats route; as-of-last-run labeling.
- **Rules tab:** ordered rule list with dnd-kit vertical drag (pipeline-page precedent: stable ids, `applyDragEnd`-style pure helper), rule cards with: source_field select (registry attributes), operator select, source_value input (multi-value input for `in`), taxonomy autocomplete bound to the selected language, `is_excluded` switch (disables the taxonomy picker), per-rule match-count badge (from stats), matched-products modal (paged list). Dirty-state guard with snapshot + Reset + Save via the generic scoped config endpoints; global/client tier switch with inherited badges (ADR-0005 tier UX); 422 per-field errors via `notifyApiError`.
- **Manual Categorization tab (working in v1):** product lookup by id (existing products hooks), category state from the product route (provenance badge, current value), assign/unassign via taxonomy autocomplete, saved through the generic scoped data endpoint (read-modify-write of the `assignments` map — Labelizer bulk-ID precedent).
- House conventions throughout: all strings via `t()`, en+de identical trees, Loading/Empty/ErrorState on every data view, TanStack Query for all server state, `notifications.clean()` in tests, `beforeAll(loadNamespaces)` for plugin namespaces.

## §6 Testing and gates

- **Contract:** `uv run pytest backend/tests/test_plugin_contract.py` must pass with the new plugin (mandatory for plugin host/plugin changes).
- **Backend unit/integration:** taxonomy CSV parser + index (fixture .csv: trailing empty segments, deepest 7-level rows, merged languages, RFC-4180-quoted segments) and the fetch-time `.txt`→CSV converter (comments, blanks, `" - "` split); rule engine semantics (manual-before-rules, first-match-wins, casefold eq/ne, case-sensitive contains/regex, `in`, excluded sets `""`, untouched uncategorized); `validate_config` (accept/reject matrix, unknown taxonomy_id); sidecar exclusion (content_hash unchanged by sidecars; rendered XML contains no `_category_*` keys); routes (stats buckets against seeded staging rows, matches paging, product state, taxonomy search ranking, languages, fetch with mocked upstream HTTP incl. failure → 502 and unwritable-dir → 500, cross-tenant 404); config_hash reprocess on rule and assignment changes (delta classify).
- **Frontend:** tab rendering, disabled placeholders, icon map entry (`sitemap` resolves, unknown names still fall back), language selector + fetch action, rule editor add/reorder/remove, autocomplete select, per-rule badge, matches modal, dirty guard (snapshot/reset/save), 422 mapping, manual categorization assign/unassign.
- **Gates:** `uv run pytest -n auto` (needs `TEST_DATABASE_URL`), `uv run ruff check .` (zero new in touched files), `uv run mypy .` (≤ 42 baseline, no new), `npm run test && npm run typecheck && npm run build`.
- **Docs updated in the same commits:** `backend/docs/plugins.md` (Category scope-table row + route list), `backend/docs/api.md` (new plugin routes), `backend/docs/data-model.md` (sidecar note: `_category_provenance`/`_category_rule_id` in `processed_data`), `docs/decisions.md` (operator decisions 2-5, the `_category_rule_id` extension, file-based taxonomy storage rationale), `backend/docs/architecture.md` if the core-plugin inventory list needs the entry. TODO bookkeeping at cycle end: 5.1 closes, 8.1 marked answered (Category picked).

## §7 Out of scope (follow-up candidates)

- Live rule-preview evaluation against staged products (Labelizer `POST /preview` analog) — stats are stored-sidecar "as of last run" in v1.
- Uncategorized/AI tabs beyond disabled placeholders; Generate/Copy/Bulk-delete actions.
- More languages beyond en-US + de-DE; file-upload refresh path.
- Per-feed-source rule overrides (spec scope decision: client-scope only for MVP).
- Supplemental feeds (separate roadmap item, 8.1 residue).
