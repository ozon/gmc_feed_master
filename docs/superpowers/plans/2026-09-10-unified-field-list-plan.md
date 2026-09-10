# Unified Field List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared field-selection data source + `FieldSelect` component for Mapping, Rules, Filter, and Labelizer, with 1-based indexed access paths (`product_detail.2.section_name`), dynamic repeat counts, and correct XML reassembly on export.

**Architecture:** Backend first — `max_repeats` on `SourceField` flows from ingest through the mapping document to two unified-shape routes; a central `parse_indexed_path()` governs the `attr.N[.sub]` grammar used by mapping validation/apply and (duplicated locally, per plugin-isolation convention) the three plugins. Frontend second — `fieldOptions.ts` (adapters + `buildFieldOptions` + path regex) and `components/FieldSelect.tsx` (Combobox + InputBase), then all four consumers migrate to them, deleting their local option-building logic.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async (PostgreSQL), React 19, TypeScript, Mantine 9 (Combobox/InputBase), TanStack Query, vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-unified-field-list-design.md` (authoritative; includes operator directives 1-5).

## Global Constraints

- Tests run from `backend/` with `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres` set; never export `DATABASE_URL` while testing. Backend suite runs with `-n auto` by default (addopts).
- Frontend commands run from `frontend/`: `npm run test` (vitest), `npm run typecheck`, `npm run build`.
- Backend gates: `uv run ruff check .` (no new errors vs 506-baseline), `uv run mypy .` (exit-0, hard), full `uv run pytest`.
- Every task's commit also updates the documentation it affects (AGENTS.md rule). Decisions entries land in Task 11; per-task commits may include targeted doc lines where noted.
- **Directive 1:** registry `max_repeats` scan must select only the two JSON columns and stream with `yield_per=1000` — never load full model instances.
- **Directive 2:** sparse object lists must never render empty XML blocks — `[{}, {}, {"attribute_value": "Val"}]` renders exactly one non-empty `<g:product_detail>`.
- **Directive 3:** run-triggering mutations invalidate the `['registry', 'attributes']` query-key prefix.
- **Directive 4:** free-text input is validated client-side against `INDEXED_PATH_REGEX` (1-based) before submission; malformed input shows an inline message, never reaches the backend.
- **Directive 5:** indexed mapping targets coexist with whole/broadcast claims (kind-compatible); indexed assignments override broadcast values for their slot at apply time.
- 1-based indices everywhere in stored values/UI; only `parse_indexed_path` (and its plugin-local mirrors) translate to 0-based.
- `RuleValuesEditor.tsx` / `RuleCard.tsx` semantics untouched (mechanical shape adaptation only, Task 8).
- New i18n keys are added to **both** `frontend/public/locales/en/` and `frontend/public/locales/de/` files in the same task.
- Mantine Select cannot accept free text — `FieldSelect` must use `Combobox` + `InputBase` (verified against Mantine docs).

## Conventions used by every task

- Backend API test files copy the shared `app_factory`/`logged_in_client` fixture block from `backend/tests/test_registry_api.py:17-51` verbatim when a new test file needs it.
- RED step: write the test, run it, watch it fail for the right reason. GREEN step: implement, run, watch pass. Then commit with the exact message given.
- Run single backend test files with `uv run pytest tests/<file>.py -v` (add `-n0` if flaky under xdist).
- Frontend component tests render via `src/test/render.tsx` + `stubFetch` from `src/test/fetch.ts` (see `MappingTable.test.tsx:1-61`); call `queryClient.clear()` and `await i18n.loadNamespaces('<ns>')` in `beforeEach`.
- Commits use `git add <explicit paths> && git commit -m "<message>"` — never `git add -A`.

---

### Task 1: `max_repeats` on `SourceField` + XML reader

**Files:**
- Modify: `backend/app/ingest/report.py:13-17`
- Modify: `backend/app/ingest/xml_reader.py:89-126`
- Test: `backend/tests/test_source_fields.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SourceField(name, kind, sub_fields, max_repeats: int)` — `max_repeats` keyword or 4th positional arg, default `0`. Tasks 2-3 construct it; Task 3 serializes it.

- [ ] **Step 1: Write failing tests (RED)**

Add to `backend/tests/test_source_fields.py` inside `TestIngestReportSourceFields` (after `test_no_items_has_no_source_fields`):

```python
    def test_max_repeats_zero_for_scalar_and_structured(self) -> None:
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item><sku>A</sku><shipping><country>US</country></shipping></item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)
        assert report.source_fields == [
            SourceField("sku", "scalar", (), 0),
            SourceField("shipping", "structured", ("country",), 0),
        ]

    def test_max_repeats_largest_observed_list_length(self) -> None:
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item>"
            b"<images>a.jpg</images>"
            b"<shipping><country>US</country><price>1</price></shipping>"
            b"<shipping><country>UK</country><price>2</price></shipping>"
            b"<shipping><country>DE</country><price>3</price></shipping>"
            b"</item>"
            b"<item><images>a.jpg</images><images>b.jpg</images><images>c.jpg</images></item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)
        by_name = {sf.name: sf for sf in report.source_fields}
        assert by_name["shipping"].max_repeats == 3  # 3 shipping blocks in item 1
        assert by_name["images"].max_repeats == 3    # 3 images elements in item 2

    def test_max_repeats_union_regression_first_item_missing_keys(self) -> None:
        """Spec §2.1: union sub-fields — first item lacks keys later items have."""
        reg = _registry({})
        data = (
            b"<rss><channel>"
            b"<item><product_detail><section_name>General</section_name></product_detail></item>"
            b"<item>"
            b"<product_detail><section_name>General</section_name></product_detail>"
            b"<product_detail>"
            b"<section_name>General</section_name>"
            b"<attribute_name>Battery</attribute_name>"
            b"<attribute_value>5000 mAh</attribute_value>"
            b"</product_detail>"
            b"</item>"
            b"</channel></rss>"
        )
        report = parse_xml(data, reg)
        pd = next(sf for sf in report.source_fields if sf.name == "product_detail")
        assert pd.kind == "repeated_structured"
        assert list(pd.sub_fields) == ["section_name", "attribute_name", "attribute_value"]
        assert pd.max_repeats == 2
```

Do NOT touch the existing assertions that construct `SourceField` without `max_repeats` — they must keep passing (proves default-0 backward compatibility).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_source_fields.py -v -n0`
Expected: 3 FAIL (`TypeError: __init__() takes 3 positional arguments` or attribute assertion).

- [ ] **Step 3: Implement (GREEN)**

`backend/app/ingest/report.py` — replace the `SourceField` dataclass:

```python
@dataclass(frozen=True)
class SourceField:
    name: str
    kind: str
    sub_fields: tuple[str, ...] = ()
    max_repeats: int = 0
```

`backend/app/ingest/xml_reader.py` — replace `_infer_source_fields` (lines 89-126) with:

```python
def _infer_source_fields(products: list[dict[str, object]]) -> list[SourceField]:
    first_value: dict[str, object] = {}
    sub_field_order: dict[str, list[str]] = {}
    max_repeats: dict[str, int] = {}

    for product in products:
        for key, value in product.items():
            if key not in first_value:
                first_value[key] = value
            if isinstance(value, dict):
                seen = sub_field_order.setdefault(key, [])
                for sub_key in value:
                    if sub_key not in seen:
                        seen.append(sub_key)
            elif isinstance(value, list):
                if value:
                    max_repeats[key] = max(max_repeats.get(key, 0), len(value))
                for element in value:
                    if isinstance(element, dict):
                        seen = sub_field_order.setdefault(key, [])
                        for sub_key in element:
                            if sub_key not in seen:
                                seen.append(sub_key)

    fields: list[SourceField] = []
    for key, value in first_value.items():
        if isinstance(value, str):
            kind = "scalar"
        elif isinstance(value, dict):
            kind = "structured"
        elif isinstance(value, list):
            first = value[0] if value else None
            kind = "repeated_structured" if isinstance(first, dict) else "repeated_scalar"
        else:
            continue
        repeats = (
            max_repeats.get(key, 0)
            if kind in ("repeated_scalar", "repeated_structured")
            else 0
        )
        fields.append(
            SourceField(
                name=key,
                kind=kind,
                sub_fields=tuple(sub_field_order.get(key, [])),
                max_repeats=repeats,
            )
        )
    return fields
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_source_fields.py tests/test_xml_reader.py tests/test_mapping_document.py -v -n0`
Expected: all PASS (existing tests pass because `max_repeats` defaults to `0`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/report.py backend/app/ingest/xml_reader.py backend/tests/test_source_fields.py
git commit -m "feat: compute max_repeats on SourceField in XML reader with union regression test"
```

---

### Task 2: `max_repeats` in flat notation + delimited reader

**Files:**
- Modify: `backend/app/ingest/flat_notation.py:22-27` (ColumnSpec), `81-86` (repeated_structured finalize)
- Modify: `backend/app/ingest/delimited.py:43-66`
- Test: `backend/tests/test_delimited_reader.py`, `backend/tests/test_source_fields.py`

**Interfaces:**
- Consumes: `SourceField(..., max_repeats)` from Task 1.
- Produces: `ColumnSpec(name, kind, sub_fields, arity, max_repeats)`; `parse_delimited` emits `SourceField` with `max_repeats` = column arity for `repeated_structured`, max observed comma-split length for `repeated_scalar`, `0` otherwise.

- [ ] **Step 1: Write failing tests (RED)**

Add to `backend/tests/test_delimited_reader.py` inside `TestRepeatedScalar`:

```python
    def test_max_repeats_repeated_scalar(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "additional_image_link": _repeated_scalar("additional_image_link"),
        })
        data = (
            b"id\ttitle\tadditional_image_link\n"
            b"1\tA\timg1.jpg,img2.jpg,img3.jpg\n"
            b"2\tB\timg4.jpg\n"
        )
        report = parse_delimited(data, "tsv", reg)
        by_name = {sf.name: sf for sf in report.source_fields}
        assert by_name["additional_image_link"].max_repeats == 3
        assert by_name["id"].max_repeats == 0
```

Add to `backend/tests/test_source_fields.py` inside `TestIngestReportSourceFields` (next to `test_wide_tsv_repeated_structured_collapsed`):

```python
    def test_wide_tsv_max_repeats_from_column_arity(self) -> None:
        reg = _registry({
            "id": _scalar_attr("id"),
            "shipping": _repeated_structured_attr(
                "shipping",
                (
                    SubField("country", "String", RequirementStatus.REQUIRED),
                    SubField("price", "Price", RequirementStatus.OPTIONAL),
                ),
            ),
        })
        data = (
            b"id\tshipping(country:price)\tshipping(country:price)\tshipping(country:price)\n"
            b"1\tUS:6.49\tUK:5.99\tDE:5.49\n"
        )
        report = parse_delimited(data, "wide_tsv", reg)
        by_name = {sf.name: sf for sf in report.source_fields}
        assert by_name["shipping"].kind == "repeated_structured"
        assert by_name["shipping"].max_repeats == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_delimited_reader.py tests/test_source_fields.py -v -n0`
Expected: FAIL — `max_repeats` missing/0.

- [ ] **Step 3: Implement (GREEN)**

`backend/app/ingest/flat_notation.py` — extend `ColumnSpec` (lines 22-27):

```python
@dataclass(frozen=True)
class ColumnSpec:
    name: str
    kind: str
    sub_fields: list[str]
    arity: int = 1
    max_repeats: int = 0
```

In `parse_header`, only the `columns[-1] = ColumnSpec(...)` call for the repeated-structured finalize (lines 81-86) changes — add `max_repeats=prev + 1`:

```python
                columns[-1] = ColumnSpec(
                    name=existing.name,
                    kind=kind,
                    sub_fields=existing.sub_fields,
                    arity=prev + 1,
                    max_repeats=prev + 1,
                )
```

(All other `ColumnSpec` constructions keep the `0` default.)

`backend/app/ingest/delimited.py` — restructure `parse_delimited` (lines 43-66): move the product loop first, then compute repeated-scalar maxima, then build `source_fields`:

```python
    plan = parse_header(parsed[0][1], registry)

    products: list[dict] = []
    row_errors: list[RowError] = []

    for line, cells in parsed[1:]:
        product, error = split_row(cells, plan)
        if error is not None:
            row_errors.append(RowError(line=line, message=error.message))
        else:
            products.append(product)

    scalar_repeats: dict[str, int] = {}
    for spec in plan.columns:
        if spec.kind != "repeated_scalar":
            continue
        for product in products:
            value = product.get(spec.name)
            if isinstance(value, list):
                scalar_repeats[spec.name] = max(
                    scalar_repeats.get(spec.name, 0), len(value)
                )

    source_fields = [
        SourceField(
            name=spec.name,
            kind="scalar" if spec.kind == "generic" else spec.kind,
            sub_fields=tuple(spec.sub_fields),
            max_repeats=scalar_repeats.get(spec.name, spec.max_repeats),
        )
        for spec in plan.columns
    ]

    return IngestReport(
        products=products, row_errors=row_errors, source_fields=source_fields
    )
```

(Delete the old `source_fields = [...]` comprehension that sat before the product loop.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_delimited_reader.py tests/test_flat_notation.py tests/test_source_fields.py -v -n0`
Expected: all PASS, including every pre-existing flat-notation/delimited test (proves default-0 compatibility).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/flat_notation.py backend/app/ingest/delimited.py backend/tests/test_delimited_reader.py backend/tests/test_source_fields.py
git commit -m "feat: carry max_repeats through flat notation and delimited reader"
```

---

### Task 3: Mapping document + schemas + registry route (`max_repeats`)

**Files:**
- Modify: `backend/app/mapping/document.py:57-73` (to_json), `76-105` (`_parse_source_fields`)
- Modify: `backend/app/schemas/field_mapping.py:14-19` (SourceFieldOut), `36-48` (RegistrySubFieldOut, RegistryAttributeOut)
- Modify: `backend/app/routes/registry.py` (full rewrite)
- Test: `backend/tests/test_mapping_document.py`, `backend/tests/test_registry_api.py`

**Interfaces:**
- Consumes: `SourceField.max_repeats` (Task 1).
- Produces:
  - `MappingDocument` JSON carries `max_repeats` per source field (tolerant read: absent → 0).
  - `SourceFieldOut` pydantic model with `max_repeats: int = 0`.
  - `GET /registry/attributes?feed_source_id=N` → each item gains `max_repeats: int`; each `sub_fields[i]` gains `kind: str | None`. Without the param: repeated attributes report `max_repeats=0`, scalar/structured report `1`.
  - `compute_max_repeats(session, feed_source_id) -> dict[str, int]` in `backend/app/routes/registry.py`.

- [ ] **Step 1: Write failing tests (RED)**

Add to `backend/tests/test_mapping_document.py` (keep its existing import of `MappingDocument`; add only if absent):

```python
def test_roundtrip_max_repeats():
    doc = MappingDocument.from_json({
        "version": 1,
        "auto_mapped": False,
        "source_fields": [
            {"name": "shipping", "kind": "repeated_structured",
             "sub_fields": ["country", "price"], "max_repeats": 3},
            {"name": "title", "kind": "scalar", "sub_fields": []},
        ],
        "mappings": {},
    })
    assert doc.source_fields[0].max_repeats == 3
    assert doc.source_fields[1].max_repeats == 0  # tolerant default
    out = doc.to_json()
    assert out["source_fields"][0]["max_repeats"] == 3
    assert out["source_fields"][1]["max_repeats"] == 0
