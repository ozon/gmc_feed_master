# Design: Lenient TSV Ingest & Baseline-Required Mapping Alert

**Date:** 2026-09-02
**Status:** Approved (user approved design in session; execution authorized without further questions)
**Scope:** `backend/app/ingest/`, `backend/app/mapping/`, `backend/app/qc/`, `backend/app/routes/`, `backend/app/schemas/`, `frontend/src/features/setup/`, `frontend/public/locales/`, `backend/tests/`, `frontend/src/features/setup/` tests, docs.

## Problem

Two independent defects block importing real-world feeds (including `examples/US-MULTIFEED-2026.tsv`):

1. **TSV reader hard-fails on real feeds.**
   - `parse_delimited` (`backend/app/ingest/delimited.py`) splits input on physical lines before running `csv.reader` per line. RFC-4180 quoted cells containing embedded newlines (multi-line product descriptions — present in `US-MULTIFEED-2026.tsv`) are shredded into fake rows: content lines become 1-column "rows" and the true logical rows get wrong column counts.
   - `parse_header` (`backend/app/ingest/flat_notation.py:62-70`) raises `HeaderError` when an annotated header `attr(sub:…)` declares a sub-field absent from the registry. One such column (`tax(country:location_group_name:…)` — `location_group_name` is a `shipping` sub-field, not a `tax` sub-field in `gmc_def.md`) aborts the **entire feed**, even though every other column is fine.

2. **"Required registry attributes not covered" alert is over-broad.**
   `MappingTab.tsx:80-90` flags every registry attribute with `required == 'required'` — including vehicle-listings fields (`vin`, `make`, `model`, `year`, `mileage`, `trim`, `dealership_*`), local-inventory fields (`store_code`, `quantity`, `region_id`), and alternative fields (`structured_title`/`structured_description`) — none of which a normal primary product feed maps. The engine spec (§6, §7) says the highlight target is **baseline-required** attributes only: `id`, `title` *or* `structured_title`, `description` *or* `structured_description`, `link`, `image_link`, `availability`, `price`, `condition`.

Non-goal (already works, locked in with tests): feeds whose products carry different optional fields (`custom_label_1` present in one feed, absent in another) — mappings are per feed source, product fields are optional per product.

Recorded follow-up (registry gap, not addressed this cycle): the registry parser does not expand backtick name ranges (`custom_label_0` … `custom_label_4` at `gmc_def.md:127`), so only `custom_label_0` and `custom_label_4` exist in `registry/attributes.json`. `custom_label_1/2/3` are unmapped by auto-match today; feeds carrying those columns work (values dropped as unmapped fields). A future cycle should teach the parser to expand same-prefix numbered ranges and regenerate `registry/attributes.json` — required before the Labelizer plugin (spec §5.9, `target_label` slots 0–4) ships. Do NOT change the parser in this cycle.

## Decisions (user-confirmed)

| Question | Decision |
|---|---|
| Annotated header declares unknown sub-field(s) | Keep the column; declared sub-fields remain the positional truth for value splitting; unknown sub-fields ride along in the parsed dict and are dropped later by mapping/export (both already filter to registry-known sub-fields). Known sub-fields (`rate`, `tax_ship`, …) are preserved. |
| Alert scope | Baseline-required attributes only (spec §7 list), with title/structured_title and description/structured_description counted covered when either member is mapped. Brand stays a QC warning (already is). Vehicle/LIA-only fields never appear. |
| Embedded newlines in quoted cells | Proper RFC-4180 stream parsing via a single `csv.reader` pass over the full text. |
| Test thoroughness | Full-chain tests using the real example files, copied into `backend/tests/fixtures/feeds/`. |

## Architecture

### 1. Reader: RFC-4180 stream parsing (`app/ingest/delimited.py`)

