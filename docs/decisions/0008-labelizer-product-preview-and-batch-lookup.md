# ADR-0008: Labelizer Product Preview and Batch Value Lookup

## Status
Accepted

## Context
The Labelizer data page lets users paste large value lists (up to ~10k IDs) into rule cards
with no feedback on whether entries match staged products — typos and dead IDs go unnoticed
until a pipeline run. No batch-ID lookup endpoint existed: the per-product detail route
would mean one request per ID, and GET query strings cannot carry 10k values. The previous
slot-view refactor (ADR-0005 follow-up, merged 2026-09-07) rejected rendering full ID lists
for performance, but a preview column can be windowed to a fixed row height.

## Decision
1. **General batch lookup endpoint** — `POST /feed-sources/{id}/products/lookup`
   (`backend/app/routes/products.py`): body `{field, values (1–10 000, deduped server-side),
   extraFields (0–20)}`; response `{matches: {<value>: {count, sample}}}`. Matching happens
   in Python over ONE full-feed fetch, mirroring the `custom_labels` plugin's `resolve_path`
   semantics exactly (scalar / repeated-array / `attr.sub` — pinned by an equivalence test
   against the plugin's own function); it is **status-agnostic** (removed/excluded rows
   participate) and counts every matching staged product, with `sample` = the lowest-
   `product_id` match projected to `product_id, status, excluded, title, brand, availability`
   + requested extra fields. Two SQL queries total (full feed + sample fetch).
2. **Synchronized, windowed, toggleable preview column** — at feed tier each expanded
   rule card renders a compact toolbar (clear, format & dedupe, preview toggle,
   extra fields) above a fixed-width flex row: the value textarea is bounded to
   380px (`flex: 0 0 380px`) in both states, and the preview column (`flex: 1`)
   is **collapsed by default** — one shared toggle lifted to `CustomLabelsUI`
   flips it for every card. Preview row *i* mirrors textarea **line** *i*
   (split on `\n` only; blank lines render blank rows so alignment never breaks;
   a multi-ID line shows its first ID's match plus a `+N more` badge, and the
   Format toolbar action normalizes commas to one ID per line). Rows are 44px
   (`ROW_HEIGHT` in `productPreview.ts`); the textarea input uses zero vertical
   padding with `line-height: 44px`, so line *i*'s top is exactly `i × 44` —
   flush with the absolutely-positioned preview rows and free of the constant
   top offset the first iteration carried. Fixed-row windowing is custom
   (~30 lines: scrollTop → slice) — **no new dependency**;
   `@tanstack/react-virtual` was re-rejected for a 1-D fixed-row list where
   textarea↔list scroll sync is custom code either way. Scroll sync is
   bidirectional `scrollTop` copying with a rAF-released guard flag and a
   rebind key (feed source + preview visibility) so listeners re-attach when
   the synced elements remount. Lookups are 300 ms-debounced,
   TanStack-Query-cached (keyed by sorted value set + fields;
   `keepPreviousData`), skeleton rows shown while fetching so newly typed
   values never flash as dead.
3. **Found semantics** — dead values render a red `ID not found in feed` (field `id`) /
   `No match in feed` badge; removed/excluded products render normally with dimmed status
   badges (so users see WHY a rule won't label them); values matching several products show
   a gray `N products` badge + the sample. A per-card MultiSelect adds extra raw-data fields
   inline (options from the feed's field list minus title/brand/availability; selection is
   session-local).
4. **Priority display moved** — slot selector items are numbered `#1 CUSTOM_LABEL_0` …
   `#5 CUSTOM_LABEL_4`; rule card headers show a compact dimmed `#N` before the rule name;
   the old `#N Priority` badge and its `priority` i18n key are retired.
5. **Shadow attribution moved inline (2026-09-08 rule-card refactor)** — the
   card-footer "Overridden IDs" struck-through list is removed; shadowing is
   communicated by the header `N overridden` badge plus an inline orange
   `OVERRIDDEN BY #N` badge on the affected preview row (tooltip: claiming
   rule name). `computeShadowing` now emits the claiming rule's id, name, and
   1-based slot priority.
6. **Coverage dashboard rule breakdown (2026-09-08 rule-card refactor)** —
   beneath the dashboard progress bar, a wrapping group of `#N name: Mx`
   badges shows each active rule of the selected slot with its **net**
   assigned product count — the preview endpoint's per-rule `labeled` stat
   (winners only, post-shadowing; `matched` remains the pre-shadowing count
   shown in card headers).

## Consequences
- One more O(feed-size) read endpoint, the same per-request budget as the existing
  `custom_labels` preview endpoint; acceptable at current feed sizes. If feeds grow large,
  revisit SQL-side matching (`jsonb_array_elements_text`) for the value set.
- Row alignment is by textarea line index: row *i* = line *i*; comma-separated
  one-liners stay on one row (first-ID match + `+N more`), and the Format
  toolbar action normalizes to one ID per line.
- The endpoint is general-purpose (reusable for future bulk-edit features), not
  `custom_labels`-specific; `resolve_path` is duplicated as
  `_product_field_candidates` in the route with an equivalence test as the drift guard.
- Frontend types `ProductLookupSample`/`ProductLookupMatch` in `frontend/src/api/types.ts`
  are consumed by the preview column; the row height (44px) is a shared constant
  (`productPreview.ts`) coupling textarea line-height and preview rows.
