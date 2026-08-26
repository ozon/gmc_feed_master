# M4 Implementation Plan: Field Mapping (Auto + Manual)

**Date:** 2026-08-25
**Spec:** `docs/superpowers/specs/2026-08-25-m4-field-mapping-design.md`
**Base:** `main` at `5bfaa54`
**Execution:** isolated worktree `.worktrees/m4-field-mapping`, branch `m4-field-mapping` (create via `superpowers:using-git-worktrees` before Task 1)

## Conventions (read first)

- Backend lives in `backend/`; run commands from there with `uv run ...`
- Models: SQLAlchemy 2.x typed `Mapped[...]`/`mapped_column(...)`, `from app.db.base import Base`
- Tests: pytest + pytest-asyncio (`asyncio_mode` is not set — mark async tests `@pytest.mark.asyncio`); PostgreSQL-backed tests use the `isolated_database_url` fixture from `tests/conftest.py` (requires `TEST_DATABASE_URL` and Compose PostgreSQL running)
- Registry: `from registry.loader import load_registry` returns `RegistryDocument` with `.attributes: dict[str, RegistryAttribute]`; each `RegistryAttribute` has `.kind: AttributeKind`, `.fields: tuple[SubField, ...]`, `.required: RequirementStatus`, `.enum_values: tuple[str, ...]`
- `AttributeKind` values: `SCALAR`, `REPEATED_SCALAR`, `STRUCTURED`, `REPEATED_STRUCTURED` (str enum, `.value` gives `"scalar"` etc.)
- `FeedSource` model: `field_mapping: dict[str, Any]` (JSONB, default `{}`), `configuration: dict[str, Any]` (JSONB)
- Routes: `APIRouter`, session auth via `Depends(require_user)`, DB via `Depends(get_db_session)` returning `AsyncSession | None` (503 if None); see `app/routes/clients.py` for the established pattern
- Schemas: pydantic v2 in `app/schemas/`; `ConfigDict(from_attributes=True)` for ORM-backed models
- `StepContext` is a frozen dataclass; `DEFAULT_STEPS` in `steps.py` is a tuple of step instances built by `default_steps(fetcher, registry)`
- TDD: write failing test → implement → green → commit per task
- No comments in code unless required for clarity of a non-obvious decision

## File map

| File | Responsibility |
|---|---|
| `backend/app/ingest/report.py` | add `SourceField` dataclass + `source_fields` on `IngestReport` |
| `backend/app/ingest/delimited.py` | derive `source_fields` from header plan |
| `backend/app/ingest/xml_reader.py` | derive `source_fields` from item value shapes |
| `backend/app/pipeline/steps.py` | `RunState.source_fields`; `IngestStep` copies them; `MappingStep` |
| `backend/app/mapping/__init__.py` | package exports |
| `backend/app/mapping/document.py` | field_mapping JSONB document model + validation |
| `backend/app/mapping/matcher.py` | auto matcher (normalization + synonyms) |
| `backend/app/mapping/apply.py` | applies stored mapping to a canonical product |
| `backend/app/schemas/field_mapping.py` | request/response schemas for mapping + registry endpoints |
| `backend/app/routes/field_mapping.py` | GET/PUT `/feed-sources/{id}/field-mapping`, POST `.../auto` |
| `backend/app/routes/registry.py` | GET `/registry/attributes` |
| `backend/app/routes/__init__.py` | export new routers |
| `backend/app/main.py` | include new routers |
| `backend/tests/test_source_fields.py` | reader source-field observation tests |
| `backend/tests/test_mapping_document.py` | document model tests |
| `backend/tests/test_mapping_matcher.py` | auto matcher tests |
| `backend/tests/test_mapping_apply.py` | mapping application tests |
| `backend/tests/test_mapping_step.py` | MappingStep tests (stub session) |
| `backend/tests/test_field_mapping_api.py` | field-mapping API tests (PostgreSQL) |
| `backend/tests/test_registry_api.py` | registry API tests |
| `backend/tests/test_m4_acceptance.py` | end-to-end runner test (PostgreSQL) |

