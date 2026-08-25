# M3 Implementation Plan: Input Readers & Canonical Product Model

**Date:** 2026-08-25
**Spec:** `docs/superpowers/specs/2026-08-25-m3-input-readers-design.md`
**Base:** `main` at `16f7569`
**Execution:** isolated worktree `.worktrees/m3-input-readers`, branch `m3-input-readers` (create via `superpowers:using-git-worktrees` before Task 1)

## Conventions (read first)

- Backend lives in `backend/`; run commands from there with `uv run ...`
- Models: SQLAlchemy 2.x typed `Mapped[...]`/`mapped_column(...)`, `from app.db.base import Base`
- Tests: pytest + pytest-asyncio (`asyncio_mode` is not set — mark async tests `@pytest.mark.asyncio`); PostgreSQL-backed tests use the `isolated_database_url` fixture from `tests/conftest.py` (requires `TEST_DATABASE_URL` and Compose PostgreSQL running)
- Registry: `from registry.loader import load_registry` returns `RegistryDocument` with `.attributes: dict[str, RegistryAttribute]`; each `RegistryAttribute` has `.kind: AttributeKind`, `.fields: tuple[SubField, ...]`
- `FeedSource` model: `source_format: str`, `source_url: str | None`, `configuration: dict[str, Any]` (JSONB)
- `StepContext` is a frozen dataclass; `PipelineRunner.execute` creates it at `runner.py:60`
- `DEFAULT_STEPS` in `steps.py:61` is a tuple of four step instances
- TDD: write failing test → implement → green → commit per task
- No comments in code unless required for clarity of a non-obvious decision

## File map

| File | Responsibility |
|---|---|
| `backend/app/ingest/__init__.py` | package exports |
| `backend/app/ingest/report.py` | `RowError`, `IngestReport` dataclasses |
| `backend/app/ingest/flat_notation.py` | header grammar parsing, value splitting, registry validation |
| `backend/app/ingest/delimited.py` | TSV/CSV/wide-TSV reader |
| `backend/app/ingest/xml_reader.py` | GMC feed XML reader (rss/atom) |
| `backend/app/ingest/fetch.py` | `HttpFetcher` (httpx async, timeout, size limit, Basic Auth) |
| `backend/app/pipeline/steps.py` | add `RunState`, add `run_state` to `StepContext`, real `IngestStep` |
| `backend/app/pipeline/runner.py` | create `RunState` per run, pass into `StepContext` |
| `backend/app/pipeline/__init__.py` | export `RunState` |
| `backend/tests/test_flat_notation.py` | header grammar + value splitting + registry validation |
| `backend/tests/test_delimited_reader.py` | TSV/CSV/wide-TSV parsing |
| `backend/tests/test_xml_reader.py` | GMC feed XML parsing |
| `backend/tests/test_fetch.py` | HttpFetcher unit tests |
| `backend/tests/test_ingest_step.py` | IngestStep unit tests (stub fetcher) |
| `backend/tests/test_m3_acceptance.py` | PostgreSQL-backed integration: runner + IngestStep end-to-end |
| `backend/tests/fixtures/feeds/` | fixture files for all four formats |

## Task 1: RunState + StepContext.run_state + runner wiring

**Goal:** Add the mutable run-state channel without breaking existing tests.

**Files:** `backend/app/pipeline/steps.py`, `backend/app/pipeline/runner.py`, `backend/app/pipeline/__init__.py`, `backend/tests/test_pipeline_steps.py`, `backend/tests/test_pipeline_runner.py`

**Steps:**
1. RED: In `test_pipeline_steps.py`, add a test that constructs `StepContext` with a `run_state` kwarg and asserts `ctx.run_state.products == []`. Run → fails (unexpected kwarg).
2. GREEN: In `steps.py`:
   - Add `@dataclass` class `RunState` with `products: list[dict[str, Any]] = field(default_factory=list)`.
   - Add `run_state: RunState` field to `StepContext` (after `logger`).
3. Update `runner.py:60` — create `run_state = RunState()` before the step loop and pass it into `StepContext(...)`.
4. Update `__init__.py` — export `RunState`.
5. Fix existing tests that construct `StepContext` directly (add `run_state=RunState()`).
6. Run full suite: `uv run pytest tests/ -x -q` → green.
7. Commit: `feat: add RunState to StepContext and runner`