```

Add to `backend/tests/test_registry_api.py`:

```python
async def test_registry_attributes_without_feed_source_max_repeats_zero(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes")
    body = resp.json()
    pd = next(a for a in body if a["name"] == "product_detail")
    assert pd["max_repeats"] == 0
    assert pd["sub_fields"][0]["kind"] == "repeated_scalar"


async def test_registry_attributes_with_feed_source_derives_max_repeats(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    from datetime import datetime, timezone
    from app.models.staging import StagingProduct
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(
        f"/clients/{created['id']}/feed-sources",
        json={"name": "DE", "source_format": "xml"},
    )).json()
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed["id"], status="success",
                               started_at=datetime.now(timezone.utc))
            session.add(run)
            await session.flush()
            session.add(StagingProduct(
                feed_source_id=feed["id"], ingestion_run_id=run.id,
                product_id="a", content_hash="h", config_hash="c",
                status="active", raw_data={"id": "a"},
                processed_data={
                    "id": "a",
                    "product_detail": [
                        {"section_name": "General", "attribute_name": "Battery",
                         "attribute_value": "5000 mAh"},
                        {"section_name": "General", "attribute_name": "Color",
                         "attribute_value": "Blue"},
                        {"section_name": "Extra"},
                    ],
                    "additional_image_link": ["x.jpg", "y.jpg"],
                }, excluded=False,
            ))
            session.add(StagingProduct(
                feed_source_id=feed["id"], ingestion_run_id=run.id,
                product_id="b", content_hash="h", config_hash="c",
                status="active", raw_data={"id": "b", "brand": "RawBrand"},
                processed_data=None, excluded=False,
            ))
    resp = await client.get(f"/registry/attributes?feed_source_id={feed['id']}")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {a["name"]: a for a in body}
    assert by_name["product_detail"]["max_repeats"] == 3
    assert by_name["additional_image_link"]["max_repeats"] == 2
    assert by_name["id"]["max_repeats"] == 1            # scalar -> 1
    assert by_name["installment"]["max_repeats"] == 1    # structured -> 1


