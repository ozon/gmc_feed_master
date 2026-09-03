# Dynamic Column Selector on Products Table

Date: 2026-09-03
Status: approved, pending implementation

## Problem

The products table column picker offers a fixed set of 11 hardcoded columns
(`ProductColumnId` union in `frontend/src/features/products/columns.ts`). The
backend list endpoint (`GET /feed-sources/{id}/products`) projects only the
7 baseline fields plus `product_id`/`status`/`last_seen_at`, so feed-specific
data present in `raw_data` (e.g. `brand`, `product_type`, `custom_label_0/4`)
can neither be offered by the picker nor shown in the table.

## Decisions (user-confirmed)

1. **Field universe:** fields actually present in this feed source's staged
   data — not all registry attributes.
2. **Discovery:** derive from the rows of the current page response (no extra
   endpoint, no DISTINCT-key query over the whole feed).
3. **Transport:** the list response carries `fields: string[]` (union of
   top-level `raw_data` keys across the returned rows) and each item carries
   its full `raw_data` dict. No `?columns=` projection param.

## Backend change — `backend/app/routes/products.py`

- `list_products` response gains `"fields": sorted(union of raw_data keys
  across the returned rows)`.
- `_list_item` attaches `"raw_data": row.raw_data` in addition to the existing
  baseline keys (which stay unchanged for compatibility).
- Sorting/search/pagination untouched (`_SORTS` still only supports the four
  documented fields; dynamic columns are not sortable).

## Frontend changes

- `frontend/src/api/types.ts`: `ProductListItem.raw_data: Record<string,
  unknown>`, `ProductsPageResponse.fields: string[]`.
- `frontend/src/features/products/columns.ts`:
  - `ProductColumnId` widens from the closed union to `string`.
  - `SYSTEM_COLUMNS` (`product_id`, `status`, `last_seen_at`) always available.
  - Data columns derive from `response.fields`; labels for the known baseline
    set keep their translations, unknown fields use the raw field name.
  - `DEFAULT_COLUMNS` unchanged; `loadColumnConfig`/`saveColumnConfig`
    unchanged (localStorage may contain field ids that are absent from the
    current page — they are kept but simply not rendered until data has them).
- `frontend/src/features/products/ProductsPage.tsx`: column picker lists
  system columns + data fields from the response; `ProductsTable` gets
  `fields` prop.
- `frontend/src/features/products/ProductsTable.tsx`:
  - `COLUMN_ACCESSORS` becomes dynamic: known ids from the item fields,
    unknown ids read `row.raw_data[field]`.
  - Non-string values render via compact `JSON.stringify`.
  - `status` keeps its badge rendering; `last_seen_at` keeps date formatting.
  - Dynamic columns get `enableSorting: false`.

## Trade-off accepted

With `page_size=200`, full `raw_data` per row makes the payload noticeably
larger. Inherent to the chosen transport option.

## Testing

- Backend (`tests/test_products_api.py`): list response includes `fields`
  union and per-item `raw_data` (baseline keys still present).
- Frontend (`ProductsPage.test.tsx`): a data field (e.g. `brand`) appears in
  the picker; toggling it adds the column with values; absent-field ids
  persisted in localStorage do not render columns.

## Docs

`backend/docs/api.md` — products endpoint entry updated in the same change
(`fields[]`, `raw_data` on items).