## Task 1: SourceField + report/run-state plumbing

**Goal:** Carry observed source fields from readers through `IngestReport` and `RunState`.

**Files:** `backend/app/ingest/report.py`, `backend/app/pipeline/steps.py`, `backend/tests/test_source_fields.py`

**Steps:**
1. RED: Write `tests/test_source_fields.py` with a test that `IngestReport()` has `source_fields == []` and that `RunState()` has `source_fields == []`. Import `SourceField` from `app.ingest.report`.
2. GREEN:
   - In `report.py`: add `@dataclass(frozen=True) class SourceField: name: str; kind: str; sub_fields: tuple[str, ...] = ()`. Add `source_fields: list[SourceField] = field(default_factory=list)` to `IngestReport`.
   - In `steps.py`: add `source_fields: list[SourceField] = field(default_factory=list)` to `RunState` (import `SourceField` from `..ingest.report`). In `IngestStep.execute`, after building the report, set `ctx.run_state.source_fields = list(report.source_fields)`.
3. Run: `uv run pytest tests/test_source_fields.py tests/test_ingest_step.py tests/test_pipeline_runner.py -x -q` → green (existing tests must not break).
4. Commit: `feat: SourceField dataclass and source_fields plumbing`

## Task 2: Readers populate source_fields

**Goal:** Delimited readers derive source fields from the header plan; XML reader infers from item value shapes.

**Files:** `backend/app/ingest/delimited.py`, `backend/app/ingest/xml_reader.py`, `backend/tests/test_source_fields.py`

**Steps:**
1. RED: Add tests:
   - Delimited (TSV): header `sku\ttitle\tshipping(country:price)` → `source_fields` = `[SourceField("sku", "generic", ()), SourceField("title", "scalar", ()), SourceField("shipping", "structured", ("country", "price"))]`. Note: unknown columns have kind `"generic"` in the header plan; map `"generic"` → `"scalar"` in the emitted `SourceField` (a bare unknown column holds a single string value).
   - Delimited (wide TSV): repeated structured columns → one `SourceField` with kind `"repeated_structured"` and the declared sub-fields.
   - XML: items `{"sku": "A", "images": ["a.jpg"], "shipping": {"country": "US"}}` → `SourceField("sku", "scalar", ())`, `SourceField("images", "repeated_scalar", ())`, `SourceField("shipping", "structured", ("country",))`.
   - XML shape conflict: first item `{"x": "a"}`, second `{"x": ["a", "b"]}` → `SourceField("x", "scalar", ())` (first-observed wins).
   - XML sub-fields: union of dict keys across items.
2. GREEN:
   - In `delimited.py`: after `parse_header`, build `source_fields` from `plan.columns`: `ColumnSpec.kind == "generic"` → `"scalar"`, else keep kind; `sub_fields=tuple(spec.sub_fields)`. Attach to the returned `IngestReport`.
   - In `xml_reader.py`: after parsing all items, walk the union of keys; infer kind from the first-observed value shape per key (`str` → scalar, `list[str]` → repeated_scalar, `dict` → structured, `list[dict]` → repeated_structured); sub-fields = union of dict keys for structured kinds. Attach to the returned `IngestReport`.
3. Run: `uv run pytest tests/test_source_fields.py tests/test_delimited_reader.py tests/test_xml_reader.py -x -q` → green.
4. Commit: `feat: readers emit observed source fields`

## Task 3: Mapping document model

**Goal:** Typed model + validation for the `field_mapping` JSONB document.

**Files:** `backend/app/mapping/__init__.py`, `backend/app/mapping/document.py`, `backend/tests/test_mapping_document.py`

**Steps:**
1. RED: Write tests for:
   - `MappingDocument.empty()` → `version=1, auto_mapped=False, source_fields=[], mappings={}`.
   - Round-trip: `MappingDocument.from_json({...})` then `.to_json()` preserves content.
   - `from_json({})` / `from_json(None)` → empty document (never-mapped).
   - Corrupt input (e.g. `{"mappings": "not-a-dict"}`) → raises `MappingDocumentError`.
   - `MappingEntry` has `target: str`, `origin: Literal["auto", "synonym", "manual"]`.