async def test_registry_attributes_unknown_feed_source_404(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes?feed_source_id=99999")
    assert resp.status_code == 404
```

Update the existing shape assertion in `test_registry_attributes_returns_list_with_expected_shape` (line 68) to the new per-item key set:

```python
    assert set(item.keys()) == {
        "name", "kind", "required", "sub_fields", "enum_values",
        "baseline_required", "max_repeats",
    }
```

and extend its sub-field loop (keep other assertions intact; read the test first):

```python
    for sub in item["sub_fields"]:
        assert "kind" in sub
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mapping_document.py tests/test_registry_api.py -v -n0`
Expected: FAIL — `max_repeats` missing from document JSON and registry response; sub `kind` absent.

- [ ] **Step 3: Implement (GREEN)**

`backend/app/mapping/document.py` — in `to_json` (lines 61-68), add the key:

```python
            "source_fields": [
                {
                    "name": sf.name,
                    "kind": sf.kind,
                    "sub_fields": list(sf.sub_fields),
                    "max_repeats": sf.max_repeats,
                }
                for sf in self.source_fields
            ],
```

In `_parse_source_fields`, replace the final `result.append(...)` (line 104) with a validated version:

```python
        max_repeats = item.get("max_repeats", 0)
        if (
            not isinstance(max_repeats, int)
            or isinstance(max_repeats, bool)
            or max_repeats < 0
        ):
            raise MappingDocumentError(
                f"source field 'max_repeats' must be a non-negative int for {name!r}"
            )
        result.append(
            SourceField(
                name=name,
                kind=kind,
                sub_fields=tuple(sub_fields),
                max_repeats=max_repeats,
            )
        )
```

`backend/app/schemas/field_mapping.py` — three changes:

```python
class SourceFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    kind: str
    sub_fields: list[str]
    max_repeats: int = 0
```

```python
class RegistrySubFieldOut(BaseModel):
    name: str
    type: str
    required: str
    kind: str | None = None
```

```python
class RegistryAttributeOut(BaseModel):
    name: str
    kind: str
    required: str
    baseline_required: bool
    sub_fields: list[RegistrySubFieldOut]
    enum_values: list[str]
    max_repeats: int = 0
```

`backend/app/routes/registry.py` — full replacement:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.loader import load_registry

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource
from ..models.staging import StagingProduct
from ..qc.constants import BASELINE_ALTERNATIVE_PAIRS, BASELINE_REQUIRED
from ..schemas.field_mapping import RegistryAttributeOut, RegistrySubFieldOut

router = APIRouter()


def _attribute_sub_kind(parent_kind: str) -> str | None:
    """Sub-field effective kind, mirroring matcher._SUB_EFFECTIVE_KINDS."""
    if parent_kind == "structured":
        return "scalar"
    if parent_kind == "repeated_structured":
        return "repeated_scalar"
    return None


async def _require_feed_source(session: AsyncSession, feed_source_id: int) -> None:
    if await session.get(FeedSource, feed_source_id) is None:
        raise HTTPException(status_code=404, detail="feed source not found")


async def compute_max_repeats(
    session: AsyncSession, feed_source_id: int
) -> dict[str, int]:
    """Max observed list length per attribute (operator directive 1).

    Streams only the two JSON columns with yield_per — never full model
    instances. processed_data falls back to raw_data when null (QC precedent).
    """
    result: dict[str, int] = {}
    stmt = (
        select(StagingProduct.processed_data, StagingProduct.raw_data)
        .where(StagingProduct.feed_source_id == feed_source_id)
        .execution_options(yield_per=1000)
    )
    stream = await session.stream(stmt)
    async for processed_data, raw_data in stream:
        product = processed_data if processed_data is not None else (raw_data or {})
        if not isinstance(product, dict):
            continue
        for key, value in product.items():
            if isinstance(value, list) and value:
                result[key] = max(result.get(key, 0), len(value))
    return result


@router.get("/registry/attributes", response_model=list[RegistryAttributeOut])
async def list_registry_attributes(
    feed_source_id: int | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[RegistryAttributeOut]:
    registry = load_registry()
    baseline_names = set(BASELINE_REQUIRED)
    for pair in BASELINE_ALTERNATIVE_PAIRS:
        baseline_names.update(pair)

    observed: dict[str, int] = {}
    if feed_source_id is not None:
        if db_session is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        async with db_session.begin():
            await _require_feed_source(db_session, feed_source_id)
            observed = await compute_max_repeats(db_session, feed_source_id)

    attributes: list[RegistryAttributeOut] = []
    for attribute in sorted(registry.attributes.values(), key=lambda attr: attr.name):
        kind = attribute.kind.value
        if kind in ("repeated_scalar", "repeated_structured"):
            max_repeats = observed.get(attribute.name, 0)
        else:
            max_repeats = 1
        attributes.append(
            RegistryAttributeOut(
                name=attribute.name,
                kind=kind,
                required=attribute.required.value,
                baseline_required=attribute.name in baseline_names,
                sub_fields=[
                    RegistrySubFieldOut(
                        name=sub.name,
                        type=sub.type,
                        required=sub.required.value,
                        kind=_attribute_sub_kind(kind),
                    )
                    for sub in attribute.fields
                ],
                enum_values=list(attribute.enum_values),
                max_repeats=max_repeats,
            )
        )
    return attributes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mapping_document.py tests/test_registry_api.py tests/test_field_mapping_api.py -v -n0`
Expected: all PASS.

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check app/routes/registry.py app/mapping/document.py app/schemas/field_mapping.py && uv run mypy app/routes/registry.py app/mapping/document.py app/schemas/field_mapping.py`
Expected: no errors (registry.py is a fresh write — must be clean).

- [ ] **Step 6: Commit**

```bash
git add backend/app/mapping/document.py backend/app/schemas/field_mapping.py backend/app/routes/registry.py backend/tests/test_mapping_document.py backend/tests/test_registry_api.py
git commit -m "feat: max_repeats through mapping document, schemas, and registry route (per-request derivation)"
```

---

### Task 4: `parse_indexed_path` utility + unit tests

**Files:**
- Create: `backend/app/mapping/indexed_path.py`
- Modify: `backend/app/mapping/__init__.py` (add export)
- Test: `backend/tests/test_indexed_path.py` (new)

**Interfaces:**
- Produces (used by Tasks 5, 6, 7):

```python
@dataclass(frozen=True)
class IndexedPath:
    attr: str
    index: int | None  # 1-based
    sub: str | None

def parse_indexed_path(path: str) -> IndexedPath
```

Semantics: `attr` → (attr, None, None); `attr.sub` → (attr, None, sub) (broadcast); `attr.N` → (attr, N, None); `attr.N.sub` → (attr, N, sub). Digits-only second segment ⇒ index. Index `0` → `ValueError` (1-based). Negative or more than 3 segments → `ValueError`. Empty attr → `ValueError`.

- [ ] **Step 1: Write failing tests (RED)**

Create `backend/tests/test_indexed_path.py`:

```python
import pytest

from app.mapping.indexed_path import IndexedPath, parse_indexed_path


@pytest.mark.parametrize("path,expected", [
    ("title", IndexedPath("title", None, None)),
    ("shipping.price", IndexedPath("shipping", None, "price")),
    ("additional_image_link.3", IndexedPath("additional_image_link", 3, None)),
    ("product_detail.2.attribute_value",
     IndexedPath("product_detail", 2, "attribute_value")),
])
def test_parse(path, expected):
    assert parse_indexed_path(path) == expected


def test_zero_index_rejected():
    with pytest.raises(ValueError, match="1-based"):
        parse_indexed_path("product_detail.0.attribute_name")


def test_negative_index_rejected():
    with pytest.raises(ValueError):
        parse_indexed_path("additional_image_link.-2")


def test_too_many_segments_rejected():
    with pytest.raises(ValueError):
        parse_indexed_path("a.b.c.d")


def test_empty_attr_rejected():
    with pytest.raises(ValueError):
        parse_indexed_path(".price")
    with pytest.raises(ValueError):
        parse_indexed_path("")


def test_index_is_1_based_in_storage_grammar():
    p = parse_indexed_path("product_detail.1.section_name")
    assert p.index == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_indexed_path.py -v -n0`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mapping.indexed_path'`.

- [ ] **Step 3: Implement (GREEN)**

Create `backend/app/mapping/indexed_path.py`:

```python
"""Central authority for the 1-based indexed path grammar.

Grammar: attr | attr.sub | attr.N | attr.N.sub  (N >= 1)

QC finding paths (additional_image_link.1) already use this grammar. UI and
stored values are always 1-based; translation to 0-based array indices
happens only in consumers of IndexedPath.index, never in the stored string.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexedPath:
    attr: str
    index: int | None  # 1-based
    sub: str | None


def parse_indexed_path(path: str) -> IndexedPath:
    parts = path.split(".")
    if not parts or not parts[0]:
        raise ValueError(f"invalid indexed path {path!r}: empty attribute")
    attr = parts[0]
    if len(parts) > 3:
        raise ValueError(f"invalid indexed path {path!r}: at most 3 segments")
    if len(parts) == 1:
        return IndexedPath(attr=attr, index=None, sub=None)

    second = parts[1]
    index: int | None = None
    sub: str | None = None
    if second.isdigit():
        index = int(second)
        if index < 1:
            raise ValueError(f"invalid index in {path!r}: indices are 1-based")
        if len(parts) == 3:
            sub = parts[2]
            if not sub:
                raise ValueError(f"invalid indexed path {path!r}: empty sub-field")
    else:
        if len(parts) == 3:
            raise ValueError(
                f"invalid indexed path {path!r}: at most attr.sub or attr.N.sub"
            )
        if not second:
            raise ValueError(f"invalid indexed path {path!r}: empty sub-field")
        sub = second
    if index is None and second.startswith("-"):
        raise ValueError(f"invalid index in {path!r}: indices are 1-based")
    return IndexedPath(attr=attr, index=index, sub=sub)
```

`backend/app/mapping/__init__.py` — add to the imports and `__all__`:

```python
from .indexed_path import IndexedPath, parse_indexed_path
```

```python
__all__ = [
    "ApplyStats",
    "IndexedPath",
    "MappingDocument",
    "MappingDocumentError",
    "MappingEntry",
    "SourceField",
    "apply_mapping",
    "auto_match",
    "parse_indexed_path",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_indexed_path.py -v -n0`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/mapping/indexed_path.py backend/app/mapping/__init__.py backend/tests/test_indexed_path.py
git commit -m "feat: central 1-based indexed path parser for attr.N[.sub] grammar"
```

---

### Task 5: Mapping validation + apply reassembly for indexed targets (+ directives 2 & 5)

**Files:**
- Modify: `backend/app/routes/field_mapping.py:39-122` (`_validate_mappings`)
- Modify: `backend/app/mapping/apply.py` (whole file)
- Test: `backend/tests/test_mapping_apply.py`, `backend/tests/test_field_mapping_api.py`, `backend/tests/test_export_renderer.py`

**Interfaces:**
- Consumes: `parse_indexed_path`/`IndexedPath` (Task 4).
- Produces: target grammar `attr | attr.sub | attr.N | attr.N.sub` (indexed only on `repeated_*` registry kinds); apply-time slot-merge where indexed assignments override broadcast/whole values for their exact slot. Deterministic order: non-indexed mappings in dict order first, then indexed mappings sorted by target.

- [ ] **Step 1: Write failing tests (RED)**

Add to `backend/tests/test_mapping_apply.py`:

```python
def test_indexed_repeated_scalar_target_sets_element():
    product = {"img_a": "a.jpg", "img_b": "b.jpg"}
    result, stats = apply_mapping(
        product,
        {"img_a": MappingEntry("additional_image_link.1", "manual"),
         "img_b": MappingEntry("additional_image_link.2", "manual")},
        registry,
    )
    assert result == {"additional_image_link": ["a.jpg", "b.jpg"]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_indexed_repeated_structured_target_sets_slot():
    product = {"sn": "General", "an": "Battery", "av": "5000 mAh"}
    result, stats = apply_mapping(
        product,
        {"sn": MappingEntry("product_detail.1.section_name", "manual"),
         "an": MappingEntry("product_detail.1.attribute_name", "manual"),
         "av": MappingEntry("product_detail.1.attribute_value", "manual")},
        registry,
    )
    assert result == {"product_detail": [
        {"section_name": "General", "attribute_name": "Battery",
         "attribute_value": "5000 mAh"},
    ]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_indexed_sparse_auto_extends():
    product = {"sn": "General"}
    result, stats = apply_mapping(
        product,
        {"sn": MappingEntry("product_detail.3.section_name", "manual")},
        registry,
    )
    assert result == {"product_detail": [{}, {}, {"section_name": "General"}]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_indexed_overrides_broadcast_slot():
    """Operator directive 5: indexed assignment beats broadcast for its slot."""
    product = {
        "images": ["a.jpg", "b.jpg", "c.jpg"],
        "first_image": "OVERRIDE.jpg",
    }
    result, stats = apply_mapping(
        product,
        {"images": MappingEntry("additional_image_link", "manual"),
         "first_image": MappingEntry("additional_image_link.1", "manual")},
        registry,
    )
    assert result == {"additional_image_link": ["OVERRIDE.jpg", "b.jpg", "c.jpg"]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_indexed_sub_overrides_broadcast_sub_slot():
    product = {
        "details": [
            {"section_name": "S1", "attribute_name": "A1", "attribute_value": "V1"},
            {"section_name": "S2", "attribute_name": "A2", "attribute_value": "V2"},
        ],
        "override_value": "NEW",
    }
    result, stats = apply_mapping(
        product,
        {"details": MappingEntry("product_detail", "manual"),
         "override_value": MappingEntry("product_detail.2.attribute_value", "manual")},
        registry,
    )
    assert result == {"product_detail": [
        {"section_name": "S1", "attribute_name": "A1", "attribute_value": "V1"},
        {"section_name": "S2", "attribute_name": "A2", "attribute_value": "NEW"},
    ]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_indexed_target_on_scalar_kind_shape_mismatch():
    product = {"x": "value"}
    result, stats = apply_mapping(
        product, {"x": MappingEntry("title.1", "manual")}, registry,
    )
    assert result == {}
    assert stats.shape_mismatches == 1
```

Extend the `source_field` helper in `backend/tests/test_field_mapping_api.py` (line 70-71) with a 4th arg:

```python
def source_field(name, kind, sub_fields=(), max_repeats=0):
    return {"name": name, "kind": kind, "sub_fields": list(sub_fields),
            "max_repeats": max_repeats}
```

Add to `backend/tests/test_field_mapping_api.py`:

```python
async def test_put_indexed_target_on_repeated_accepted(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await create_feed_source(client)
    await seed_field_mapping(factory, feed_id, {
        "version": 1, "auto_mapped": False,
        "source_fields": [
            source_field("sn", "scalar"),
            source_field("pd", "repeated_structured",
                         ["section_name", "attribute_name", "attribute_value"]),
        ],
        "mappings": {},
    })
    resp = await client.put(f"/feed-sources/{feed_id}/field-mapping", json={
        "mappings": {
            "sn": {"target": "product_detail.1.section_name"},
        },
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["mappings"]["sn"]["target"] == "product_detail.1.section_name"


async def test_put_indexed_target_on_scalar_rejected_422(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await create_feed_source(client)
    await seed_field_mapping(factory, feed_id, {
        "version": 1, "auto_mapped": False,
        "source_fields": [source_field("t", "scalar")],
        "mappings": {},
    })
    resp = await client.put(f"/feed-sources/{feed_id}/field-mapping", json={
        "mappings": {"t": {"target": "title.1"}},
    })
    assert resp.status_code == 422
    assert any("repeated" in e for e in resp.json()["errors"])


async def test_put_indexed_coexists_with_whole_claim(app_factory):
    """Operator directive 5: whole claim + indexed claim on same attr coexist."""
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await create_feed_source(client)
    await seed_field_mapping(factory, feed_id, {
        "version": 1, "auto_mapped": False,
        "source_fields": [
            source_field("images", "repeated_scalar"),
            source_field("hero", "scalar"),
        ],
        "mappings": {},
    })
    resp = await client.put(f"/feed-sources/{feed_id}/field-mapping", json={
        "mappings": {
            "images": {"target": "additional_image_link"},
            "hero": {"target": "additional_image_link.1"},
        },
    })
    assert resp.status_code == 200
    assert resp.json()["mappings"]["hero"]["target"] == "additional_image_link.1"


async def test_put_indexed_duplicate_target_still_rejected(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await create_feed_source(client)
    await seed_field_mapping(factory, feed_id, {
        "version": 1, "auto_mapped": False,
        "source_fields": [
            source_field("a", "scalar"),
            source_field("b", "scalar"),
        ],
        "mappings": {},
    })
    resp = await client.put(f"/feed-sources/{feed_id}/field-mapping", json={
        "mappings": {
            "a": {"target": "product_detail.1.section_name"},
            "b": {"target": "product_detail.1.section_name"},
        },
    })
    assert resp.status_code == 422
    assert any("already claimed" in e for e in resp.json()["errors"])
```

Add to `backend/tests/test_export_renderer.py` (directive 2 + golden XML):

```python
def test_sparse_product_detail_renders_only_non_empty_blocks():
    registry = load_registry()
    product = {
        "id": "1",
        "product_detail": [{}, {}, {"attribute_value": "Val"}],
    }
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert text.count("<g:product_detail>") == 1
    assert "<g:attribute_value>Val</g:attribute_value>" in text
    assert "<g:product_detail></g:product_detail>" not in text


def test_golden_indexed_mapping_end_to_end():
    """apply_mapping with indexed targets -> clean structured XML."""
    from app.mapping import MappingEntry, apply_mapping
    product = {
        "sn1": "General", "an1": "Battery", "av1": "5000 mAh",
        "sn2": "General", "an2": "Color", "av2": "Blue",
        "img": ["x.jpg", "y.jpg", "z.jpg"],
    }
    mappings = {
        "sn1": MappingEntry("product_detail.1.section_name", "manual"),
        "an1": MappingEntry("product_detail.1.attribute_name", "manual"),
        "av1": MappingEntry("product_detail.1.attribute_value", "manual"),
        "sn2": MappingEntry("product_detail.2.section_name", "manual"),
        "an2": MappingEntry("product_detail.2.attribute_name", "manual"),
        "av2": MappingEntry("product_detail.2.attribute_value", "manual"),
        "img": MappingEntry("additional_image_link", "manual"),
    }
    mapped, stats = apply_mapping(product, mappings, registry)
    assert stats.shape_mismatches == 0
    text = render_feed([mapped], registry, CHANNEL).decode("utf-8")
    assert text.count("<g:product_detail>") == 2
    assert ("<g:product_detail><g:section_name>General</g:section_name>"
            "<g:attribute_name>Battery</g:attribute_name>"
            "<g:attribute_value>5000 mAh</g:attribute_value></g:product_detail>"
            ) in text
    assert ("<g:product_detail><g:section_name>General</g:section_name>"
            "<g:attribute_name>Color</g:attribute_name>"
            "<g:attribute_value>Blue</g:attribute_value></g:product_detail>"
            ) in text
    assert "<g:additional_image_link>x.jpg</g:additional_image_link>" in text
    assert "<g:additional_image_link>y.jpg</g:additional_image_link>" in text
    assert "<g:additional_image_link>z.jpg</g:additional_image_link>" in text
```

Before finalizing the golden strings, verify the registry sub-field order of `product_detail` in `backend/registry/attributes.json` (section_name → attribute_name → attribute_value) — the renderer emits registry order; adjust the expected strings if it differs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mapping_apply.py tests/test_field_mapping_api.py tests/test_export_renderer.py -v -n0`
Expected: new apply tests FAIL (indexed targets unresolved); API tests FAIL with 422 (today `>2` segments rejected); golden XML FAIL (nothing rendered from indexed targets).

- [ ] **Step 3: Implement validation (GREEN part 1)**

`backend/app/routes/field_mapping.py` — add the import:

```python
from ..mapping.indexed_path import parse_indexed_path
```

Replace the body of the inner `check_target` (currently lines 48-90) with:

```python
    def check_target(source: str, target: str, source_kind: str | None) -> None:
        try:
            parsed = parse_indexed_path(target)
        except ValueError:
            errors.append(f"{source}: invalid target path {target!r}")
            return
        attribute = registry.attributes.get(parsed.attr)
        if attribute is None:
            errors.append(f"{source}: unknown attribute {parsed.attr!r}")
            return
        attr_kind = attribute.kind.value
        known_subs = {sub.name for sub in attribute.fields}

        if parsed.index is not None:
            if attr_kind not in ("repeated_scalar", "repeated_structured"):
                errors.append(
                    f"{source}: indexed target {target!r} requires a repeated attribute"
                )
                return
            if parsed.sub is not None:
                if attr_kind != "repeated_structured":
                    errors.append(
                        f"{source}: indexed sub target {target!r} requires a "
                        "repeated_structured attribute"
                    )
                    return
                if parsed.sub not in known_subs:
                    errors.append(
                        f"{source}: unknown sub-field {parsed.sub!r} on {parsed.attr!r}"
                    )
                    return
        elif parsed.sub is not None:
            if attr_kind not in _STRUCTURED_KINDS:
                errors.append(f"{source}: {parsed.attr!r} has no sub-fields")
                return
            if parsed.sub not in known_subs:
                errors.append(
                    f"{source}: unknown sub-field {parsed.sub!r} on {parsed.attr!r}"
                )
                return
        else:
            if (
                source_kind is not None
                and attr_kind not in _COMPATIBLE_KINDS.get(source_kind, frozenset())
            ):
                errors.append(
                    f"{source}: kind {source_kind!r} incompatible with "
                    f"{attr_kind!r} target {target!r}"
                )
                return

        # Overlap policy (operator directive 5): indexed targets never claim
        # the whole attribute and never block other claims; whole/broadcast
        # claims never block indexed sub-slots. Only exact duplicates block.
        if parsed.index is None and parsed.sub is not None:
            if parsed.attr in claimed:
                errors.append(
                    f"{source}: target {target!r} overlaps claim on "
                    f"{parsed.attr!r} by {claimed[parsed.attr]!r}"
                )
                return
        if parsed.index is None and parsed.sub is None:
            for claimed_target, claimed_by in claimed.items():
                if "." not in claimed_target:
                    continue
                try:
                    claimed_parsed = parse_indexed_path(claimed_target)
                except ValueError:
                    continue
                if claimed_parsed.index is not None:
                    continue  # directive 5: indexed claims never block whole claims
                if claimed_target.startswith(f"{parsed.attr}."):
                    errors.append(
                        f"{source}: target {target!r} overlaps claim on "
                        f"{claimed_target!r} by {claimed_by!r}"
                    )
                    return
        if target in claimed:
            errors.append(
                f"{source}: target {target!r} already claimed by {claimed[target]!r}"
            )
            return
        claimed[target] = source
```

The source-side loop below `check_target` (whole-source vs sub-source exclusivity, lines 92-121) is unchanged — source keys never contain indices.

- [ ] **Step 4: Implement apply (GREEN part 2)**

`backend/app/mapping/apply.py` — add the import:

```python
from .indexed_path import IndexedPath, parse_indexed_path
```

Add `_set_indexed` above `_apply_entry`:

```python
def _set_indexed(
    result: dict[str, Any],
    parsed: IndexedPath,
    value: str,
) -> bool:
    """Write value into attr[N-1][sub] (N is 1-based); True on success."""
    idx0 = parsed.index - 1
    if parsed.sub is None:
        bucket = result.get(parsed.attr)
        if not isinstance(bucket, list):
            bucket = []
            result[parsed.attr] = bucket
        while len(bucket) <= idx0:
            bucket.append("")
        if not isinstance(value, str):
            return False
        bucket[idx0] = value
        return True
    bucket = result.get(parsed.attr)
    if not isinstance(bucket, list):
        bucket = []
        result[parsed.attr] = bucket
    while len(bucket) <= idx0:
        bucket.append({})
    if not isinstance(bucket[idx0], dict):
        return False
    bucket[idx0][parsed.sub] = value
    return True
```

Replace `_apply_entry` with:

```python
def _apply_entry(
    result: dict[str, Any],
    source: str,
    value: Any,
    entry: MappingEntry,
    registry: RegistryDocument,
    stats: ApplyStats,
) -> None:
    try:
        parsed = parse_indexed_path(entry.target)
    except ValueError:
        stats.shape_mismatches += 1
        return
    attribute = registry.attributes.get(parsed.attr)
    if attribute is None:
        stats.shape_mismatches += 1
        return
    kind = attribute.kind

    if parsed.index is not None:
        if kind not in (AttributeKind.REPEATED_SCALAR, AttributeKind.REPEATED_STRUCTURED):
            stats.shape_mismatches += 1
            return
        if parsed.sub is not None and kind is not AttributeKind.REPEATED_STRUCTURED:
            stats.shape_mismatches += 1
            return
        if not isinstance(value, str):
            stats.shape_mismatches += 1
            return
        if not _set_indexed(result, parsed, value):
            stats.shape_mismatches += 1
        return

    attr_name, subfield = parsed.attr, parsed.sub
    if subfield:
        if kind.value not in ("structured", "repeated_structured"):
            stats.shape_mismatches += 1
            return
        if isinstance(value, str):
            if kind is AttributeKind.STRUCTURED:
                bucket = result.setdefault(attr_name, {})
                if isinstance(bucket, dict):
                    bucket[subfield] = value
                return
            bucket = result.get(attr_name)
            if not isinstance(bucket, list):
                bucket = []
                result[attr_name] = bucket
            if not bucket:
                bucket.append({})
            bucket[0][subfield] = value
            return
        if isinstance(value, list):
            if kind is AttributeKind.STRUCTURED:
                if len(value) == 1:
                    bucket = result.setdefault(attr_name, {})
                    if isinstance(bucket, dict):
                        bucket[subfield] = value[0]
                    return
                stats.shape_mismatches += 1
                return
            _merge_elementwise(result, attr_name, subfield, value)
            return
        stats.shape_mismatches += 1
        return

    if kind is AttributeKind.SCALAR:
        if isinstance(value, str):
            result[attr_name] = value
        else:
            stats.shape_mismatches += 1
    elif kind is AttributeKind.REPEATED_SCALAR:
        if isinstance(value, str):
            result[attr_name] = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            result[attr_name] = [item for item in value if item != ""]
        else:
            stats.shape_mismatches += 1
    elif kind is AttributeKind.STRUCTURED:
        if isinstance(value, dict):
            known = {field.name for field in attribute.fields}
            result[attr_name] = {k: v for k, v in value.items() if k in known}
        else:
            stats.shape_mismatches += 1
    elif kind is AttributeKind.REPEATED_STRUCTURED:
        if isinstance(value, dict):
            result[attr_name] = [dict(value)]
        elif isinstance(value, list) and all(isinstance(item, dict) for item in value):
            result[attr_name] = [dict(item) for item in value]
        else:
            stats.shape_mismatches += 1
```

In `apply_mapping`, guard the first loop so direct-key entries with indexed targets are deferred (insert after `entry = mappings.get(source)`):

```python
    for source, value in product.items():
        entry = mappings.get(source)
        if entry is not None:
            try:
                if parse_indexed_path(entry.target).index is not None:
                    continue  # deferred to the indexed pass (precedence)
            except ValueError:
                pass
            _apply_entry(result, source, value, entry, registry, stats)
        elif source not in parent_has_sub_mapping:
            stats.dropped_unmapped += 1
```

And replace the second loop (source sub-path keys) with the two-pass precedence ordering (operator directive 5):

```python
    # Pass 1: non-indexed sub-path source mappings in dict order.
    for key, entry in mappings.items():
        if key in product or "." not in key:
            continue
        if _entry_is_indexed(entry):
            continue
        parent, _, sub = key.partition(".")
        if not sub or "." in sub or parent not in product:
            continue
        values, mismatch = _sub_values(product[parent], sub)
        if mismatch:
            stats.shape_mismatches += 1
            continue
        if values is not None:
            value = values[0] if len(values) == 1 else values
            _apply_entry(result, key, value, entry, registry, stats)

    # Pass 2: indexed target assignments, sorted by target path — override
    # broadcast values in their exact slot (operator directive 5).
    indexed = sorted(
        (
            (key, entry)
            for key, entry in mappings.items()
            if key not in product and _entry_is_indexed(entry)
        ),
        key=lambda pair: pair[1].target,
    )
    for key, entry in indexed:
        if key in product:
            continue  # direct-key indexed entries were applied via pass 0's deferral
        parent, dot, sub = key.partition(".")
        if not dot or not sub or "." in sub or parent not in product:
            continue
        values, mismatch = _sub_values(product[parent], sub)
        if mismatch:
            stats.shape_mismatches += 1
            continue
        if values is not None:
            value = values[0] if len(values) == 1 else values
            _apply_entry(result, key, value, entry, registry, stats)

    # Pass 3: deferred direct-key indexed entries (product carries the key).
    for source, value in product.items():
        entry = mappings.get(source)
        if entry is None or not _entry_is_indexed(entry):
            continue
        if isinstance(value, list):
            value = value[0] if len(value) == 1 else value
        _apply_entry(result, source, value, entry, registry, stats)

    return result, stats
```

Wait — pass 3 duplicates pass 0's deferral logic: direct-key indexed entries were skipped in the first loop and must be applied in the ordered indexed pass. Simplify: fold pass 3 into pass 2 by iterating `mappings.items()` there and handling `key in product` by reading `product[key]` directly. Correct final form of pass 2:

```python
    # Pass 2: indexed target assignments, sorted by target path — override
    # broadcast values in their exact slot (operator directive 5).
    indexed = sorted(
        (
            (key, entry)
            for key, entry in mappings.items()
            if _entry_is_indexed(entry)
        ),
        key=lambda pair: pair[1].target,
    )
    for key, entry in indexed:
        if key in product:
            value = product[key]
            if isinstance(value, list):
                value = value[0] if len(value) == 1 else value
            _apply_entry(result, key, value, entry, registry, stats)
            continue
        parent, dot, sub = key.partition(".")
        if not dot or not sub or "." in sub or parent not in product:
            continue
        values, mismatch = _sub_values(product[parent], sub)
        if mismatch:
            stats.shape_mismatches += 1
            continue
        if values is not None:
            value = values[0] if len(values) == 1 else values
            _apply_entry(result, key, value, entry, registry, stats)

    return result, stats
```

And add the helper at module level:

```python
def _entry_is_indexed(entry: MappingEntry) -> bool:
    try:
        return parse_indexed_path(entry.target).index is not None
    except ValueError:
        return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mapping_apply.py tests/test_field_mapping_api.py tests/test_export_renderer.py tests/test_mapping_step.py tests/test_example_feed_chain.py tests/test_mapping_matcher.py -v -n0`
Expected: all PASS — new indexed tests green; all pre-existing mapping/export/matcher tests unchanged.

If the golden-XML assertion fails on element order, check `backend/registry/attributes.json` `product_detail.fields` order and adjust the expected strings.

- [ ] **Step 6: Lint + typecheck**

Run: `uv run ruff check app/mapping/apply.py app/routes/field_mapping.py && uv run mypy app/mapping/apply.py app/routes/field_mapping.py`
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/mapping/apply.py backend/app/routes/field_mapping.py backend/tests/test_mapping_apply.py backend/tests/test_field_mapping_api.py backend/tests/test_export_renderer.py
git commit -m "feat: indexed mapping targets with slot-override precedence and golden XML test"
```

---

### Task 6: Plugins — indexed reads (filter, custom_labels) + indexed writes (rules) + products.py mirror

**Files:**
- Modify: `plugins/core/filter/plugin.py`
- Modify: `plugins/core/custom_labels/plugin.py`
- Modify: `plugins/core/rules/plugin.py`
- Modify: `backend/app/routes/products.py:196-218` (`_product_field_candidates`)
- Test: `backend/tests/test_filter_plugin.py`, `backend/tests/test_custom_labels_plugin.py`, `backend/tests/test_rules_plugin.py`, `backend/tests/test_product_lookup_indexed.py` (new)

**Interfaces:**
- Consumes: the Task 4 grammar — but each plugin embeds its own local `_parse_indexed` helper (plugin-isolation convention; plugins never import from `app` or each other).
- Produces: indexed read semantics in filter conditions, labelizer `resolve_path`/`matches`, rules `_field_value`; indexed THEN-action writes in rules (`apply_action`); indexed `_product_field_candidates` in the products route (this is app code — it imports `parse_indexed_path` directly).

- [ ] **Step 1: Write failing tests (RED)**

Add to `backend/tests/test_filter_plugin.py` (match its existing import style — it already imports `evaluate_condition` from the plugin module):

```python
def test_condition_on_indexed_repeated_scalar_element():
    product = {"additional_image_link": ["a.jpg", "b.jpg", "c.jpg"]}
    assert evaluate_condition(
        {"field": "additional_image_link.2", "op": "equals", "arg": "b.jpg"}, product
    )
    assert not evaluate_condition(
        {"field": "additional_image_link.2", "op": "equals", "arg": "a.jpg"}, product
    )


def test_condition_on_indexed_repeated_structured_sub():
    product = {"product_detail": [
        {"section_name": "General", "attribute_name": "Battery"},
        {"section_name": "Extra", "attribute_name": "Color"},
    ]}
    assert evaluate_condition(
        {"field": "product_detail.2.attribute_name", "op": "equals", "arg": "Color"},
        product,
    )
    assert evaluate_condition(
        {"field": "product_detail.1.section_name", "op": "contains", "arg": "Gen"},
        product,
    )


def test_condition_indexed_out_of_range_treated_as_empty():
    product = {"additional_image_link": ["a.jpg"]}
    assert not evaluate_condition(
        {"field": "additional_image_link.5", "op": "exists"}, product
    )
    assert evaluate_condition(
        {"field": "additional_image_link.5", "op": "empty"}, product
    )
```

Add to `backend/tests/test_custom_labels_plugin.py` (it loads the plugin module via `tests/labels_plugin_module.py` — keep that import style):

```python
def test_resolve_path_indexed_element():
    product = {"additional_image_link": ["a.jpg", "b.jpg"]}
    assert resolve_path(product, "additional_image_link.2") == ["b.jpg"]


def test_resolve_path_indexed_structured_sub():
    product = {"product_detail": [
        {"attribute_value": "V1"},
        {"attribute_value": "V2"},
    ]}
    assert resolve_path(product, "product_detail.2.attribute_value") == ["V2"]


def test_resolve_path_indexed_out_of_range_empty():
    product = {"additional_image_link": ["a.jpg"]}
    assert resolve_path(product, "additional_image_link.3") == []


def test_matches_indexed_field():
    product = {"product_detail": [
        {"attribute_name": "Battery"},
        {"attribute_name": "Color"},
    ]}
    assert matches(product, "product_detail.2.attribute_name", frozenset({"Color"}))
    assert not matches(product, "product_detail.1.attribute_name", frozenset({"Color"}))
```

Add to `backend/tests/test_rules_plugin.py` (match its existing imports of `evaluate_condition`, `apply_action`):

```python
def test_condition_reads_indexed_path():
    product = {"product_detail": [
        {"attribute_name": "Battery"},
        {"attribute_name": "Color"},
    ]}
    assert evaluate_condition(
        {"op": "equals", "field": "product_detail.2.attribute_name", "arg": "Color"},
        product,
    )


def test_action_set_indexed_repeated_scalar():
    product = {"additional_image_link": ["a.jpg", "b.jpg"]}
    out = apply_action(product, {"op": "set", "field": "additional_image_link.1",
                                 "value": "hero.jpg"})
    assert out["additional_image_link"] == ["hero.jpg", "b.jpg"]


def test_action_set_indexed_extends_list():
    product = {"additional_image_link": ["a.jpg"]}
    out = apply_action(product, {"op": "set", "field": "additional_image_link.3",
                                 "value": "c.jpg"})
    assert out["additional_image_link"] == ["a.jpg", "", "c.jpg"]


def test_action_set_indexed_structured_sub():
    product = {"product_detail": [{"section_name": "General"}]}
    out = apply_action(product, {"op": "set", "field": "product_detail.1.attribute_name",
                                 "value": "Battery"})
    assert out["product_detail"][0]["attribute_name"] == "Battery"


def test_action_set_indexed_structured_sub_extends():
    product = {"product_detail": [{"section_name": "General"}]}
    out = apply_action(product, {"op": "set", "field": "product_detail.3.section_name",
                                 "value": "Extra"})
    assert out["product_detail"] == [
        {"section_name": "General"}, {}, {"section_name": "Extra"},
    ]


def test_action_replace_indexed_element():
    product = {"additional_image_link": ["a-old.jpg", "b.jpg"]}
    out = apply_action(product, {"op": "replace", "field": "additional_image_link.1",
                                 "find": "old", "with": "new"})
    assert out["additional_image_link"][0] == "a-new.jpg"


def test_action_remove_indexed_element():
    product = {"additional_image_link": ["a.jpg", "b.jpg", "c.jpg"]}
    out = apply_action(product, {"op": "remove", "field": "additional_image_link.2"})
    assert out["additional_image_link"] == ["a.jpg", "c.jpg"]


def test_action_clear_indexed_element():
    product = {"additional_image_link": ["a.jpg", "b.jpg"]}
    out = apply_action(product, {"op": "clear", "field": "additional_image_link.1"})
    assert out["additional_image_link"][0] == ""
    assert out["additional_image_link"][1] == "b.jpg"
```

Create `backend/tests/test_product_lookup_indexed.py`:

```python
from app.routes.products import _product_field_candidates


def test_candidates_indexed_repeated_scalar():
    raw = {"additional_image_link": ["a.jpg", "b.jpg"]}
    assert _product_field_candidates(raw, "additional_image_link.2") == ["b.jpg"]
    assert _product_field_candidates(raw, "additional_image_link.5") == []


def test_candidates_indexed_structured_sub():
    raw = {"product_detail": [
        {"attribute_name": "Battery"},
        {"attribute_name": "Color"},
    ]}
    assert _product_field_candidates(
        raw, "product_detail.2.attribute_name"
    ) == ["Color"]


def test_candidates_non_indexed_unchanged():
    raw = {"title": "T", "images": ["x", "y"]}
    assert _product_field_candidates(raw, "title") == ["T"]
    assert _product_field_candidates(raw, "images") == ["x", "y"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_filter_plugin.py tests/test_custom_labels_plugin.py tests/test_rules_plugin.py tests/test_product_lookup_indexed.py -v -n0`
Expected: all new tests FAIL (no indexed resolution anywhere).

- [ ] **Step 3: Implement (GREEN) — shared local helper per plugin**

Add the same local helper to **each** of the three plugin files (deliberate duplication per the plugin-isolation convention):

```python
def _parse_indexed(path: str) -> tuple[str, int | None, str | None]:
    """attr | attr.sub | attr.N | attr.N.sub (N 1-based). Raises ValueError."""
    parts = path.split(".")
    if not parts or not parts[0] or len(parts) > 3:
        raise ValueError(f"invalid path {path!r}")
    attr = parts[0]
    if len(parts) == 1:
        return attr, None, None
    second = parts[1]
    if second.isdigit():
        index = int(second)
        if index < 1:
            raise ValueError(f"invalid index in {path!r}: 1-based")
        sub = parts[2] if len(parts) == 3 else None
        if sub == "":
            raise ValueError(f"invalid path {path!r}")
        return attr, index, sub
    if len(parts) == 3:
        raise ValueError(f"invalid path {path!r}")
    return attr, None, second
```

**`plugins/core/filter/plugin.py`** — replace `value = product.get(field)` in `evaluate_condition` (line 38) with:

```python
    try:
        attr, index, sub = _parse_indexed(field)
    except ValueError:
        raise FilterError(f"invalid field path {field!r}")
    value: Any = product.get(attr)
    if index is not None:
        if isinstance(value, list) and len(value) >= index:
            value = value[index - 1]
        else:
            value = None
        if value is not None and sub is not None:
            value = value.get(sub) if isinstance(value, dict) else None
    elif sub is not None:
        if isinstance(value, dict):
            value = value.get(sub)
        elif isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
            value = value[0].get(sub)
        else:
            value = None
```

**`plugins/core/custom_labels/plugin.py`** — replace the whole `resolve_path` function (lines 39-67) with:

```python
def resolve_path(product: dict[str, Any], path: str) -> list[str]:
    """Resolve a registry attribute path to candidate string values (spec §2.1).

    Grammar: attr | attr.sub | attr.N | attr.N.sub (N is 1-based).
    Indexed paths address one list element exactly; out-of-range yields no
    candidates. Non-indexed paths keep the legacy broadcast semantics.
    """
    try:
        attr, index, sub = _parse_indexed(path)
    except ValueError:
        return []
    value = product.get(attr)
    if value is None:
        return []
    if index is not None:
        if not isinstance(value, list) or len(value) < index:
            return []
        element = value[index - 1]
        if sub is None:
            return [str(element)] if element not in (None, "") else []
        if not isinstance(element, dict):
            return []
        item = element.get(sub)
        return [str(item)] if item not in (None, "") else []
    if sub:
        if isinstance(value, dict):
            item = value.get(sub)
            return [str(item)] if item not in (None, "") else []
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict):
                return []
            item = value[0].get(sub)
            return [str(item)] if item not in (None, "") else []
        return []
    if isinstance(value, str):
        return [value] if value != "" else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]
```

**`plugins/core/rules/plugin.py`** — replace `_field_value` (lines 13-14):

```python
def _field_value(product: dict[str, Any], field: str) -> Any:
    try:
        attr, index, sub = _parse_indexed(field)
    except ValueError:
        return None
    value = product.get(attr)
    if index is not None:
        if not isinstance(value, list) or len(value) < index:
            return None
        value = value[index - 1]
        if sub is not None:
            return value.get(sub) if isinstance(value, dict) else None
        return value
    if sub is not None:
        if isinstance(value, dict):
            return value.get(sub)
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
            return value[0].get(sub)
        return None
    return value
```

In the same file, in `apply_action`, after the `field` validation and before `next_product: dict[str, Any] = dict(product)`, insert:

```python
    try:
        attr, index, sub = _parse_indexed(field)
    except ValueError:
        raise ActionError(f"invalid field path {field!r}")

    if index is not None:
        return _apply_indexed_action(product, attr, index, sub, action, op)
```

and add:

```python
def _apply_indexed_action(
    product: dict[str, Any],
    attr: str,
    index: int,
    sub: str | None,
    action: dict[str, Any],
    op: str,
) -> dict[str, Any]:
    """Index-addressed THEN action (copy-on-write). Index is 1-based."""
    next_product = dict(product)
    idx0 = index - 1
    current = next_product.get(attr)

    if sub is None:
        if op in ("set", "append", "prepend", "replace"):
            bucket = list(current) if isinstance(current, list) else []
            while len(bucket) <= idx0:
                bucket.append("")
            if op == "set":
                text = "" if action.get("value") is None else str(action["value"])
            elif op in ("append", "prepend"):
                existing = "" if bucket[idx0] is None else str(bucket[idx0])
                addition = "" if action.get("value") is None else str(action["value"])
                text = addition + existing if op == "prepend" else existing + addition
            else:  # replace
                text = "" if bucket[idx0] is None else str(bucket[idx0])
                text = _apply_replace(text, action)
            bucket[idx0] = text
            next_product[attr] = bucket
            return next_product
        if op == "remove":
            if isinstance(current, list) and len(current) > idx0:
                bucket = list(current)
                bucket.pop(idx0)
                next_product[attr] = bucket
            return next_product
        if op == "clear":
            if isinstance(current, list) and len(current) > idx0:
                bucket = list(current)
                bucket[idx0] = ""
                next_product[attr] = bucket
            return next_product
        raise ActionError(f"unknown action op {op!r}")

    bucket = [
        dict(elem) if isinstance(elem, dict) else elem
        for elem in (current if isinstance(current, list) else [])
    ]
    while len(bucket) <= idx0:
        bucket.append({})
    element = bucket[idx0]
    if not isinstance(element, dict):
        raise ActionError(f"cannot address sub-field on non-object element of {attr!r}")
    if op == "set":
        element[sub] = action.get("value")
    elif op in ("append", "prepend"):
        existing = "" if element.get(sub) is None else str(element.get(sub))
        addition = "" if action.get("value") is None else str(action["value"])
        element[sub] = addition + existing if op == "prepend" else existing + addition
    elif op == "replace":
        text = "" if element.get(sub) is None else str(element.get(sub))
        element[sub] = _apply_replace(text, action)
    elif op == "remove":
        element.pop(sub, None)
    elif op == "clear":
        element[sub] = ""
    else:
        raise ActionError(f"unknown action op {op!r}")
    bucket[idx0] = element
    next_product[attr] = bucket
    return next_product
```

Verify before writing: `_apply_replace(text, action)` and `ActionError` already exist in that file (they do — `plugins/core/rules/plugin.py:155` and `:9`).

**`backend/app/routes/products.py`** — add the import:

```python
from ..mapping.indexed_path import parse_indexed_path
```

Replace `_product_field_candidates` (lines 196-218) with:

```python
def _product_field_candidates(raw: dict, path: str) -> list[str]:
    """Candidate values of a registry path in raw_data — mirrors the
    custom_labels plugin's resolve_path() semantics (scalar / repeated /
    attr.sub / indexed attr.N[.sub]). Keep in sync with
    plugins/core/custom_labels/plugin.py."""
    try:
        parsed = parse_indexed_path(path)
    except ValueError:
        return []
    value = raw.get(parsed.attr)
    if value is None:
        return []
    if parsed.index is not None:
        if not isinstance(value, list) or len(value) < parsed.index:
            return []
        element = value[parsed.index - 1]
        if parsed.sub is None:
            return [str(element)] if element not in (None, "") else []
        if not isinstance(element, dict):
            return []
        item = element.get(parsed.sub)
        return [str(item)] if item not in (None, "") else []
    if parsed.sub:
        if isinstance(value, dict):
            item = value.get(parsed.sub)
            return [str(item)] if item not in (None, "") else []
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict):
                return []
            item = value[0].get(parsed.sub)
            return [str(item)] if item not in (None, "") else []
        return []
    if isinstance(value, str):
        return [value] if value != "" else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_filter_plugin.py tests/test_custom_labels_plugin.py tests/test_rules_plugin.py tests/test_product_lookup_indexed.py tests/test_custom_labels_preview.py tests/test_category_rules.py -v -n0`
Expected: all PASS — every pre-existing plugin test stays green (non-indexed behavior unchanged).

- [ ] **Step 5: Commit**

```bash
git add plugins/core/filter/plugin.py plugins/core/custom_labels/plugin.py plugins/core/rules/plugin.py backend/app/routes/products.py backend/tests/test_filter_plugin.py backend/tests/test_custom_labels_plugin.py backend/tests/test_rules_plugin.py backend/tests/test_product_lookup_indexed.py
git commit -m "feat: indexed path reads in filter/labelizer and indexed writes in rules plugin"
```

---

### Task 7: `GET /feed-sources/{id}/fields` unified shape

**Files:**
- Modify: `backend/app/routes/products.py:170-187` (`feed_source_fields`)
- Test: `backend/tests/test_feed_fields_api.py` (new)

**Interfaces:**
- Consumes: `MappingDocument.from_json`, `_BASELINE_FIELDS`.
- Produces: `GET /feed-sources/{id}/fields` → `{"fields": [{"name", "kind", "sub_fields": [{"name", "kind"}], "max_repeats"}]}` — source fields from the persisted mapping document (sub-kind: `structured`→`scalar`, `repeated_structured`→`repeated_scalar`; max_repeats only for repeated kinds), `_BASELINE_FIELDS` merged as scalars (`max_repeats: 1`) only when absent, sorted by name. 404 for unknown feed source.

- [ ] **Step 1: Write failing tests (RED)**

Create `backend/tests/test_feed_fields_api.py` (copy the `app_factory`/`logged_in_client` block from `backend/tests/test_registry_api.py:17-51` verbatim, including imports), then add:

```python
from app.models import FeedSource


async def test_fields_requires_auth(app_factory):
    app, _ = app_factory
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anon.get("/feed-sources/1/fields")).status_code == 401


async def test_fields_unknown_feed_source_404(app_factory):
    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/99999/fields")).status_code == 404


async def test_fields_unified_shape_from_mapping_document(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(
        f"/clients/{created['id']}/feed-sources",
        json={"name": "DE", "source_format": "xml"},
    )).json()
    async with factory() as session:
        async with session.begin():
            row = await session.get(FeedSource, feed["id"])
            row.field_mapping = {
                "version": 1, "auto_mapped": False,
                "source_fields": [
                    {"name": "title", "kind": "scalar", "sub_fields": [],
                     "max_repeats": 0},
                    {"name": "shipping", "kind": "repeated_structured",
                     "sub_fields": ["country", "price"], "max_repeats": 3},
                ],
                "mappings": {},
            }

    resp = await client.get(f"/feed-sources/{feed['id']}/fields")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["title"]["kind"] == "scalar"
    assert by_name["title"]["sub_fields"] == []
    assert by_name["title"]["max_repeats"] == 1  # non-repeated -> 1
    ship = by_name["shipping"]
    assert ship["kind"] == "repeated_structured"
    assert ship["max_repeats"] == 3
    assert [s["name"] for s in ship["sub_fields"]] == ["country", "price"]
    assert all(s["kind"] == "repeated_scalar" for s in ship["sub_fields"])
    assert by_name["image_link"]["kind"] == "scalar"  # baseline merged
    names = [f["name"] for f in body["fields"]]
    assert names == sorted(names)


async def test_fields_never_ingested_returns_baselines_only(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(
        f"/clients/{created['id']}/feed-sources",
        json={"name": "DE", "source_format": "xml"},
    )).json()
    resp = await client.get(f"/feed-sources/{feed['id']}/fields")
    assert resp.status_code == 200
    names = {f["name"] for f in resp.json()["fields"]}
    assert {"title", "description", "link", "image_link", "availability",
            "price", "condition"} <= names
    assert all(f["kind"] == "scalar" for f in resp.json()["fields"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feed_fields_api.py -v -n0`
Expected: FAIL — response is a plain string list.

- [ ] **Step 3: Implement (GREEN)**

`backend/app/routes/products.py` — add imports (merge with the existing block):

```python
from ..ingest.report import SourceField
from ..mapping.document import MappingDocument
```

Replace the `feed_source_fields` handler (lines 170-187) with:

```python
def _source_field_descriptor(sf: SourceField) -> dict:
    sub_kind = "repeated_scalar" if sf.kind == "repeated_structured" else "scalar"
    return {
        "name": sf.name,
        "kind": sf.kind,
        "sub_fields": [{"name": sub, "kind": sub_kind} for sub in sf.sub_fields],
        "max_repeats": (
            sf.max_repeats
            if sf.kind in ("repeated_scalar", "repeated_structured")
            else 1
        ),
    }


@router.get("/feed-sources/{feed_source_id}/fields")
async def feed_source_fields(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
        feed_source = await session.get(FeedSource, feed_source_id)
    doc = MappingDocument.from_json(feed_source.field_mapping)
    fields: dict[str, dict] = {
        sf.name: _source_field_descriptor(sf) for sf in doc.source_fields
    }
    for name in _BASELINE_FIELDS:
        if name not in fields:
            fields[name] = {
                "name": name,
                "kind": "scalar",
                "sub_fields": [],
                "max_repeats": 1,
            }
    return {"fields": [fields[name] for name in sorted(fields)]}
```

(Observed source fields win over baselines — matches today's union semantics. The old `text(...)` JSONB-key query and `_BASELINE_FIELDS` string-union line are deleted.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feed_fields_api.py tests/test_products_api.py -v -n0`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/products.py backend/tests/test_feed_fields_api.py
git commit -m "feat!: unified field descriptor shape for GET /feed-sources/{id}/fields"
```

---

### Task 8: Frontend types, hooks, `fieldOptions.ts` (directives 3 & 4)

**Files:**
- Modify: `frontend/src/api/types.ts:72-103` (RegistrySubField, RegistryAttribute, SourceField), `:219-221` (FeedSourceFieldsResponse)
- Modify: `frontend/src/api/queryKeys.ts:6`
- Modify: `frontend/src/api/hooks.ts:123-145` (both hooks), `:186-196` (useDryRun), `:198-208` (useTriggerRun)
- Create: `frontend/src/api/fieldOptions.ts`
- Modify (mechanical only): `frontend/src/features/products/ProductsPage.tsx:65-66`, `frontend/src/features/customLabels/RuleValuesEditor.tsx:51-55`
- Test: `frontend/src/api/fieldOptions.test.ts` (new), `frontend/src/api/hooks.registry.test.tsx` (new), `frontend/src/api/hooks.m10c.test.tsx` (update)

**Interfaces:**
- Produces:

```typescript
// fieldOptions.ts
export type FieldSubFieldDescriptor = { name: string; kind?: string };
export type FieldDescriptor = {
  name: string;
  kind: string;
  sub_fields: FieldSubFieldDescriptor[];
  max_repeats: number;
};
export type FieldOption = { value: string; label: string };
export type GroupedFieldOptions = { group: string; items: FieldOption[] }[];
export const INDEXED_PATH_REGEX =
  /^[a-z_][a-z0-9_]*(\.([1-9]\d*))?(\.[a-z_][a-z0-9_]*)?$/;
export const FIELD_GROUP_LABEL = 'Field';
export function fromSourceFields(fields: SourceField[]): FieldDescriptor[];
export function fromRegistryAttributes(attrs: RegistryAttribute[]): FieldDescriptor[];
export function buildFieldOptions(
  fields: FieldDescriptor[],
  opts?: { includeParent?: boolean }, // default { includeParent: true }
): GroupedFieldOptions;
```

- `useRegistryAttributes(feedSourceId?: number | string)` — key `['registry', 'attributes', id]` when id passed.
- `useFeedSourceFields` returns `{ fields: FieldDescriptor[] }`.

- [ ] **Step 1: Write failing tests (RED)**

Create `frontend/src/api/fieldOptions.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import {
  INDEXED_PATH_REGEX, buildFieldOptions, fromRegistryAttributes,
  fromSourceFields, type FieldDescriptor,
} from './fieldOptions';
import type { RegistryAttribute, SourceField } from './types';

const scalar: FieldDescriptor = { name: 'title', kind: 'scalar', sub_fields: [], max_repeats: 0 };
const structured: FieldDescriptor = {
  name: 'installment', kind: 'structured',
  sub_fields: [{ name: 'months', kind: 'scalar' }, { name: 'amount', kind: 'scalar' }],
  max_repeats: 0,
};
const repeatedScalar: FieldDescriptor = {
  name: 'additional_image_link', kind: 'repeated_scalar', sub_fields: [], max_repeats: 3,
};
const repeatedStructured: FieldDescriptor = {
  name: 'product_detail', kind: 'repeated_structured',
  sub_fields: [
    { name: 'section_name', kind: 'repeated_scalar' },
    { name: 'attribute_name', kind: 'repeated_scalar' },
    { name: 'attribute_value', kind: 'repeated_scalar' },
  ],
  max_repeats: 2,
};

describe('buildFieldOptions', () => {
  it('puts scalars under the "Field" group', () => {
    expect(buildFieldOptions([scalar])).toEqual([
      { group: 'Field', items: [{ value: 'title', label: 'title' }] },
    ]);
  });

  it('expands structured attributes into sub items', () => {
    expect(buildFieldOptions([structured])).toEqual([
      {
        group: 'installment',
        items: [
          { value: 'installment', label: 'installment' },
          { value: 'installment.months', label: 'months' },
          { value: 'installment.amount', label: 'amount' },
        ],
      },
    ]);
  });

  it('expands repeated_scalar into #i indexed items up to max_repeats', () => {
    expect(buildFieldOptions([repeatedScalar])).toEqual([
      {
        group: 'additional_image_link',
        items: [
          { value: 'additional_image_link', label: 'additional_image_link' },
          { value: 'additional_image_link.1', label: '#1' },
          { value: 'additional_image_link.2', label: '#2' },
          { value: 'additional_image_link.3', label: '#3' },
        ],
      },
    ]);
  });

  it('expands repeated_structured into #i · sub items', () => {
    const groups = buildFieldOptions([repeatedStructured]);
    expect(groups[0].items).toEqual([
      { value: 'product_detail', label: 'product_detail' },
      { value: 'product_detail.1.section_name', label: '#1 · section_name' },
      { value: 'product_detail.1.attribute_name', label: '#1 · attribute_name' },
      { value: 'product_detail.1.attribute_value', label: '#1 · attribute_value' },
      { value: 'product_detail.2.section_name', label: '#2 · section_name' },
      { value: 'product_detail.2.attribute_name', label: '#2 · attribute_name' },
      { value: 'product_detail.2.attribute_value', label: '#2 · attribute_value' },
    ]);
  });

  it('emits no children when max_repeats is 0', () => {
    const groups = buildFieldOptions([{ ...repeatedScalar, max_repeats: 0 }]);
    expect(groups[0].items).toEqual([
      { value: 'additional_image_link', label: 'additional_image_link' },
    ]);
  });

  it('includeParent: false drops the parent option', () => {
    const groups = buildFieldOptions([repeatedScalar], { includeParent: false });
    expect(groups[0].items.every((i) => i.value !== 'additional_image_link')).toBe(true);
  });

  it('literal dotted field name wins over generated path (collision)', () => {
    const dotted: FieldDescriptor = {
      name: 'a.b', kind: 'scalar', sub_fields: [], max_repeats: 0,
    };
    const parent: FieldDescriptor = {
      name: 'a', kind: 'structured', sub_fields: [{ name: 'b' }], max_repeats: 0,
    };
    const groups = buildFieldOptions([dotted, parent]);
    const fieldGroup = groups.find((g) => g.group === 'Field')!;
    expect(fieldGroup.items).toContainEqual({ value: 'a.b', label: 'a.b' });
    const aGroup = groups.find((g) => g.group === 'a')!;
    expect(aGroup.items.map((i) => i.value)).not.toContain('a.b');
  });
});

describe('adapters', () => {
  it('fromSourceFields maps SourceField to FieldDescriptor', () => {
    const sf: SourceField = {
      name: 'shipping', kind: 'repeated_structured',
      sub_fields: ['country', 'price'], max_repeats: 3,
    };
    expect(fromSourceFields([sf])).toEqual([{
      name: 'shipping', kind: 'repeated_structured',
      sub_fields: [{ name: 'country' }, { name: 'price' }], max_repeats: 3,
    }]);
  });

  it('fromRegistryAttributes maps RegistryAttribute to FieldDescriptor', () => {
    const attr: RegistryAttribute = {
      name: 'product_detail', kind: 'repeated_structured',
      required: 'optional',
      sub_fields: [
        { name: 'section_name', type: 'String', required: 'optional', kind: 'repeated_scalar' },
      ],
      enum_values: [], max_repeats: 2,
    };
    expect(fromRegistryAttributes([attr])).toEqual([{
      name: 'product_detail', kind: 'repeated_structured',
      sub_fields: [{ name: 'section_name', kind: 'repeated_scalar' }],
      max_repeats: 2,
    }]);
  });
});

describe('INDEXED_PATH_REGEX (directive 4)', () => {
  const valid = [
    'title', 'shipping.price', 'additional_image_link.1',
    'additional_image_link.12', 'product_detail.2.attribute_value',
    'a_1.b_2', 'product_detail.7.section_name',
  ];
  const invalid = [
    'product_detail.0.attribute_name', 'product_detail.0',
    '.title', 'title.', '', 'a..b',
    'Product_Detail', 'product_detail.-1.section_name', 'a.b.c.d',
  ];
  it.each(valid.map((v) => [v]))('accepts %s', (path) => {
    expect(INDEXED_PATH_REGEX.test(path)).toBe(true);
  });
  it.each(invalid.map((v) => [v]))('rejects %s', (path) => {
    expect(INDEXED_PATH_REGEX.test(path)).toBe(false);
  });
});
```

Create `frontend/src/api/hooks.registry.test.tsx`:

```typescript
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useFeedSourceFields, useRegistryAttributes, useTriggerRun } from './hooks';
import { stubFetch } from '../test/fetch';

let queryClient: QueryClient;
let fetchMock: ReturnType<typeof stubFetch>;

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

const registryFixture = [
  { name: 'title', kind: 'scalar', required: 'required', sub_fields: [],
    enum_values: [], baseline_required: true, max_repeats: 1 },
  { name: 'product_detail', kind: 'repeated_structured', required: 'optional',
    sub_fields: [
      { name: 'section_name', type: 'String', required: 'optional', kind: 'repeated_scalar' },
    ],
    enum_values: [], baseline_required: false, max_repeats: 2 },
];

const fieldsFixture = {
  fields: [
    { name: 'title', kind: 'scalar', sub_fields: [], max_repeats: 1 },
    { name: 'shipping', kind: 'repeated_structured',
      sub_fields: [{ name: 'country', kind: 'repeated_scalar' }], max_repeats: 3 },
  ],
};

beforeEach(() => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  fetchMock = stubFetch(() => jsonResponse({}));
});

describe('registry/fields hooks', () => {
  it('useRegistryAttributes passes feed_source_id and returns descriptors', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/registry/attributes?feed_source_id=5') return jsonResponse(registryFixture);
      return jsonResponse([]);
    });
    const { result } = renderHook(() => useRegistryAttributes(5), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data![1].max_repeats).toBe(2);
  });

  it('useRegistryAttributes without id keeps the bare URL', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/registry/attributes');
      return jsonResponse(registryFixture.map((a) => ({ ...a, max_repeats: 0 })));
    });
    const { result } = renderHook(() => useRegistryAttributes(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
  });

  it('useFeedSourceFields returns descriptor array', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/feed-sources/7/fields');
      return jsonResponse(fieldsFixture);
    });
    const { result } = renderHook(() => useFeedSourceFields(7), { wrapper });
    await waitFor(() => expect(result.current.data?.fields).toBeDefined());
    expect(result.current.data!.fields[1].max_repeats).toBe(3);
  });

  it('useTriggerRun invalidates the registry attributes prefix (directive 3)', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/registry/attributes?feed_source_id=5') return jsonResponse(registryFixture);
      if (url === '/feed-sources/5/run') return jsonResponse({ run_id: 1 });
      return jsonResponse({});
    });
    const registry = renderHook(() => useRegistryAttributes(5), { wrapper });
    await waitFor(() => expect(registry.result.current.data).toBeDefined());
    const spy = vi.spyOn(queryClient, 'invalidateQueries');

    const run = renderHook(() => useTriggerRun(5), { wrapper });
    await run.result.current.mutateAsync();

    const called = spy.mock.calls.some((call) => {
      const key = (call[0] as { queryKey?: unknown[] }).queryKey;
      return Array.isArray(key) && key[0] === 'registry' && key[1] === 'attributes';
    });
    expect(called).toBe(true);
  });
});
```

Update `frontend/src/api/hooks.m10c.test.tsx`: find its `useFeedSourceFields` stub (search for `fields`) and change the mocked response from a string array to the descriptor shape:

```typescript
jsonResponse({
  fields: [
    { name: 'title', kind: 'scalar', sub_fields: [], max_repeats: 1 },
    { name: 'brand', kind: 'scalar', sub_fields: [], max_repeats: 1 },
  ],
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- src/api/fieldOptions.test.ts src/api/hooks.registry.test.tsx`
Expected: FAIL — `./fieldOptions` doesn't exist; hooks use old shapes.

- [ ] **Step 3: Implement (GREEN)**

`frontend/src/api/types.ts` — update the types:

```typescript
export type RegistrySubField = {
  name: string;
  type: string;
  required: string;
  kind?: string;
};

export type RegistryAttribute = {
  name: string;
  kind: string;
  required: string;
  baseline_required?: boolean;
  sub_fields: RegistrySubField[];
  enum_values: string[];
  max_repeats: number;
};

export type SourceField = {
  name: string;
  kind: string;
  sub_fields: string[];
  max_repeats: number;
};
```

```typescript
export type FeedSourceFieldsResponse = {
  fields: {
    name: string;
    kind: string;
    sub_fields: { name: string; kind?: string }[];
    max_repeats: number;
  }[];
};
```

`frontend/src/api/queryKeys.ts` — replace line 6:

```typescript
  registryAttributes: (feedSourceId?: number | string) =>
    (feedSourceId === undefined
      ? ['registry', 'attributes'] as const
      : ['registry', 'attributes', feedSourceId] as const),
```

`frontend/src/api/hooks.ts` — replace `useFeedSourceFields` and `useRegistryAttributes` (lines 123-145):

```typescript
export function useFeedSourceFields(feedSourceId: number | string) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).fields,
    queryFn: () =>
      apiGet<FeedSourceFieldsResponse>(`/feed-sources/${feedSourceId}/fields`),
    enabled: Boolean(feedSourceId),
  });
}

