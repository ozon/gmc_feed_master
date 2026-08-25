# M3 Design: Input Readers & Canonical Product Model

**Date:** 2026-08-25
**Status:** Approved
**Builds on:** M2 (commit `e6e7ac6` on `main`)
**Implements:** spec §5.5 (canonical product model), §5.8 (input formats & flat-notation parsing), §3 (Input Reader stage)

> Numbering note: this is the project's third built milestone (M3) and corresponds
> to the AGENTS.md milestone-table row labeled "M2" (input readers + canonical
> model). The project sequence M0/M1/M2 is already used for foundation,
> persistence+registry, and scheduler/runner skeleton.

## Scope

M3 delivers the input-reading stage of the pipeline: fetching a source feed over
HTTP(S) and parsing it — in all four supported formats — into the canonical
product model. The real `IngestStep` replaces the M2 no-op and hands parsed
products to downstream steps through a shared run state.

**In scope:**
- Canonical product model (JSON-native `dict[str, Any]`, the four attribute kinds of §5.5)
- Flat-notation parsing (§5.8), registry-driven via the M1 Attribute Registry
- Four format readers: XML (GMC feed), TSV, CSV (delimiter sniffing), wide-format TSV
- HTTP(S) fetch: 60 s timeout, 500 MB limit, optional Basic Auth
- Malformed rows logged & skipped; header/structural errors fail the run
- Real `IngestStep`: fetch → parse → populate run state → report counts/errors
- Row-error visibility through the existing run-history API (`IngestionRun.statistics`)

**Out of scope:**
- Field mapping (auto + manual) — next milestone
- Staging DB, delta mechanics (`content_hash`/`config_hash`)
- Plugin execution, QC rules, XML export
- File-upload ingestion endpoint (HTTP fetch only this milestone)
- Frontend

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Canonical product | Plain `dict[str, Any]`, no wrapper class | §5.5 is JSON-native; a dict is what plugins, staging, and the writer all consume. No abstraction needed yet |
| Leaf value types | All leaves stay strings | GMC values embed units/currency (`"49.99 EUR"`); parsing to numbers would lose fidelity. Type coercion is QC/writer concern |
| Reader architecture | `Reader` protocol + per-format implementations | Mirrors §3 boundaries; each format independently testable; wide-TSV/TSV/CSV share the flat-notation core |
| Flat-notation core | Shared `flat_notation.py` used by all delimited readers | One place for header grammar + value splitting; wide-TSV is TSV with repeated/annotated columns, not a separate parser |
| Unknown source columns | Parsed generically, kept under source name | Field mapping (next milestone) decides their fate; dropping pre-empts the auto mapper |
| Known-attribute sub-field validation | Declared sub-fields must be a subset of the registry's; unknown sub-field name → header error | Catches typos (`shipping(contry:price)`) while allowing feeds that omit optional sub-fields |
| Bare structured column | Header error → run fails | §5.8: implicit-order structured columns are "rejected with a clear error" |
| Row vs header errors | Row errors (surplus colons, unparseable structure) → logged & skipped; header errors → run fails | A broken header means the whole feed is suspect; a single bad row should not lose the feed |
| XML scope | GMC feed XML only (rss/atom, `g:` namespace or bare tags) | §5.8's four formats refer to GMC XML feeds, not arbitrary merchant XML |
| Source acquisition | HTTP(S) fetch only | §5.8 defines fetch semantics; upload endpoint deferred |
| Format selection | From `FeedSource.source_format`, not content sniffing | The feed source declares its format; sniffing adds ambiguity |
| Fetch client | httpx async (already pinned 0.28.1) | No new dependency; async matches FastAPI execution model |
| Run state channel | `StepContext` gains a mutable `run_state: RunState` | `StepContext` stays frozen; `RunState` is the designated mutable channel for products between steps |
| Row-error reporting | First 100 row errors (truncated) in `StepResult.statistics` | Surfaces in the existing run-history API without a new table |

## Architecture

### New package: `backend/app/ingest/`

```
app/ingest/
  __init__.py        # exports Reader, read_feed, HttpFetcher, IngestReport, RowError
  flat_notation.py   # header grammar, value splitting, registry validation
  delimited.py       # TSV/CSV/wide-TSV reader (shared flat-notation core)
  xml_reader.py      # GMC feed XML reader (rss/atom, g: namespace)
  fetch.py           # HttpFetcher (timeout, size limit, Basic Auth)
  report.py          # IngestReport, RowError
```

### Canonical product model

A product is `dict[str, Any]`. Keys are attribute names; values take one of the
four §5.5 kinds:

| Kind | Python shape | Example |
|---|---|---|
| Scalar | `str` | `"title": "Red Shirt"` |
| Repeated scalar | `list[str]` | `"additional_image_link": ["…", "…"]` |
| Structured (single) | `dict[str, str]` | `"installment": {"months": "12", "amount": "49.99 EUR"}` |
| Structured (repeated) | `list[dict[str, str]]` | `"shipping": [{"country": "US", "price": "6.49 USD"}]` |

Rules:
- All leaf values are strings.
- Empty cells / empty elements are omitted (key absent), not stored as empty strings.
- Empty elements are stripped from repeated fields at ingestion. The writer
  still applies its own empty-element stripping (spec §5.7) because plugins
  can create empty slots downstream of ingestion.
- Pass-through fidelity: structures no component touches reach later stages unchanged.

### Reader protocol

```python
class Reader(Protocol):
    def parse(self, data: bytes, registry: RegistryDocument) -> IngestReport: ...
```

`IngestReport`:

```python
@dataclass
class RowError:
    line: int            # 1-based source line (delimited) or item index (XML)
    message: str

@dataclass
class IngestReport:
    products: list[dict[str, Any]]
    row_errors: list[RowError]
```

`read_feed(data, source_format, registry)` dispatches to the reader for the
declared format.

### Flat-notation parsing (`flat_notation.py`)

Header grammar (§5.8):
- `attr` — bare column.
- `attr(sub1:sub2:…)` — annotated structured column; values split left-to-right
  by declared arity; surplus colons in a value → row error (logged, row skipped).
- Same header n times → repeated structured attribute (array of n structs,
  column order preserved).
- Comma-separated cell → repeated scalar (RFC-4180 quoting respected, so quoted
  commas survive).
- Bare structured column (registry-known structured attribute with no
  annotation) → header error, run fails with a clear message.

Registry validation at header time:
- Known attribute + annotated: declared sub-fields must be a subset of the
  registry's sub-fields; an unknown sub-field name → header error, run fails.
- Known repeated scalar: comma-splitting applied.
- Unknown attribute: parsed generically, kept under its source name.

Error classes:
- **Header errors** (unknown sub-field on a known attribute, bare structured
  column, duplicate scalar column) → raise; the run fails.
- **Row errors** (surplus colons, unparseable structure) → recorded in
  `IngestReport.row_errors`, row skipped, run continues.

### Delimited reader (`delimited.py`)

Handles `tsv`, `csv`, and `wide_tsv`:
- TSV / wide-TSV: tab-delimited.
- CSV: delimiter sniffing (comma/semicolon), RFC-4180 quoting.
- UTF-8, BOM-tolerant.
- Builds the header plan once (via `flat_notation`), then maps each row to a
  product, collecting row errors.

### XML reader (`xml_reader.py`)

GMC feed XML only:
- Roots: rss → channel → item; atom → entry.
- Attribute tags: `g:`-namespaced or bare.
- Repeated sibling elements → arrays.
- Nested `g:shipping` / `g:tax` (and other structured elements) → structs.
- Malformed XML → run fails; an individual item that fails to parse → logged &
  skipped (row error with the item index).

### HttpFetcher (`fetch.py`)

```python
class HttpFetcher:
    async def fetch(self, url: str, basic_auth: tuple[str, str] | None = None) -> bytes: ...
```

- httpx async client, 60 s timeout.
- Streams the response; aborts once 500 MB is exceeded.
- Optional Basic Auth credentials from `FeedSource.configuration` (the JSONB
  column created in the M1 baseline migration — no new migration needed).
  Credentials are stored in plaintext JSONB for the MVP (see
  `docs/decisions.md`, "M3 Basic Auth credential storage").
- Fetch errors (timeout, non-2xx HTTP status, size limit, connection failure) →
  raise; the run fails with a clear message.
- Returns bytes; format selection is by `FeedSource.source_format`.

### RunState & IngestStep wiring

`StepContext` gains one field; it stays frozen:

```python
@dataclass(frozen=True)
class StepContext:
    feed_source_id: int
    session_factory: Callable[[], AsyncSession]
    logger: logging.Logger
    run_state: RunState

@dataclass
class RunState:
    products: list[dict[str, Any]] = field(default_factory=list)
```

`RunState` is the designated mutable channel between steps. `IngestStep`
populates `run_state.products`; later steps (plugins/staging in future
milestones) consume it. The M2 no-op steps ignore it. This is the only change
to the M2 step contract.

`PipelineRunner.execute` creates one `RunState` per run and passes it into every
`StepContext`. No other runner behavior changes.

`IngestStep` (replaces the no-op):
1. Load `FeedSource` (format, `source_url`, `configuration`). Missing feed
   source or missing `source_url` → raise; the run fails.
2. Fetch via `HttpFetcher` → parse via the reader for `source_format`.
3. Populate `run_state.products`.
4. Return `StepResult(processed_count=len(products), failed_count=len(row_errors),
   statistics={"row_errors": [...first 100, truncated...]})`.

Row errors surface in the existing run-history API via `IngestionRun.statistics`.

## Error handling

- Fetch failure → run fails (`status="error"`, message recorded by the runner).
- Header error → run fails with a clear message naming the offending column.
- Row error → logged, row skipped, run continues; count in `failed_count`.
- Missing `source_url` → run fails.
- Malformed XML document → run fails; a single bad item → row error, skipped.

## Testing

**Unit (no PostgreSQL):**
- `flat_notation`: header grammar (bare, annotated, repeated columns), value
  splitting (surplus colons → row error), registry sub-field subset validation,
  bare structured column → header error, unknown attribute kept generically.
- `delimited`: TSV/CSV/wide-TSV parse into the canonical model; comma-split
  repeated scalars; quoted commas; BOM tolerance; malformed rows skipped.
- `xml_reader`: rss + atom roots, `g:` namespace + bare tags, repeated siblings,
  nested shipping/tax structs, malformed XML fails, bad item skipped.
- `fetch`: timeout, size-limit abort, Basic Auth header, non-2xx raises — against
  a mock httpx transport.
- `IngestStep`: with a stub fetcher, populates run state and reports counts;
  missing `source_url` fails.

**Integration (PostgreSQL via `isolated_database_url`):**
- Runner with the real `IngestStep` + stub fetcher: products reach `run_state`,
  counts land in `IngestionRun`, row errors in `statistics`.

**Acceptance:**
- All four formats parse into the canonical model; malformed rows logged & skipped.
- Full backend suite green with Compose PostgreSQL.
- compileall clean.

## Dependencies

No new dependencies. httpx 0.28.1 is already pinned (M0).
