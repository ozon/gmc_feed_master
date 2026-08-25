# Task 5: Delimited reader (TSV/CSV/wide-TSV) — Report

## Summary

Implemented `parse_delimited` in `backend/app/ingest/delimited.py` to parse TSV, CSV, and wide-TSV feeds into the canonical `IngestReport` model.

## What was done

### Files created
- `backend/app/ingest/delimited.py` — `parse_delimited(data, source_format, registry) → IngestReport`
- `backend/tests/test_delimited_reader.py` — 8 tests covering all task requirements
- `backend/tests/fixtures/feeds/simple.tsv` — 3 products, tab-delimited
- `backend/tests/fixtures/feeds/repeated.tsv` — comma-separated `additional_image_link` values
- `backend/tests/fixtures/feeds/wide.tsv` — repeated `shipping(country:price)` columns
- `backend/tests/fixtures/feeds/simple.csv` — comma-delimited equivalent
- `backend/tests/fixtures/feeds/malformed_rows.tsv` — row with surplus colons
- `backend/tests/fixtures/feeds/bom.tsv` — UTF-8 BOM prefix

### Implementation details
1. **Delimiter detection**: `tsv`/`wide_tsv` → tab; `csv` → `csv.Sniffer` sniffs comma vs semicolon (fallback to comma)
2. **BOM stripping**: Checks for UTF-8 BOM (`\xef\xbb\xbf`) and strips before decoding
3. **Blank line handling**: Filters out empty/whitespace-only lines before parsing
4. **RFC-4180 quoting**: Uses `csv.reader` for proper delimiter parsing with quoting support
5. **Error propagation**: `split_row` errors are converted from `flat_notation.RowError` to `report.RowError` with line numbers, appended to `IngestReport.row_errors`, and parsing continues
6. **Empty cell omission**: Delegated to `split_row` which already omits empty keys

## Test coverage
- TSV: correct products, correct count, empty input
- CSV: comma-delimited parsing
- Wide-TSV: repeated structured columns → array of structs
- Repeated scalar: comma-split values
- Malformed rows: skipped, `row_errors` populated with line number, run continues
- BOM: parsed correctly after stripping
- Empty cells: keys omitted from product dict

## Verification
All 8 tests pass (`uv run pytest tests/test_delimited_reader.py -x -q`). No regressions in existing tests.

## Commit
`9359880` feat: delimited reader for TSV, CSV, and wide-TSV formats
