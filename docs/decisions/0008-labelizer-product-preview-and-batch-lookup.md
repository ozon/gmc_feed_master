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
2. **Synchronized, windowed preview column** — at feed tier each expanded rule card splits
   its editor 35/65 (Grid columns=20, spans 7/13): a fixed 10-row, no-soft-wrap, 34px-line
   monospace textarea beside a preview column whose row *i* mirrors parsed entry *i*
   (order + duplicates preserved). Fixed-row windowing is custom (~30 lines: scrollTop →
   slice) — **no new dependency**; `@tanstack/react-virtual` was rejected for a 1-D
   fixed-row list where textarea↔list scroll sync is custom code either way. Scroll sync is
   bidirectional `scrollTop` copying with a rAF-released guard flag and a rebind key so
   listeners re-attach when the synced elements remount. Lookups are 300 ms-debounced,
   TanStack-Query-cached (keyed by sorted value set + fields; `keepPreviousData`), skeleton
   rows shown while fetching so newly typed values never flash as dead.
3. **Found semantics** — dead values render a red `ID not found in feed` (field `id`) /
   `No match in feed` badge; removed/excluded products render normally with dimmed status
   badges (so users see WHY a rule won't label them); values matching several products show
   a gray `N products` badge + the sample. A per-card MultiSelect adds extra raw-data fields
   inline (options from the feed's field list minus title/brand/availability; selection is
   session-local).
4. **Priority display moved** — slot selector items are numbered `#1 CUSTOM_LABEL_0` …
   `#5 CUSTOM_LABEL_4`; rule card headers show a compact dimmed `#N` before the rule name;
   the old `#N Priority` badge and its `priority` i18n key are retired.

## Consequences
- One more O(feed-size) read endpoint, the same per-request budget as the existing
  `custom_labels` preview endpoint; acceptable at current feed sizes. If feeds grow large,
  revisit SQL-side matching (`jsonb_array_elements_text`) for the value set.
- Row alignment is by parsed-entry index, not physical line: comma-separated one-liner
  lists align by index (the textarea uses `wrap="off"` so newline lists align 1:1).
- The endpoint is general-purpose (reusable for future bulk-edit features), not
  `custom_labels`-specific; `resolve_path` is duplicated as
  `_product_field_candidates` in the route with an equivalence test as the drift guard.
- Frontend types `ProductLookupSample`/`ProductLookupMatch` in `frontend/src/api/types.ts`
  are consumed by the preview column; the row height (34px) is a shared constant
  (`productPreview.ts`) coupling textarea line-height and preview rows.
