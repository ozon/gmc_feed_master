# M1 Task 7 Registry Findings Report

## Verification

- Full backend suite with `TEST_DATABASE_URL` and Compose PostgreSQL: **85 passed**.
- Registry parser/generator focused suite: **11 passed**.
- `python -m compileall app alembic registry`: passed.
- Registry CLI drift check: passed.
- Alembic CLI upgrade and downgrade against PostgreSQL: passed.
- `docker compose config -q`: passed.

## Findings addressed

- Enum normalization removes documented default clauses and ellipsis markers while preserving phrases such as `big and tall` and the complete `body_style` list.
- Nested field format qualifiers are retained for ISO 3166-1, IANA, and percent constraints.
- Exact line diagnostics are asserted for malformed rows, unsupported types, ambiguous structured order, and duplicate fields.
- Representative full-source enum and nested qualifier assertions cover `minimum_order_value.surface`, `returns.window_type`, `body_style`, `adult`, and `identifier_exists`.

## Concerns

- Existing non-blocking warnings remain: Starlette/httpx TestClient deprecation, pytest collection of `TestClock`, and Alembic `path_separator` deprecation.

## M1 Task 7 parser follow-up

- Internal `A+++ … G` syntax is represented as the distinguishable range value `range:A+++..G`, without emitting the ellipsis marker as an enum literal.
- Structured `+` separators preserve ordered `digital_source_type` and `content` subfields, including exact enum values, requirements, and content length limits.
- Requirement markers take precedence over prose notes: `minimum_order_value` and `pickup_cost` remain optional with `required_from:2026-09-30` qualifiers, while `returns.window_days` remains conditional.
- Follow-up verification: focused registry parser suite **10 passed**; full backend suite with Compose PostgreSQL and `TEST_DATABASE_URL` **86 passed**; compileall and registry CLI drift check passed; `docker compose config -q` passed.
