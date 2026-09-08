# Labelizer Priority Indicators & Synchronized Product Preview — Design

Date: 2026-09-08
Status: Approved (brainstorming session 2026-09-08)
Scope: Labelizer **data page** (feed-level surface) — builds on the slot-selected view shipped 2026-09-07 (merged as `6dcf853`).

## Problem

Two gaps on the Labelizer Plugin Page:

1. The priority display is a verbose `#N Priority` Badge after the rule name, and the slot selector labels carry no ordering indicator.
2. Users paste large ID/value lists with no visibility into whether the entries actually match staged products — typos and dead IDs go unnoticed until a pipeline run.

## Decisions (from brainstorming)

1. **Priority indicators, both surfaces:** slot selector items get `#N` before the slot name (`#1 CUSTOM_LABEL_0` … `#5 CUSTOM_LABEL_4`, registry order); rule card headers replace the `#N Priority` Badge with a compact dimmed `#N` Text **before** the rule name.
2. **Batch lookup endpoint (new, general):** `POST /feed-sources/{id}/products/lookup` — no batch lookup exists today; per-ID detail requests don't scale.
3. **Virtualization:** fixed row height + a small custom windowing hook. **No new npm dependency** (`@tanstack/react-virtual` rejected — 1-D fixed-row list, and textarea↔list scroll sync is custom code either way).
4. **Found semantics:** status-agnostic — removed/excluded products are returned and shown with a dimmed status badge; only truly absent values get the red not-found badge.
5. **Match-field lookup:** the preview appears for **all** rules, looking up values BY the rule's match field (including `id`, i.e. `raw_data['id']`, not the staging `product_id`). One value can match many products; rows show count + first sample.

## 1. Priority indicators

- `SlotSelector` SegmentedControl item labels: `#${index + 1} ${slot.toUpperCase()}` (index in `TARGET_SLOTS` registry order).
- `RuleCard` header: replace the blue `#N Priority` Badge (i18n key `priority`) with a dimmed `#N` Text placed before the rule name; header order becomes `#N · <name> · <badges…>`. The `priority` i18n key is retired (removed from en/de).

## 2. Backend: `POST /feed-sources/{id}/products/lookup`

Located in `backend/app/routes/products.py`, auth like the other product routes.

- Request: `{field: string = "id" (registry attribute path), values: string[] (1–10 000 after dedupe), extraFields: string[] (0–20, optional)}`.
- Matching mirrors the plugin's `matches()`: a value matches a staged product when any candidate value of `raw_data[field]` equals it; matching happens in Python over one full-feed fetch of the staged products (subfield paths `attr.sub` resolve like the plugin's `resolve_path`), and per-value counts plus lowest-`product_id` samples are resolved in two SQL queries. Status-agnostic: `removed` and `excluded` rows participate.
- Response, keyed by value:
  `{"matches": {"<value>": {"count": <int>, "sample": {product_id, status, excluded, title, brand, availability, <extraFields…>} | null}}}`
  - `count` = number of staged products matching the value (any status).
  - `sample` = the matching product with the lowest `product_id` (deterministic), projected to `product_id, status, excluded, title, brand, availability` (title/brand/availability from `raw_data`, missing → `null`) plus requested `extraFields` from `raw_data` (missing → `null`). `null` when `count === 0`.
- SQL: one grouped pass (per-value `count` + `min(product_id)` over the value set) plus one fetch of the sample rows by id; two queries total, no N+1.
- Errors: 404 unknown feed source; 422 invalid body (unknown shape, >10 000 values, >20 extraFields); 503 database unavailable.
- Docs: `backend/docs/api.md` gains the endpoint entry in the same commit. No schema/migration change.

## 3. Frontend data flow

- `useProductLookup(feedSourceId, field, values, extraFields)` in `frontend/src/api/hooks.ts`: TanStack Query, key `[feedSourceId, field, sorted-values-hash, extraFields-hash]`, `staleTime: 30_000`, `placeholderData: keepPreviousData`. 300 ms debounce via `useDebouncedValue` in the consumer. Only unique values are sent; duplicated list entries still render duplicated rows. Result mapped to `Map<value, {count, sample}>`.
- `parseIdEntries(raw): string[]` added to `frontend/src/features/customLabels/ids.ts`: ordered, trimmed, empty-dropped (same tokenization as `parseIdList`, without dedupe) — row *i* = entry *i*.