export function useRegistryAttributes(feedSourceId?: number | string) {
  return useQuery({
    queryKey: queryKeys.registryAttributes(feedSourceId),
    queryFn: () => apiGet<RegistryAttribute[]>(
      feedSourceId === undefined
        ? '/registry/attributes'
        : `/registry/attributes?feed_source_id=${feedSourceId}`,
    ),
    staleTime: Infinity,
  });
}
```

In the same file, add the directive-3 invalidation to `useDryRun`'s and `useTriggerRun`'s `onSuccess` blocks (after their existing `invalidateQueries` calls):

```typescript
      void queryClient.invalidateQueries({ queryKey: ['registry', 'attributes'] });
```

Mechanical call-site fixes:

`frontend/src/features/products/ProductsPage.tsx` (lines 65-66):

```typescript
  const fieldsQuery = useFeedSourceFields(feedSourceId ?? '');
  const allFields = (fieldsQuery.data?.fields ?? []).map((d) => d.name);
```

`frontend/src/features/customLabels/RuleValuesEditor.tsx` (lines 51-55) — data mapping only, semantics untouched:

```typescript
  const fieldsQuery = useFeedSourceFields(String(feedSourceId ?? ''));
  const fieldOptions = useMemo(
    () => (fieldsQuery.data?.fields ?? [])
      .map((d) => d.name)
      .filter((f) => !PREVIEW_DEFAULT_FIELDS.has(f)),
    [fieldsQuery.data],
  );