## Task 2: IngestReport + RowError

**Goal:** Define the data structures readers return.

**Files:** `backend/app/ingest/__init__.py`, `backend/app/ingest/report.py`, `backend/tests/test_flat_notation.py` (create)

**Steps:**
1. Create `backend/app/ingest/__init__.py` (empty for now).
2. Create `backend/app/ingest/report.py`:
   ```python
   from __future__ import annotations
   from dataclasses import dataclass, field
   from typing import Any

   @dataclass
   class RowError:
       line: int
       message: str

   @dataclass
   class IngestReport:
       products: list[dict[str, Any]] = field(default_factory=list)
       row_errors: list[RowError] = field(default_factory=list)
   ```
3. RED: In `test_flat_notation.py`, write a trivial import test: `from app.ingest.report import IngestReport, RowError`. Run → passes (module exists).
4. Commit: `feat: add IngestReport and RowError dataclasses`

## Task 3: Flat-notation header parsing

**Goal:** Parse annotated headers into a column plan.

**Files:** `backend/app/ingest/flat_notation.py`, `backend/tests/test_flat_notation.py`

**Steps:**
1. RED: Write tests for `parse_header(headers: list[str], registry: RegistryDocument) -> HeaderPlan`:
   - Bare scalar: `["title", "price"]` → two scalar columns
   - Annotated structured: `["shipping(country:price)"]` → structured column with sub-fields `["country", "price"]`
   - Repeated structured: `["shipping(country:price)", "shipping(country:price)"]` → repeated structured
   - Unknown attribute kept generically: `["internal_sku"]` → generic scalar column
   - Bare structured column (registry-known structured attr, no annotation) → raises `HeaderError`
   - Unknown sub-field on known attribute: `["shipping(contry:price)"]` → raises `HeaderError`
   - Duplicate scalar column: `["title", "title"]` → raises `HeaderError`
2. GREEN: Implement `flat_notation.py`:
   - `HeaderError(Exception)` with a message naming the offending column
   - `@dataclass ColumnSpec`: `name: str`, `kind: str` (one of `"scalar"`, `"repeated_scalar"`, `"structured"`, `"repeated_structured"`, `"generic"`), `sub_fields: list[str]`
   - `@dataclass HeaderPlan`: `columns: list[ColumnSpec]`
   - `parse_header(headers, registry)` — regex `^(\w+)\(([^)]+)\)$` for annotated; look up `registry.attributes.get(name)` for kind/sub-field validation
3. Run: `uv run pytest tests/test_flat_notation.py -x -q` → green.
4. Commit: `feat: flat-notation header parsing with registry validation`

## Task 4: Flat-notation value splitting

**Goal:** Split a row's cell values according to the header plan.

**Files:** `backend/app/ingest/flat_notation.py`, `backend/tests/test_flat_notation.py`

**Steps:**
1. RED: Write tests for `split_row(cells: list[str], plan: HeaderPlan) -> tuple[dict[str, Any], RowError | None]`:
   - Scalar: `["Red Shirt"]` → `{"title": "Red Shirt"}`
   - Empty cell → key omitted
   - Repeated scalar (comma-separated): `["img1.jpg,img2.jpg"]` → `{"additional_image_link": ["img1.jpg", "img2.jpg"]}`
   - Quoted comma preserved: `['"img1.jpg,img2.jpg"']` → single-element list (RFC-4180)
   - Annotated structured: `["US:6.49 USD"]` with sub-fields `["country", "price"]` → `{"shipping": {"country": "US", "price": "6.49 USD"}}`
   - Surplus colons: `["US:6.49:extra"]` with 2 sub-fields → returns `RowError`
   - Repeated structured (two columns): cells from two columns → `{"shipping": [{...}, {...}]}`
2. GREEN: Implement `split_row` in `flat_notation.py`.
3. Run: `uv run pytest tests/test_flat_notation.py -x -q` → green.
4. Commit: `feat: flat-notation value splitting`

## Task 5: Delimited reader (TSV/CSV/wide-TSV)

**Goal:** Parse delimited feeds into the canonical model.

**Files:** `backend/app/ingest/delimited.py`, `backend/tests/test_delimited_reader.py`, `backend/tests/fixtures/feeds/`