2. GREEN: Implement `document.py`:
   - `class MappingDocumentError(Exception)`.
   - `@dataclass class MappingEntry: target: str; origin: str`.
   - `@dataclass class MappingDocument: version: int = 1; auto_mapped: bool = False; source_fields: list[SourceField] = field(default_factory=list); mappings: dict[str, MappingEntry] = field(default_factory=dict)`.
   - `MappingDocument.empty()`, `.from_json(raw: Any)`, `.to_json() -> dict[str, Any]`.
   - `from_json` validates types; unknown keys ignored; missing keys defaulted.
   - `__init__.py`: export `MappingDocument`, `MappingEntry`, `MappingDocumentError`, `SourceField` (re-export from `app.ingest.report`).
3. Run: `uv run pytest tests/test_mapping_document.py -x -q` → green.
4. Commit: `feat: field_mapping document model`

## Task 4: Auto matcher

**Goal:** Suggest mappings from observed source fields against the registry.

**Files:** `backend/app/mapping/matcher.py`, `backend/tests/test_mapping_matcher.py`

**Steps:**
1. RED: Write tests for `auto_match(source_fields: list[SourceField], registry: RegistryDocument, existing: dict[str, MappingEntry] | None = None) -> dict[str, MappingEntry]`:
   - Exact match: `SourceField("title", "scalar")` → `{"title": MappingEntry("title", "auto")}`.
   - Normalized match: `SourceField("Product_Title", "scalar")` does NOT match `title` via normalization alone (normalization only strips separators/case: `product_title` ≠ `title`); but `SourceField("product-title", "scalar")` → matches `product_title`? No — registry has no `product_title`. Use a real registry attribute: `SourceField("Sale_Price", "scalar")` → matches `sale_price` → `MappingEntry("sale_price", "auto")`.
   - Synonym: `SourceField("ean", "scalar")` → `MappingEntry("gtin", "synonym")`.
   - Synonym list: `ean`/`upc`/`barcode`/`isbn` → `gtin`; `sku`/`item_id`/`item_number` → `id`; `product_title` → `title`; `product_url` → `link`; `image_url` → `image_link`; `additional_images` → `additional_image_link`.
   - Kind incompatibility: `SourceField("ean", "repeated_structured")` → no match (gtin is scalar).
   - Conflict: two sources both normalize to the same target → first in list wins, second unmapped.
   - Existing manual entries preserved: `existing={"sku": MappingEntry("id", "manual")}` and source field `sku` → result keeps the manual entry; auto/synonym recomputed for others; manual beats auto on target conflicts.
   - Unknown field: `SourceField("margin", "scalar")` → not in result.
2. GREEN: Implement `matcher.py`:
   - `_normalize(name: str) -> str`: lowercase, strip `_`, `-`, `.`, space.
   - `SYNONYMS: dict[str, str]` — the curated list above (keys normalized).
   - `auto_match(...)`: build registry lookup by normalized name; iterate source fields in order; for each, try exact/normalized match first, then synonym; check kind compatibility; check target not already claimed (manual > auto > synonym priority); emit `MappingEntry`.
   - Kind compatibility table per the design doc.
3. Run: `uv run pytest tests/test_mapping_matcher.py -x -q` → green.
4. Commit: `feat: auto mapper with normalization and synonyms`

## Task 5: Mapping application

**Goal:** Apply a stored mapping to a canonical product, producing a registry-only dict.

**Files:** `backend/app/mapping/apply.py`, `backend/tests/test_mapping_apply.py`