```

Create `frontend/src/api/fieldOptions.ts`:

```typescript
import type { RegistryAttribute, SourceField } from './types';

export type FieldSubFieldDescriptor = { name: string; kind?: string };

export type FieldDescriptor = {
  name: string;
  kind: string;
  sub_fields: FieldSubFieldDescriptor[];
  max_repeats: number;
};

export type FieldOption = { value: string; label: string };

export type GroupedFieldOptions = { group: string; items: FieldOption[] }[];

/** Canonical indexed-path grammar (1-based indices) — mirrors the backend
 * parse_indexed_path; validates free-text input (operator directive 4). */
export const INDEXED_PATH_REGEX =
  /^[a-z_][a-z0-9_]*(\.([1-9]\d*))?(\.[a-z_][a-z0-9_]*)?$/;

export const FIELD_GROUP_LABEL = 'Field';

export function fromSourceFields(fields: SourceField[]): FieldDescriptor[] {
  return fields.map((f) => ({
    name: f.name,
    kind: f.kind,
    sub_fields: f.sub_fields.map((name) => ({ name })),
    max_repeats: f.max_repeats,
  }));
}

export function fromRegistryAttributes(attrs: RegistryAttribute[]): FieldDescriptor[] {
  return attrs.map((a) => ({
    name: a.name,
    kind: a.kind,
    sub_fields: a.sub_fields.map((s) => ({ name: s.name, kind: s.kind })),
    max_repeats: a.max_repeats,
  }));
}