**Steps:**
1. Create fixture files:
   - `fixtures/feeds/simple.tsv` — 3 products, tab-delimited, headers: `id\ttitle\tprice\tlink`
   - `fixtures/feeds/repeated.tsv` — includes `additional_image_link` with comma-separated values
   - `fixtures/feeds/wide.tsv` — repeated `shipping(country:price)` columns
   - `fixtures/feeds/simple.csv` — comma-delimited equivalent
   - `fixtures/feeds/malformed_rows.tsv` — rows with surplus colons
   - `fixtures/feeds/bom.tsv` — UTF-8 BOM prefix
2. RED: Write tests for `parse_delimited(data: bytes, source_format: str, registry: RegistryDocument) -> IngestReport`:
   - TSV: correct products, correct count
   - CSV: same with comma delimiter
   - Wide-TSV: repeated structured columns → array of structs
   - Repeated scalar: comma-split
   - Malformed rows: skipped, `row_errors` populated, run continues
   - BOM: parsed correctly
   - Empty cells: keys omitted
3. GREEN: Implement `delimited.py`:
   - Detect delimiter from `source_format` (`tsv`/`wide_tsv` → tab, `csv` → sniff comma/semicolon)
   - Decode UTF-8 (strip BOM), split into lines, parse header via `parse_header`, iterate rows via `split_row`
   - Use `csv.reader` for proper RFC-4180 quoting
4. Run: `uv run pytest tests/test_delimited_reader.py -x -q` → green.
5. Commit: `feat: delimited reader for TSV, CSV, and wide-TSV formats`

## Task 6: XML reader (GMC feed XML)

**Goal:** Parse GMC feed XML (rss/atom) into the canonical model.

**Files:** `backend/app/ingest/xml_reader.py`, `backend/tests/test_xml_reader.py`, `backend/tests/fixtures/feeds/`

**Steps:**
1. Create fixture files:
   - `fixtures/feeds/simple_rss.xml` — rss → channel → item, `g:`-namespaced tags
   - `fixtures/feeds/simple_atom.xml` — atom → entry, bare tags
   - `fixtures/feeds/nested_shipping.xml` — `g:shipping` with child elements
   - `fixtures/feeds/repeated_images.xml` — multiple `g:additional_image_link` siblings
   - `fixtures/feeds/malformed.xml` — invalid XML
   - `fixtures/feeds/bad_item.xml` — one valid item, one item with unparseable structure
2. RED: Write tests for `parse_xml(data: bytes, registry: RegistryDocument) -> IngestReport`:
   - RSS: correct products from `g:`-namespaced tags
   - Atom: correct products from bare tags
   - Nested shipping: `{"shipping": {"country": "US", "price": "6.49 USD"}}`
   - Repeated siblings: `{"additional_image_link": ["url1", "url2"]}`
   - Malformed XML: raises (run fails)
   - Bad item: skipped, `row_errors` populated
3. GREEN: Implement `xml_reader.py` using `xml.etree.ElementTree`:
   - Detect root: `rss` → find `channel/item`; `feed` (atom) → find `entry`
   - For each item: iterate children, strip namespace prefix, build product dict
   - Repeated siblings → list; nested elements → dict
   - Wrap `ET.fromstring` errors → raise `XmlParseError`
4. Run: `uv run pytest tests/test_xml_reader.py -x -q` → green.
5. Commit: `feat: XML reader for GMC feed format (rss/atom)`

## Task 7: HttpFetcher

**Goal:** Fetch source data over HTTP(S) with timeout, size limit, and Basic Auth.

**Files:** `backend/app/ingest/fetch.py`, `backend/tests/test_fetch.py`

**Steps:**
1. RED: Write tests for `HttpFetcher.fetch(url, basic_auth=None) -> bytes` using `httpx.MockTransport`:
   - Success: returns bytes
   - Timeout: raises `FetchError`
   - Non-2xx: raises `FetchError` with status
   - Size limit exceeded: raises `FetchError`
   - Basic Auth: `Authorization` header present
2. GREEN: Implement `fetch.py`:
   - `FetchError(Exception)`
   - `HttpFetcher` with `timeout: float = 60.0`, `max_bytes: int = 500 * 1024 * 1024`
   - Use `httpx.AsyncClient` with `timeout=httpx.Timeout(self.timeout)`
   - Stream response, accumulate bytes, abort if `max_bytes` exceeded
   - Apply `httpx.BasicAuth` if credentials provided