**Steps:**
1. RED: Write tests for `apply_mapping(product: dict[str, Any], mappings: dict[str, MappingEntry], registry: RegistryDocument) -> tuple[dict[str, Any], ApplyStats]` where `ApplyStats` is a dataclass with `dropped_unmapped: int` and `shape_mismatches: int`:
   - Scalar → scalar: `{"sku": "A"}` with `sku → id` → `{"id": "A"}`.
   - Scalar → sub-field: `{"months": "6"}` with `months → installment.months` → `{"installment": {"months": "6"}}`.
   - Scalar → repeated-scalar: `{"tag": "sale"}` with `tag → custom_label_0` where target is repeated-scalar → `{"custom_label_0": ["sale"]}`. (Use a real repeated-scalar registry attribute; check the registry for one, e.g. `additional_image_link`.)
   - List → repeated-scalar: `{"images": ["a.jpg", "b.jpg"]}` with `images → additional_image_link` → copied list.
   - Dict → structured: `{"ship": {"country": "US", "extra": "x"}}` with `ship → shipping` → `{"shipping": {"country": "US"}}` (unknown sub-field `extra` dropped).
   - Dict → repeated-structured: wraps in list.
   - List of dicts → repeated-structured: copied.
   - Shape mismatch: `{"images": ["a.jpg"]}` with `images → title` (scalar target) → field dropped, `shape_mismatches == 1`, result has no `title`.
   - Unmapped field: `{"margin": "10"}` with no mapping for `margin` → dropped, `dropped_unmapped == 1`.
   - Identity pass-through: `{"title": "Shirt"}` with `title → title` → `{"title": "Shirt"}`.
2. GREEN: Implement `apply.py` per the design doc's value-shape table. Parse target paths: split on `.` — one segment = attribute, two segments = attribute.subfield. Look up registry attribute for kind. Build result dict.
3. Run: `uv run pytest tests/test_mapping_apply.py -x -q` → green.
4. Commit: `feat: mapping application with shape rules`

## Task 6: MappingStep

**Goal:** Pipeline step that auto-maps on first ingestion, persists the document, and applies the mapping.

**Files:** `backend/app/pipeline/steps.py`, `backend/tests/test_mapping_step.py`

**Steps:**
1. RED: Write tests using a stub session factory (same pattern as `test_ingest_step.py`):
   - First ingestion: `FeedSource.field_mapping == {}`, `run_state.source_fields` populated → after execute, `feed_source.field_mapping` has `auto_mapped: true`, `source_fields`, and auto/synonym mappings; products in `run_state.products` are registry-only.
   - Second run: `field_mapping` has `auto_mapped: true` and a manual entry → manual entry preserved; `source_fields` refreshed; products mapped with manual mapping.
   - Corrupt document: `field_mapping = {"mappings": "bad"}` → raises `MappingDocumentError` (run fails).
   - Statistics: `result.statistics["mapping"]` has `applied`, `dropped_unmapped_fields`, `shape_mismatches`.
2. GREEN: Implement `MappingStep` in `steps.py`:
   - `name = "mapping"`.
   - `__init__(self, registry: RegistryDocument)`.
   - `execute`: load `FeedSource`; parse document (`MappingDocument.from_json`); if not `auto_mapped` → run `auto_match` against `ctx.run_state.source_fields`, set `auto_mapped = True`; else refresh `source_fields`. Persist `feed_source.field_mapping = doc.to_json()` and commit. Apply mapping to each product in `ctx.run_state.products` (replace in place). Return `StepResult` with counts.
   - Update `default_steps(fetcher, registry)` to insert `MappingStep(registry)` between `IngestStep` and the plugin no-op.
3. Run: `uv run pytest tests/test_mapping_step.py tests/test_pipeline_runner.py tests/test_m3_acceptance.py -x -q` → green.
4. Commit: `feat: MappingStep with first-ingestion auto-map`

## Task 7: Field-mapping API

**Goal:** GET/PUT `/feed-sources/{id}/field-mapping`, POST `.../auto`.

**Files:** `backend/app/schemas/field_mapping.py`, `backend/app/routes/field_mapping.py`, `backend/app/routes/__init__.py`, `backend/app/main.py`, `backend/tests/test_field_mapping_api.py`