`parse_delimited` is rewritten to:
1. Strip BOM, decode UTF-8 (unchanged).
2. Run **one** `csv.reader(io.StringIO(text), delimiter=…)` pass over the whole stream — quoted cells with embedded newlines, escaped quotes, and delimiter sniffing (CSV) behave per RFC-4180 automatically.
3. First non-blank logical row = header; leading logical rows whose every cell is empty are skipped (same intent as today's blank-line drop).
4. Each subsequent logical row is parsed via `split_row`; row-error `line` numbers use the reader's `line_num` after consuming the row (physical line where the row ends — identical values to the current implementation for single-line rows, which is what all existing tests and fixtures use).
5. Logical rows whose every cell is empty are skipped silently (today: lines that strip to "" are dropped — same behavior for realistic files).

Error surface unchanged: `IngestReport.products`, `IngestReport.row_errors`, `RowError(line, message)`. `HeaderError` still raised for genuinely broken headers (duplicate scalar columns, non-adjacent repeated structured, annotating a non-structured attribute) — those are structural mistakes, not data variance.

### 2. Header leniency (`app/ingest/flat_notation.py`)

In `parse_header`'s annotated branch: remove the "unknown sub-field" `HeaderError`. The `ColumnSpec.sub_fields` list is whatever the header declared (order preserved). No other changes — kind inference, adjacency rules, duplicate detection stay strict.

Downstream effect (no code change needed — verified during exploration):
- `apply_mapping` (`app/mapping/apply.py:57-62`) already filters structured dicts to registry-known sub-fields, so `tax.location_group_name` never reaches staging. **Caveat handled in the plan:** filtering happens after `split_row` built the positional dict, so the *declared* sub-field order (kept intact in `ColumnSpec.sub_fields`) is what makes `US::::0.0825` land on the right keys — the test suite must assert the filtered result keeps `rate`/`tax_ship` values correctly aligned.
- `render_feed` (`app/export/renderer.py:26-33`) iterates registry sub-fields only, so unknown keys can never be exported.
- `auto_match`/`_validate_mappings` are unaffected: they validate target paths against the registry, and the source field name (`tax`) still matches the registry attribute.

### 3. Baseline-required flag (backend, single source of truth)

- `app/qc/constants.py`: add `BASELINE_REQUIRED: tuple[str, …] = ("id", "link", "image_link", "availability", "price", "condition")` and `BASELINE_ALTERNATIVE_PAIRS: tuple[tuple[str, str], …] = (("title", "structured_title"), ("description", "structured_description"))`.
- `app/qc/rules.py` `BaselineRequired._REQUIRED` now references the shared constant (dedupe; behavior identical).
- `app/schemas/field_mapping.py`: `RegistryAttributeOut` gains `baseline_required: bool`.
- `app/routes/registry.py`: populate it — `attribute.name in BASELINE_REQUIRED or attribute.name in {name for pair in BASELINE_ALTERNATIVE_PAIRS for name in pair}`.
- `/registry/attributes` response shape: additive only. No other endpoints change.

### 4. Frontend alert (`MappingTab.tsx`)

- `frontend/src/api/types.ts`: `RegistryAttribute` gains `baseline_required?: boolean` (optional — backward compatible with older API during rollout).
- `requiredUncovered` computation: consider only attributes with `baseline_required === true`; a pair (`title`/`structured_title`, `description`/`structured_description`) counts as covered when **either** member is in `coveredTargets`; an uncovered pair lists both members (the operator sees which alternatives exist). Non-pair baseline attrs (`id`, `link`, `image_link`, `availability`, `price`, `condition`) list individually when uncovered. The backend flag already excludes vehicle/LIA fields — they're not baseline — so no feed-type filtering is needed in the frontend.
- Alert text/keys unchanged (`mapping.requiredUncovered`, `mapping.requiredUncoveredList`), so no locale changes needed.
- Missing baseline fields remain enforced where they belong: QC `baseline_required` rule, non-blocking, per spec §7.

### 5. Tests

**Fixtures:** copy `examples/US-MULTIFEED-2026.tsv` → `backend/tests/fixtures/feeds/multifeed.tsv`; copy `examples/feed.xml` → `backend/tests/fixtures/feeds/example_feed.xml`. (Keeps `examples/` as the operator's live samples; fixtures are stable test inputs.)

**Backend:**
- `test_delimited_reader.py`: new `TestRFC4180` — quoted cell with embedded newline parses as one product with the full description; row-error line numbers unchanged for existing fixtures; empty logical rows skipped.
- `test_flat_notation.py`: `parse_header(["tax(country:location_group_name:rate:tax_ship)"], registry)` succeeds with declared sub_fields (registry `tax` lacks `location_group_name`); existing strict-error tests (duplicate columns, non-adjacent repeats) unchanged.
- New `test_example_feed_chain.py`: for each of `multifeed.tsv` (tsv) and `example_feed.xml` (xml):
  - `read_feed` succeeds; product count correct (14, 308); row errors empty;
  - `auto_match` over observed source fields yields expected core mappings (`id`→`id`, `title`→`title`, `shipping`→`shipping`, `tax`→`tax`, …);
  - `apply_mapping` output: `tax` dict contains only registry sub-fields (no `location_group_name`); per-product optional fields (`custom_label_1`) appear only where the source has values;
  - `render_feed` produces valid `rss` XML with `<g:id>` items; `custom_label_1` rendered for products that have it and absent for those that don't;
  - QC `BaselineRequired` produces zero critical findings for the mapped products.
- Existing `test_field_mapping_api.py` / registry route tests: add assertion for `baseline_required` on known attributes (`id` → true, `brand` → false, `structured_title` → true, `vin` → false).

**Frontend:** update `MappingTab.test.tsx` — alert now lists baseline attrs only (`id` uncovered → shown; `brand` uncovered → not shown; `vin`-like required attrs not present in fixture anyway); new case: pair covered via `structured_title` alone suppresses the pair. Registry fixture payloads gain `baseline_required`.

**Contract tests:** plugin contract suite untouched (no plugin changes).

### 6. Documentation (same commit)

- `backend/docs/architecture.md`: § ingest — RFC-4180 stream parsing; annotated-header sub-fields are trust-the-header positional, unknown ones filtered downstream; baseline-required definition and its single source (`qc/constants.py`).
- `backend/docs/api.md`: `/registry/attributes` — new `baseline_required` field.
- `backend/docs/data-model.md`: no schema change (JSONB document only) — mention only if it documents the mapping alert; check and update if it references the alert semantics.
- `frontend/docs/architecture.md`: only if it documents the mapping-tab alert semantics — update the baseline-required pairing rule there.
- ADR: not warranted (no architectural decision change; reader leniency + alert scope correction follow spec §5.8/§6/§7 — the current code was the deviation).

## Error handling

- `HeaderError` remains for structural header mistakes (duplicate scalar, non-adjacent repeated, non-structured annotation) → feed import fails with a precise message (unchanged surface).
- Unknown annotated sub-fields: silent leniency by design (data variance), filtered at mapping/export.
- Malformed data cells (surplus colons): row-level error, row skipped (unchanged).
- No migrations, no new dependencies, no plugin-contract changes.

## Testing summary

`uv run pytest -n auto` (backend; needs `TEST_DATABASE_URL`), `uv run ruff check .`, `uv run mypy .` from `backend/`; `npm run test`, `npm run typecheck` from `frontend/`. Full-chain tests use the two real example files.