3. Run: `uv run pytest tests/test_fetch.py -x -q` → green.
4. Commit: `feat: HttpFetcher with timeout, size limit, and Basic Auth`

## Task 8: Real IngestStep

**Goal:** Replace the no-op `IngestStep` with fetch → parse → populate run state.

**Files:** `backend/app/pipeline/steps.py`, `backend/tests/test_ingest_step.py`

**Steps:**
1. RED: Write tests for `IngestStep.execute(ctx)`:
   - Happy path: stub fetcher returns TSV bytes → `run_state.products` populated, `StepResult.processed_count` correct
   - Missing `source_url`: raises → run fails
   - Fetch error: raises → run fails
   - Row errors: `StepResult.failed_count` correct, `statistics["row_errors"]` populated (first 100)
   - XML format: stub fetcher returns XML bytes → products parsed
2. GREEN: Implement real `IngestStep`:
   - Constructor takes `fetcher: HttpFetcher` and `registry: RegistryDocument`
   - `execute`: load `FeedSource` via `ctx.session_factory`, check `source_url`, fetch, dispatch to reader by `source_format`, populate `ctx.run_state.products`, return `StepResult`
   - `read_feed(data, source_format, registry)` dispatch function in `app/ingest/__init__.py`
3. Update `DEFAULT_STEPS` — `IngestStep` now needs constructor args; change to a factory or pass defaults. Decision: `DEFAULT_STEPS` becomes a function `default_steps(fetcher, registry)` that returns the tuple. Update `runner.py` and `main.py` accordingly.
4. Update `main.py` — load registry at startup via `load_registry()`, create `HttpFetcher()`, pass to `default_steps(...)`.
5. Fix existing tests that reference `DEFAULT_STEPS` directly.
6. Run: `uv run pytest tests/test_ingest_step.py tests/test_pipeline_steps.py tests/test_pipeline_runner.py -x -q` → green.
7. Commit: `feat: real IngestStep with fetch, parse, and run-state population`

## Task 9: Integration test (PostgreSQL-backed)

**Goal:** Verify the full runner → IngestStep → run-state flow against a real database.

**Files:** `backend/tests/test_m3_acceptance.py`

**Steps:**
1. RED: Write `test_m3_acceptance.py`:
   - Create a `FeedSource` with `source_format="tsv"`, `source_url="http://test.local/feed.tsv"`, `configuration={"basic_auth": {"username": "u", "password": "p"}}`
   - Stub the fetcher to return TSV bytes
   - Run `PipelineRunner.execute(feed_source_id)`
   - Assert: `IngestionRun.status == "success"`, `statistics["processed_count"] > 0`, `run_state.products` populated (via a test step that captures it)
   - Assert: row errors appear in `statistics["row_errors"]` when present
2. GREEN: Wire the test with a stub fetcher injected into the runner's steps.
3. Run: `TEST_DATABASE_URL=... uv run pytest tests/test_m3_acceptance.py -x -q` → green.
4. Commit: `feat: M3 acceptance test — runner + IngestStep end-to-end`

## Task 10: Full suite verification + acceptance gate

**Goal:** All tests green, compileall clean, no regressions.

**Steps:**
1. Run: `uv run python -m compileall app/ registry/ -q` → clean.
2. Run: `TEST_DATABASE_URL=... uv run pytest tests/ -x -q` → all green.
3. Run: `git diff --check` → clean.
4. Verify: `uv run pytest tests/test_m2_acceptance.py -x -q` → still green (no M2 regressions).
5. Commit: `feat: M3 acceptance gate — all readers, IngestStep, and integration verified`

## Verification checklist

- [ ] All four formats (XML, TSV, CSV, wide-TSV) parse into the canonical model
- [ ] Malformed rows logged & skipped; header errors fail the run
- [ ] Flat-notation: annotated headers, repeated columns, comma-split scalars, surplus-colon row errors
- [ ] Registry sub-field subset validation; unknown sub-field → header error
- [ ] Bare structured column → header error
- [ ] Unknown attributes kept generically
- [ ] HttpFetcher: timeout, size limit, Basic Auth
- [ ] IngestStep populates `run_state.products`
- [ ] Row errors surface in `IngestionRun.statistics`
- [ ] M2 acceptance test still passes
- [ ] compileall clean