const REPEATED_KINDS = new Set(['repeated_scalar', 'repeated_structured']);

/**
 * Build grouped, indexed options from unified descriptors.
 *
 * - scalar -> group "Field"; structured -> group attr: parent + attr.sub
 * - repeated_scalar -> group attr: parent + attr.i (#i)
 * - repeated_structured -> group attr: parent + attr.i.sub (#i · sub)
 * - max_repeats 0 -> no children (free text still allows typed indices)
 * - a literal dotted field name (scalar, never expanded) wins over a
 *   same-valued generated path (collision rule)
 */
export function buildFieldOptions(
  fields: FieldDescriptor[],
  opts?: { includeParent?: boolean },
): GroupedFieldOptions {
  const includeParent = opts?.includeParent ?? true;
  const literalNames = new Set(fields.filter((f) => f.name.includes('.')).map((f) => f.name));
  const groups = new Map<string, FieldOption[]>();

  const push = (group: string, option: FieldOption) => {
    if (
      option.value.includes('.')
      && literalNames.has(option.value)
      && !literalNames.has(group)
    ) {
      return; // generated path collides with a literal field name — literal wins
    }
    const list = groups.get(group) ?? [];
    if (!list.some((o) => o.value === option.value)) {
      list.push(option);
    }
    groups.set(group, list);
  };

  for (const field of fields) {
    const isStructured = field.kind === 'structured' || field.kind === 'repeated_structured';
    if (!isStructured) {
      push(FIELD_GROUP_LABEL, { value: field.name, label: field.name });
      continue;
    }
    if (includeParent) {
      push(field.name, { value: field.name, label: field.name });
    }
    if (field.kind === 'structured') {
      for (const sub of field.sub_fields) {
        push(field.name, { value: `${field.name}.${sub.name}`, label: sub.name });
      }
      continue;
    }
    const max = Math.max(0, field.max_repeats);
    for (let i = 1; i <= max; i++) {
      if (field.kind === 'repeated_scalar') {
        push(field.name, { value: `${field.name}.${i}`, label: `#${i}` });
      } else {
        for (const sub of field.sub_fields) {
          push(field.name, {
            value: `${field.name}.${i}.${sub.name}`,
            label: `#${i} · ${sub.name}`,
          });
        }
      }
    }
  }

  return Array.from(groups.entries()).map(([group, items]) => ({ group, items }));
}
```

(The unused `REPEATED_KINDS` constant is deleted — the branch logic covers it. Keep the file free of dead exports.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/api/fieldOptions.test.ts src/api/hooks.registry.test.tsx src/api/hooks.m10c.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Typecheck the mechanical fixes**

Run: `npm run typecheck`
Expected: errors ONLY in the four not-yet-migrated consumers (MappingTable, MatchFieldCombobox via CustomLabelsUI fixtures, RulesUI, FilterUI) and their test fixtures. The api layer + ProductsPage + RuleValuesEditor must be clean. If any error is elsewhere, fix it now.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/queryKeys.ts frontend/src/api/hooks.ts frontend/src/api/fieldOptions.ts frontend/src/api/fieldOptions.test.ts frontend/src/api/hooks.registry.test.tsx frontend/src/api/hooks.m10c.test.tsx frontend/src/features/products/ProductsPage.tsx frontend/src/features/customLabels/RuleValuesEditor.tsx
git commit -m "feat!: unified FieldDescriptor types, hooks, and fieldOptions module (directives 3+4)"
```

