# Task 7 Report

Implemented the strict normalized registry model, documented Markdown parser, deterministic JSON generator/check mode, CLI, fixture coverage, and generated `backend/registry/attributes.json` from `gmc_def.md`.

## Verification

- Registry parser and generation tests: 8 passed.
- Full backend regression: 62 passed, 20 errors because `TEST_DATABASE_URL` is not configured in this environment.
- `uv run python -m compileall -q backend`: passed.
- Full-source generation and CLI check mode: passed.

## Scope

Runtime loading, artifact integration beyond the generated registry, and CI changes were intentionally not implemented.

## Review Fix Verification (2026-08-24)

- Full-source parser now preserves primary, local-inventory, vehicle-listings,
  and deprecated applicability, including vehicle-valid deprecated rows.
- Duplicate canonical rows are rejected with both the duplicate and first source
  lines; intentional source repeats are represented as explicit applicability.
- Unsupported types are rejected rather than coerced to String.
- Structured field enums, requirement status, limits, formats, qualifiers,
  ordered fields, metadata, and source lines are retained in normalized output.
- Stale check output includes a unified byte-level text diff.
- Registry parser/generator tests: 9 passed.
- Full backend suite with Compose PostgreSQL and `TEST_DATABASE_URL`: 83 passed.
- `compileall`, registry CLI check, and `git diff --check`: passed.

Runtime loader, artifact integration beyond generation, and CI changes remain
out of scope as requested.

## Remaining Parser Findings Verification (2026-08-24)

- Structured objects preserve bare names, ordered declarations, nested primitive
  types, requirement markers, enum alternatives, and constraints/formats.
- Full-source assertions cover adult, identifier_exists, body_style, shipping,
  minimum_order_value, pickup_cost, returns, loyalty_program, and nested URL/
  Price fields.
- Duplicate diagnostics assert the duplicate and first source lines plus field
  name; cross-section applicability repeats remain the only accepted repeats.
- Registry parser and generation tests: 9 passed.
- Registry generation/check, compileall, and `git diff --check`: passed.
- Full backend: 63 passed, 20 PostgreSQL errors because `TEST_DATABASE_URL` is
  not configured in this environment.