**Steps:**
1. RED: Write API tests (PostgreSQL via `isolated_database_url`, same harness as `test_clients_api.py`):
   - GET on missing feed source → 404.
   - GET on never-ingested feed source → empty document shape.
   - PUT with valid mappings → 200, entries stored with `origin: manual`; `auto_mapped`/`source_fields` untouched.
   - PUT with invalid target path (unknown attribute) → 422 with `errors` list.
   - PUT with invalid sub-field → 422.
   - PUT with duplicate target across two sources → 422.
   - PUT with kind-incompatible mapping (known source field) → 422.
   - POST auto on never-ingested feed source → 422.
   - POST auto after seeding `source_fields` in the document → returns updated document; manual entries preserved.
   - Unauthenticated requests → 401.
2. GREEN:
   - `schemas/field_mapping.py`: `MappingEntryIn(BaseModel): target: str`; `FieldMappingPut(BaseModel): mappings: dict[str, MappingEntryIn]`; `SourceFieldOut`, `MappingEntryOut`, `FieldMappingOut` response models.
   - `routes/field_mapping.py`: three endpoints following the `clients.py` pattern. PUT validates against the registry (load via `load_registry()`); POST auto loads the document, requires non-empty `source_fields`, runs `auto_match` with existing manual entries, persists, returns.
   - Register router in `routes/__init__.py` and `main.py`.
3. Run: `uv run pytest tests/test_field_mapping_api.py -x -q` → green.
4. Commit: `feat: field-mapping API endpoints`

## Task 8: Registry API

**Goal:** GET `/registry/attributes` for the mapper UI.

**Files:** `backend/app/schemas/field_mapping.py`, `backend/app/routes/registry.py`, `backend/app/routes/__init__.py`, `backend/app/main.py`, `backend/tests/test_registry_api.py`

**Steps:**
1. RED: Write tests:
   - Unauthenticated → 401.
   - Authenticated → 200, list of objects with `name`, `kind`, `required`, `sub_fields` (list of `{name, type, required}`), `enum_values`.
   - Known attribute (e.g. `title`) present with `kind == "scalar"`.
   - Structured attribute (e.g. `installment`) has non-empty `sub_fields`.
2. GREEN: Implement `routes/registry.py`: load registry via `load_registry()`, serialize attributes. Add response schemas to `schemas/field_mapping.py`. Register router.
3. Run: `uv run pytest tests/test_registry_api.py -x -q` → green.
4. Commit: `feat: registry attributes API endpoint`

## Task 9: End-to-end integration

**Goal:** Full runner with real IngestStep + MappingStep produces registry-only products and persists the document.

**Files:** `backend/tests/test_m4_acceptance.py`

**Steps:**
1. RED: Write an acceptance test (PostgreSQL):
   - Create a client + feed source (TSV, stub fetcher serving a TSV with `sku`, `title`, `ean`, `margin` columns).
   - Run the pipeline via `PipelineRunner.execute`.
   - Assert: run status `completed`; `run_state` products contain `id` (from `sku` via synonym), `title`, `gtin` (from `ean` via synonym); `margin` absent.
   - Assert: `feed_source.field_mapping` has `auto_mapped: true`, `source_fields` listing all four columns, mappings for `sku`/`title`/`ean` but not `margin`.
   - PUT a manual mapping via the API (`margin` → some valid target is not possible since margin is unknown to registry; instead remap `sku` → `id` manually), re-run, assert manual mapping applied.
2. GREEN: Fix any wiring issues surfaced by the test.
3. Run: `uv run pytest tests/test_m4_acceptance.py -x -q` → green.
4. Commit: `feat: M4 end-to-end runner integration`

## Task 10: Acceptance gate

**Goal:** Full suite green, compileall clean, no regressions.

**Steps:**
1. Run: `uv run pytest -x -q` → all green.
2. Run: `uv run python -m compileall app alembic registry -q` → clean.
3. Run: `uv run pytest tests/test_m2_acceptance.py tests/test_m3_acceptance.py -x -q` → green (no regressions).
4. Commit (empty gate commit): `feat: M4 acceptance gate — field mapping verified`