---

### Task 9: `FieldSelect` shared component

**Files:**
- Create: `frontend/src/components/FieldSelect.tsx`
- Create: `frontend/src/components/FieldSelect.test.tsx`
- Modify: `frontend/public/locales/en/common.json`, `frontend/public/locales/de/common.json`

**Interfaces:**
- Consumes: `GroupedFieldOptions`, `INDEXED_PATH_REGEX` (Task 8).
- Produces:

```typescript
export type FieldSelectProps = {
  value: string;
  onChange: (value: string) => void;   // clear emits ''
  options: GroupedFieldOptions;
  label?: React.ReactNode;
  description?: React.ReactNode;
  placeholder?: string;
  disabled?: boolean;
  error?: React.ReactNode;
  clearable?: boolean;
  size?: 'xs' | 'sm' | 'md' | 'lg';
  w?: number | string;
  'aria-label'?: string;
  'data-testid'?: string;
};
```

- [ ] **Step 1: Write failing tests (RED)**

Create `frontend/src/components/FieldSelect.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../i18n';
import { render } from '../test/render';
import { buildFieldOptions, type FieldDescriptor } from '../api/fieldOptions';
import { FieldSelect } from './FieldSelect';

const fields: FieldDescriptor[] = [
  { name: 'title', kind: 'scalar', sub_fields: [], max_repeats: 1 },
  { name: 'product_detail', kind: 'repeated_structured',
    sub_fields: [
      { name: 'section_name', kind: 'repeated_scalar' },
      { name: 'attribute_value', kind: 'repeated_scalar' },
    ], max_repeats: 2 },
];

const options = buildFieldOptions(fields);

function setup(overrides?: Partial<React.ComponentProps<typeof FieldSelect>>) {
  const onChange = vi.fn();
  render(
    <FieldSelect
      value=""
      onChange={onChange}
      options={options}
      aria-label="field"
      data-testid="field-select"
      {...overrides}
    />,
  );
  return { onChange };
}

beforeEach(async () => {
  await i18n.loadNamespaces('common');
});

describe('FieldSelect', () => {
  it('renders grouped options when opened', async () => {
    setup({ value: 'title' });
    const user = userEvent.setup();
    await user.click(screen.getByTestId('field-select'));
    await waitFor(() => {
      expect(screen.getByText('product_detail')).toBeInTheDocument();
    });
  });

  it('filters by label', async () => {
    setup();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('field-select'));
    await user.type(screen.getByTestId('field-select'), 'attribute_value');
    await waitFor(() => {
      expect(screen.getByText('#2 · attribute_value')).toBeInTheDocument();
    });
  });

  it('submits a picked option with the full dot path', async () => {
    const { onChange } = setup();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('field-select'));
    const opt = await screen.findByText('#2 · attribute_value');
    await user.click(opt);
    expect(onChange).toHaveBeenCalledWith('product_detail.2.attribute_value');
  });

  it('accepts valid free text beyond max_repeats (directive 4 happy path)', async () => {
    const { onChange } = setup();
    const user = userEvent.setup();
    const input = screen.getByTestId('field-select');
    await user.click(input);
    await user.type(input, 'product_detail.9.section_name');
    await user.keyboard('{Enter}');
    expect(onChange).toHaveBeenCalledWith('product_detail.9.section_name');
  });

  it('rejects 0-based free text with an inline message and does not submit (directive 4)', async () => {
    const { onChange } = setup();
    const user = userEvent.setup();
    const input = screen.getByTestId('field-select');
    await user.click(input);
    await user.type(input, 'product_detail.0.section_name');
    await user.keyboard('{Enter}');
    expect(onChange).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByText(/1-based/)).toBeInTheDocument();
    });
  });

  it('clear emits empty string when clearable', async () => {
    const { onChange } = setup({ value: 'title', clearable: true });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /clear/i }));
    expect(onChange).toHaveBeenCalledWith('');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- src/components/FieldSelect.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement (GREEN)**

Add i18n keys. Read `frontend/public/locales/en/common.json` and `de/common.json` first; add at the top level of both (keeping their existing structure):

en:
```json
"fieldSelect": {
  "customValue": "Use custom value \"{{value}}\"",
  "invalidPath": "Indices are 1-based (e.g. .1, .2)"
}
```

de:
```json
"fieldSelect": {
  "customValue": "Eigenen Wert verwenden: „{{value}}“",
  "invalidPath": "Indizes sind 1-basiert (z. B. .1, .2)"
}
```

Create `frontend/src/components/FieldSelect.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { Combobox, InputBase, useCombobox } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { INDEXED_PATH_REGEX, type FieldOption, type GroupedFieldOptions } from '../api/fieldOptions';

export type FieldSelectProps = {
  value: string;
  onChange: (value: string) => void;
  options: GroupedFieldOptions;
  label?: React.ReactNode;
  description?: React.ReactNode;
  placeholder?: string;
  disabled?: boolean;
  error?: React.ReactNode;
  clearable?: boolean;
  size?: 'xs' | 'sm' | 'md' | 'lg';
  w?: number | string;
  'aria-label'?: string;
  'data-testid'?: string;
};

function matchesQuery(option: FieldOption, group: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    option.value.toLowerCase().includes(q)
    || option.label.toLowerCase().includes(q)
    || group.toLowerCase().includes(q)
  );
}