## 4. Layout, alignment, sync, windowing

New `frontend/src/features/customLabels/ProductPreviewColumn.tsx`, rendered inside `RuleCard`'s panel for **all** rules at feed tier (no feed context → no column, full-width editor as today).

- **Split:** 35 % left / 65 % right — `Grid` with `cols={20}`, spans 7/13. Left = existing Textarea with `wrap="off"` (no soft-wrap), monospace, `line-height` = row height (34 px) so newline-separated lists align 1:1 with preview rows. Right = preview column, same visible height.
- **Alignment:** by parsed-entry index (§3). Caveat: comma-separated one-liner lists align by index, not by visual line.
- **Scroll sync:** bidirectional `scrollTop` copy between textarea and the preview container (plain `div`, `overflowY: auto`, Mantine-styled border), guarded by a `syncing` flag released on the next animation frame — no feedback loop.
- **Windowing:** fixed `ROW_HEIGHT = 34`; visible slice = `scrollTop / ROW_HEIGHT ± overscan(5)`; spacer `div` carries `entries.length × ROW_HEIGHT` total height; windowed rows absolutely positioned. Target: smooth scrolling at 10k entries.
- **Toolbar** above the columns: per-card field MultiSelect (`searchable clearable`), options = feed fields (`useFeedSourceFields`) minus the defaults (`title`, `brand`, `availability`); selection state lifted to `CustomLabelsUI` as `Record<ruleId, string[]>` (survives accordion collapse).

## 5. Row rendering

Row *i* (value *i*) renders, right column:

- `count === 0` → red Badge `ID not found in feed` (field `id`) / `No match in feed` (other fields).
- `count >= 1` → sample product row: **title** (one line, ellipsis-truncated, Tooltip with full title), **brand** (dimmed text; falls back to `—` when absent), **availability badge** (`in_stock` green, `out_of_stock` red, others gray), requested **extra fields** inline (dimmed `label: value`), dimmed `removed`/`excluded` badge when the sample's status warrants it.
- `count > 1` → compact gray `N products` Badge before the sample row.

## 6. Error handling & i18n

- Lookup pending → skeleton rows in the visible window; lookup error → dimmed error line in the column header (data still editable); empty value list → column shows the dimmed empty hint.
- New i18n keys (en + de, `customLabels` ns): `idNotFoundInFeed`, `noMatchInFeed`, `nProducts_one/_other`, `previewTitle` ("Matched products"), `previewFieldsLabel`, `previewEmpty`, `previewError`. Key `priority` removed.

## 7. Testing

- Backend: `test_products_lookup.py` (or extension of the existing products route tests): found/missing/removed/excluded, array-field matching, subfield matching, extraField projection, value dedupe, limits (10 000 / 20), 404/422/503, sample determinism (lowest product_id).
- Frontend: `ProductPreviewColumn.test.tsx` (rows by index, count badges, not-found badge, status badges, scroll sync via scrollTop assertions, windowing slice, MultiSelect toggles extra fields); `useProductLookup` hook test (debounce, key stability, keepPreviousData); `ids.test.ts` additions for `parseIdEntries`; `RuleCard.test.tsx` + `CustomLabelsUI.test.tsx` updates (split layout present at feed tier / absent without feed context, `#N` before rule name, slot labels `#1 CUSTOM_LABEL_0`, `priority` badge gone).
- Gates: frontend `npm run test/typecheck/build`; backend `uv run pytest -n auto` (+ plugin contract tests unchanged — no plugin code touched).

## Out of scope

- Editing product data from the preview column (read-only).
- Persisting per-card extra-field selections (session-local state only).
- Virtualizing the textarea itself (native scroll suffices).
- `@tanstack/react-virtual` (no new dependencies).
- Changing the custom_labels plugin runtime, preview endpoint, or scope-merge semantics.