export function FieldSelect({
  value,
  onChange,
  options,
  label,
  description,
  placeholder,
  disabled = false,
  error,
  clearable = false,
  size = 'sm',
  w,
  'aria-label': ariaLabel,
  'data-testid': dataTestId,
}: FieldSelectProps) {
  const { t } = useTranslation('common');
  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });
  const [search, setSearch] = useState(value);
  useEffect(() => setSearch(value), [value]);

  const query = search.trim().toLowerCase();
  const isKnown = useMemo(
    () => options.some((g) => g.items.some((i) => i.value === search)),
    [options, search],
  );
  const isValidSyntax = search === '' || INDEXED_PATH_REGEX.test(search);
  const showCustom = !isKnown && search !== '' && isValidSyntax;
  const showInvalid = search !== '' && !isValidSyntax;

  const visibleGroups = useMemo(
    () => options
      .map((g) => ({
        group: g.group,
        items: g.items.filter((i) => matchesQuery(i, g.group, query)),
      }))
      .filter((g) => g.items.length > 0),
    [options, query],
  );

  return (
    <Combobox
      store={combobox}
      onOptionSubmit={(val) => {
        if (val === '__custom__') {
          onChange(search);
        } else {
          onChange(val);
        }
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target>
        <InputBase
          data-testid={dataTestId}
          aria-label={ariaLabel}
          label={label}
          description={description}
          placeholder={placeholder}
          disabled={disabled}
          error={showInvalid ? t('fieldSelect.invalidPath') : error}
          value={search}
          rightSection={<Combobox.Chevron />}
          rightSectionPointerEvents="none"
          clearable={clearable}
          onClear={() => onChange('')}
          size={size}
          w={w}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            combobox.openDropdown();
            combobox.updateSelectedOptionIndex();
          }}
          onClick={() => combobox.openDropdown()}
          onFocus={() => combobox.openDropdown()}
          onBlur={() => {
            combobox.closeDropdown();
            setSearch(value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !isKnown) {
              event.preventDefault();
              if (isValidSyntax && search !== '') {
                onChange(search);
                combobox.closeDropdown();
              }
            }
          }}
        />
      </Combobox.Target>
      <Combobox.Dropdown>
        <Combobox.Options mah={280} style={{ overflowY: 'auto' }}>
          {visibleGroups.map((g) => (
            <Combobox.Group key={g.group} label={g.group}>
              {g.items.map((item) => (
                <Combobox.Option key={item.value} value={item.value} active={item.value === value}>
                  {item.label}
                </Combobox.Option>
              ))}
            </Combobox.Group>
          ))}
          {showCustom && (
            <Combobox.Option value="__custom__">
              {t('fieldSelect.customValue', { value: search })}
            </Combobox.Option>
          )}
          {showInvalid && (
            <Combobox.Empty>{t('fieldSelect.invalidPath')}</Combobox.Empty>
          )}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/components/FieldSelect.test.tsx src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: FieldSelect tests PASS; CustomLabelsUI still passes (MatchFieldCombobox untouched until Task 10).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/FieldSelect.tsx frontend/src/components/FieldSelect.test.tsx frontend/public/locales/en/common.json frontend/public/locales/de/common.json
git commit -m "feat: shared FieldSelect component with grouped options, free text, and 1-based validation"
```

---

### Task 10: Migrate the four consumers to FieldSelect

**Files:**
- Modify: `frontend/src/features/setup/MappingTable.tsx`
- Modify: `frontend/src/features/setup/MappingTable.test.tsx`
- Modify: `frontend/src/features/customLabels/MatchFieldCombobox.tsx`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
- Modify: `frontend/src/features/rules/RulesUI.tsx:36-37,204-205`
- Modify: `frontend/src/features/rules/RuleEditor.tsx`
- Modify: `frontend/src/features/rules/__tests__/RulesUI.test.tsx`
- Modify: `frontend/src/features/filter/FilterUI.tsx:59-84`
- Modify: `frontend/src/features/filter/__tests__/FilterUI.test.tsx`
- Fixture-only updates: `frontend/src/features/setup/MappingTab.test.tsx`, `frontend/src/features/setup/SetupPage.test.tsx`, `frontend/src/features/category/RulesTab.test.tsx`, `frontend/src/features/plugin/PluginPage.test.tsx`

**Interfaces:**
- Consumes: `FieldSelect`, `buildFieldOptions`, `fromRegistryAttributes`, `useRegistryAttributes(feedSourceId)` (Tasks 8-9).
- Produces: none (terminal UI task). Acceptance: no options-building logic remains in any of the four files; all four pickers show identical lists for the same feed.

- [ ] **Step 1: Update fixtures first (RED)**

Every `RegistryAttribute` mock in the listed test files gains `max_repeats` (mechanical — scalars/structured get `1` or `0`, repeated get their fixture value); every `SourceField` mock gains `max_repeats: 0`. Example for `MappingTable.test.tsx:20-28`:

```typescript
const registryAttributes: RegistryAttribute[] = [
  { name: 'title', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [], max_repeats: 1 },
  { name: 'description', kind: 'scalar', required: 'optional', sub_fields: [], enum_values: [], max_repeats: 1 },
  { name: 'id', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [], max_repeats: 1 },
  { name: 'installment', kind: 'structured', required: 'optional', sub_fields: [
    { name: 'months', type: 'string', required: 'optional' },
    { name: 'amount', type: 'string', required: 'optional' },
  ], enum_values: [], max_repeats: 1 },
];
```

Add one new behavioral test to `MappingTable.test.tsx`:

```typescript
  it('offers indexed target options for repeated attributes', async () => {
    const repeated: RegistryAttribute[] = [
      ...registryAttributes,
      { name: 'product_detail', kind: 'repeated_structured', required: 'optional',
        sub_fields: [
          { name: 'section_name', type: 'string', required: 'optional' },
          { name: 'attribute_name', type: 'string', required: 'optional' },
        ], enum_values: [], max_repeats: 2 },
    ];
    render(<MappingTable {...defaultProps({ registryAttributes: repeated })} />);
    const user = userEvent.setup();
    const select = screen.getAllByRole('combobox')[0];
    await user.click(select);
    await waitFor(() => {
      expect(screen.getByText('#2 · section_name')).toBeInTheDocument();
    });
  });
```

Run: `npm run typecheck` — fix every mock lacking `max_repeats` mechanically. Run `npm run test -- src/features/setup` — the new index test is RED (MappingTable doesn't offer indexed options yet).

- [ ] **Step 2: Migrate MappingTable (GREEN part 1)**

`frontend/src/features/setup/MappingTable.tsx`:

- Delete `buildTargetOptions` (lines 9-22) and the `SelectOption` type (line 7).
- Delete the `grouped`/`mantineData` construction (lines 73-83).
- Add imports:

```tsx
import { useMemo } from 'react';  // merge with the existing react import
import { FieldSelect } from '../../components/FieldSelect';
import { buildFieldOptions, fromRegistryAttributes } from '../../api/fieldOptions';
```

- Inside the component:

```tsx
  const targetOptions = useMemo(
    () => buildFieldOptions(fromRegistryAttributes(registryAttributes)),
    [registryAttributes],
  );
```

- Replace both `<Select data={mantineData} ...>` blocks (lines 135-144 and 170-179) with:

```tsx
                  <FieldSelect
                    value={targetValue ?? ''}
                    onChange={(val) => onChange(sf.name, val || null)}
                    options={targetOptions}
                    placeholder={t('mapping.table.selectTarget')}
                    error={!!error}
                    clearable
                    data-testid={`target-select-${sf.name}`}
                  />
```

and for sub rows:

```tsx
                        <FieldSelect
                          value={subMapping?.target ?? ''}
                          onChange={(val) => onChange(subKey, val || null)}
                          options={targetOptions}
                          placeholder={t('mapping.table.selectTarget')}
                          error={!!subError}
                          clearable
                          data-testid={`target-select-${subKey}`}
                        />
```

- Remove the now-unused `Select` import from '@mantine/core'.

- [ ] **Step 3: Migrate MatchFieldCombobox (GREEN part 2)**

Replace the whole body of `frontend/src/features/customLabels/MatchFieldCombobox.tsx` (exported name and props unchanged so `CustomLabelsUI` keeps working):

```tsx
import { useTranslation } from 'react-i18next';
import { FieldSelect } from '../../components/FieldSelect';
import { buildFieldOptions, fromRegistryAttributes } from '../../api/fieldOptions';
import type { RegistryAttribute } from '../../api/types';

export function MatchFieldCombobox({
  value,
  onChange,
  attributes,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  attributes: RegistryAttribute[];
  disabled?: boolean;
}) {
  const { t } = useTranslation('customLabels');
  return (
    <FieldSelect
      value={value}
      onChange={onChange}
      options={buildFieldOptions(fromRegistryAttributes(attributes))}
      label={t('fields.matchField')}
      description={t('fields.matchFieldHint')}
      placeholder={t('fields.matchFieldPlaceholder')}
      disabled={disabled}
    />
  );
}
```

- [ ] **Step 4: Migrate RulesUI/RuleEditor (GREEN part 3)**

`frontend/src/features/rules/RulesUI.tsx` — replace lines 36-37:

```tsx
  const registryQuery = useRegistryAttributes(scope.feedSourceId);
  const fieldOptions = useMemo(
    () => buildFieldOptions(fromRegistryAttributes(registryQuery.data ?? [])),
    [registryQuery.data],
  );
```

Import changes: drop `useFeedSourceFields`, add `useRegistryAttributes`; add `buildFieldOptions, fromRegistryAttributes` from `'../../api/fieldOptions'`. Change the `fields={fields}` pass-down (line ~204) to `fieldOptions={fieldOptions}`.

`frontend/src/features/rules/RuleEditor.tsx`:

- Change `RuleEditorProps.fields: string[]` to `fieldOptions: GroupedFieldOptions` (import the type from `'../../api/fieldOptions'`).
- Delete `const fieldData: Option[] = fields.map(...)` (line 104).
- Replace the three field Selects with `FieldSelect` in the same pattern as MappingTable:
  - leaf condition (line ~403): `<FieldSelect aria-label={t('editor.addField')} value={node.field ?? ''} onChange={(v) => patch({ field: v })} options={fieldOptions} w={160} />`
  - then-field (line ~178): same pattern, keep `data-testid={`then-field-${index}`}` and the onChange writing `{ ...action, field: v }`.
  - `ConditionNodeEditor`'s props: `fields: Option[]` → `fieldOptions: GroupedFieldOptions`; its recursive call passes it down unchanged.
- Replace the `fields[0] ?? ''` fallbacks (lines 157, 373) with `fieldOptions[0]?.items[0]?.value ?? ''`.
- Keep `Option` and `opOptions` for the operator Selects (unchanged).

- [ ] **Step 5: Migrate FilterUI (GREEN part 4)**

`frontend/src/features/filter/FilterUI.tsx` — replace lines 59-60:

```tsx
  const registryQuery = useRegistryAttributes(scope.feedSourceId);
  const fieldOptions = useMemo(
    () => buildFieldOptions(fromRegistryAttributes(registryQuery.data ?? [])),
    [registryQuery.data],
  );
```

Delete line 84 (`const fieldData = fields.map(...)`). Replace the condition field Select (lines 166-173) with:

```tsx
            <FieldSelect
              aria-label={t('field')}
              value={condition.field || ''}
              onChange={(v) => patchCondition(index, { field: v })}
              options={fieldOptions}
              w={180}
            />
```

Import changes: drop `useFeedSourceFields`, add `useRegistryAttributes`; add `FieldSelect`, `buildFieldOptions`, `fromRegistryAttributes`.

- [ ] **Step 6: Update remaining test stubs + run the four suites**

In the four consumers' test files, update fetch stubs: registry endpoint responses gain `max_repeats` (and `sub_fields[].kind` where asserted); `/feed-sources/N/fields` stubs are no longer used by RulesUI/FilterUI (they now call `/registry/attributes?feed_source_id=N` — update stubbed URLs accordingly).

```bash
npm run test -- src/features/setup src/features/customLabels src/features/rules src/features/filter src/features/category src/features/plugin
```

Expected: all PASS.

- [ ] **Step 7: Full frontend gates + leftover check**

```bash
npm run typecheck && npm run test && npm run build
```

Verify no leftovers:

```bash
rtk rg -n "buildTargetOptions|fieldData" frontend/src/features   # must return nothing
rtk rg -n "sub_fields.map" frontend/src/features/customLabels/MatchFieldCombobox.tsx   # must return nothing
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features frontend/public/locales
git commit -m "feat!: migrate mapping, labelizer, rules, and filter pickers to shared FieldSelect"
```

---

### Task 11: Backend gates + docs/decisions

**Files:**
- Modify: `docs/decisions.md` (append — never rewrite history)
- Modify: `backend/docs/architecture.md`, `backend/docs/api.md`
- Modify: `frontend/docs/architecture.md`

**Interfaces:** Consumes everything above; produces documentation parity (AGENTS.md rule).

- [ ] **Step 1: Backend full gates**

```bash
cd backend
uv run ruff check .
uv run mypy .
uv run pytest --report-log=.report.jsonl
```

Expected: ruff count unchanged vs baseline; mypy exit 0; pytest green. Fix any fallout before docs.

- [ ] **Step 2: Append decisions.md entries**

Append a `## 2026-09-10 (d)` section at the end of `docs/decisions.md`, following the existing Topic/Decision/Rationale style:

```markdown
## 2026-09-10 (d)

### Unified field list and indexed path grammar

- **Topic:** Shared field selection (Mapping/Rules/Filter/Labelizer) + indexed
  repetition addressing.
- **Decision:** One shared descriptor shape
  `{name, kind, sub_fields[{name, kind?}], max_repeats}` served by
  `GET /feed-sources/{id}/fields` (from the persisted mapping document;
  baselines merged as scalars) and `GET /registry/attributes?feed_source_id=N`
  (per-request `max_repeats` from staged `processed_data` with `raw_data`
  fallback, streamed via `yield_per=1000` — operator directive 1). Path grammar
  is 1-based `attr | attr.sub | attr.N | attr.N.sub`, parsed only by
  `app/mapping/indexed_path.py` (aligns with QC's existing
  `additional_image_link.1` finding grammar). This **supersedes** the
  2026-08-28 decision "positional paths rejected with 422": indexed targets
  are now accepted for `repeated_*` registry kinds; scalar/structured
  attributes still reject indices.
- **Sub-field union clarification:** the 2026-08-25 "M4 XML kind inference"
  entry's first-observed rule applies to kind inference only; sub-fields have
  been the union of observed keys since the original implementation
  (`_infer_source_fields`), now pinned by a regression test.
- **Indexed/broadcast precedence (operator directive 5):** indexed mapping
  targets coexist with whole/broadcast claims (kind-compatible); apply
  evaluates non-indexed mappings first, then indexed assignments sorted by
  target, so indexed values override broadcast values in their exact slot.
  Exact duplicate indexed targets remain blocked.
- **Sparse rendering (operator directive 2):** auto-extended empty dict slots
  never emit empty XML blocks — `[{}, {}, {…}]` renders only the non-empty
  block (regression-pinned in test_export_renderer.py).
- **Breaking change:** `/feed-sources/{id}/fields` now returns descriptors
  instead of `{fields: string[]}` (one-shot cutover; ProductsPage and
  RuleValuesEditor adapted mechanically — RuleValuesEditor semantics
  untouched per scope). Registry route is additive (optional query param +
  new fields).
- **Frontend:** `api/fieldOptions.ts` (adapters + `buildFieldOptions` +
  `INDEXED_PATH_REGEX` client-side validation — operator directive 4) and
  `components/FieldSelect.tsx` (Combobox+InputBase — Mantine Select cannot
  accept free text) are the single option-building authority; the four
  pickers consume registry-with-feed-context so their lists are identical.
  Run-triggering mutations invalidate the `['registry','attributes']` prefix
  (operator directive 3).
- **Rationale:** Four independent option builders produced inconsistent lists
  and no repetition addressing; the QC finding-path grammar, the
  mapping-document source of truth, and per-request repeat derivation close
  the gaps without schema changes or a document version bump.
```

- [ ] **Step 3: Update backend docs**

Read both files first; keep edits minimal and consistent with their entry format.

`backend/docs/architecture.md` — in the ingest/mapping/export sections: add `max_repeats` to the SourceField description, the indexed target grammar to the mapping section, and the per-request registry derivation + `yield_per` note.

`backend/docs/api.md` — replace the `/feed-sources/{id}/fields` entry with the descriptor shape; extend `/registry/attributes` with the optional `feed_source_id` param, `max_repeats`, and sub-field `kind`; note the indexed target grammar on the mapping PUT.

- [ ] **Step 4: Update frontend docs**

`frontend/docs/architecture.md` — add `api/fieldOptions.ts` + `components/FieldSelect.tsx` to the shared-module inventory; note the data-source alignment (four pickers = registry-with-feed-context) and the registry prefix invalidation on run mutations.

- [ ] **Step 5: Full frontend gates + commit**

```bash
cd frontend
npm run typecheck && npm run test && npm run build
cd ..
git add docs/decisions.md backend/docs/architecture.md backend/docs/api.md frontend/docs/architecture.md
git commit -m "docs: unified field list decisions and architecture updates"
```

---

### Task 12: Final verification sweep

**Interfaces:** Consumes the full plan; produces the acceptance verdict.

- [ ] **Step 1: Cross-check acceptance criteria**

1. **Identical lists** — `rtk rg -n "buildFieldOptions" frontend/src` shows it only in `fieldOptions.ts` plus one call site per consumer; `rtk rg -n "buildTargetOptions" frontend/src` returns nothing.
2. **Indexed selectability** — `npm run test -- src/api/fieldOptions.test.ts src/components/FieldSelect.test.tsx src/features/setup` green, including the `#2 · section_name` MappingTable assertion.
3. **"Field" group** — `fieldOptions.test.ts` scalar test green.
4. **Clean XML** — `uv run pytest tests/test_export_renderer.py -v -n0` shows golden + sparse tests green.
5. **No leftover logic** — `rtk rg -n "fieldData" frontend/src/features` empty; `rtk rg -n "sub_fields.map" frontend/src/features/customLabels/MatchFieldCombobox.tsx` empty.
6. **RuleValuesEditor semantics** — `git diff main -- frontend/src/features/customLabels/RuleValuesEditor.tsx` (run from a branch; or `git log -p -1 -- <file>` for the Task 8 commit) shows only the `map((d) => d.name)` adaptation.

- [ ] **Step 2: Full CI parity locally**

```bash
cd backend && uv run ruff check . && uv run mypy . && uv run pytest -q
cd ../frontend && npm run typecheck && npm run test && npm run build
```

Expected: everything green.

- [ ] **Step 3: Final state + push**

```bash
git status --short   # must be clean after previous commits
git log --oneline -14  # one commit per task, reviewable
git push origin main
```

---

## Self-Review (completed during planning)

1. **Spec coverage:** §4 ingest (`max_repeats`) → Tasks 1-2; §4 document/schemas → Task 3; §5.1 utility → Task 4; §5.2 validation/apply/precedence (directive 5) + sparse (directive 2) → Task 5; §6 plugins + products.py mirror → Task 6; §4.4 feed-fields route → Task 7; §7.1-7.4 types/hooks/invalidation (directive 3) + regex (directive 4) → Task 8; §7.3 FieldSelect → Task 9; §7.6-7.7 migrations + mechanical sites → Task 10; §9 docs/decisions → Task 11; §12 acceptance → Task 12. Directive 1 (yield_per) → Task 3. Registry per-request derivation → Task 3. All spec sections have tasks.
2. **Placeholder scan:** no TBD/TODO/"similar to Task N"; every code step carries complete code; the one mid-file correction in Task 5 (pass-2 folding) is written out with the final correct form, not left as an instruction.
3. **Type consistency:** `SourceField.max_repeats` (Task 1) ↔ `ColumnSpec.max_repeats` (Task 2) ↔ document/schema `max_repeats` (Task 3) ↔ `FieldDescriptor.max_repeats` (Task 8) all use the same name and int type. `parse_indexed_path`/`IndexedPath` (Task 4) match the plugin-local `_parse_indexed` tuple shape `(attr, index, sub)` (Task 6). Frontend `GroupedFieldOptions`/`FieldOption` names are identical in Tasks 8, 9, 10.
