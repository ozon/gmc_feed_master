# Lenient TSV Ingest & Baseline-Required Mapping Alert — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make real-world TSV feeds importable (RFC-4180 multi-line cells, annotated headers with registry-unknown sub-fields) and restrict the mapping UI's "required attributes not covered" alert to spec §7 baseline-required attributes only.

**Architecture:** Two independent fixes sharing one theme (leniency where the data is merely variant, strictness where structure is broken). Backend: single-pass `csv.reader` stream parsing in `delimited.py`, header tolerance in `flat_notation.py`, a shared `BASELINE_REQUIRED` constant in `qc/constants.py` surfaced through `/registry/attributes`. Frontend: `MappingTab.tsx` alert filtered by the new `baseline_required` flag with alternative-pair logic. Full-chain regression tests use the real example files copied into test fixtures.

**Tech Stack:** Python 3.11 / FastAPI / pytest (backend); React 19 / TypeScript / vitest (frontend). No new dependencies. No migrations.

**Spec:** `docs/superpowers/specs/2026-09-02-lenient-tsv-ingest-and-baseline-alert-design.md`

## Global Constraints

- Backend commands run from `backend/`: `uv run pytest -n auto` (needs `TEST_DATABASE_URL`), `uv run ruff check .`, `uv run mypy .`.
- Frontend commands run from `frontend/`: `npm run test`, `npm run typecheck`.
- Never mutate `original_product` in plugins; never bypass the per-feed-source run lock; never use reserved plugin routes — not relevant here, but binding.
- `HeaderError` stays for structural header mistakes (duplicate scalar column, non-adjacent repeated structured, annotating a non-structured attribute). ONLY the unknown-sub-field case becomes lenient.
- No new dependencies, no schema changes, no plugin changes, no locale changes (alert keys `mapping.requiredUncovered` / `mapping.requiredUncoveredList` stay).
- Registry data (`backend/registry/attributes.json`) is generated from `gmc_def.md` — do NOT edit it or its parser to add `tax.location_group_name`.
- Docs update in the same commit as behavior changes (repo rule).
- Commit messages: match repo style (see `git log --oneline -10`).
- Python code: no comments unless asked (repo rule: comments only when necessary).

---

### Task 1: Fixtures — copy example feeds into test fixtures

**Files:**
- Create: `backend/tests/fixtures/feeds/multifeed.tsv` (copy of `examples/US-MULTIFEED-2026.tsv`)
- Create: `backend/tests/fixtures/feeds/example_feed.xml` (copy of `examples/feed.xml`)

**Interfaces:**
- Produces: `backend/tests/fixtures/feeds/multifeed.tsv` — 70-column header, 14 logical data rows, quoted cells with embedded newlines, annotated headers `shipping(...)`, `certification(...)`, `tax(country:location_group_name:location_id:postal_code:region:rate:tax_ship)` (sub-field `location_group_name` not in registry `tax`).
- Produces: `backend/tests/fixtures/feeds/example_feed.xml` — RSS 2.0 with `g:` namespace, 308 `<item>`s, per-product varying optional fields (`custom_label_1` on some items only).

- [ ] **Step 1: Copy the files**

```bash
cp examples/US-MULTIFEED-2026.tsv backend/tests/fixtures/feeds/multifeed.tsv
cp examples/feed.xml backend/tests/fixtures/feeds/example_feed.xml
```

- [ ] **Step 2: Verify fixture properties**

```bash
cd backend && uv run python -c "
import csv, io
text = open('tests/fixtures/feeds/multifeed.tsv', newline='', encoding='utf-8').read()
rows = list(csv.reader(io.StringIO(text), delimiter='\t'))
assert len(rows[0]) == 70, len(rows[0])
assert len(rows) == 15, len(rows)
hdr = [h.strip('\"') for h in rows[0]]
assert 'tax(country:location_group_name:location_id:postal_code:region:rate:tax_ship)' in hdr
data = open('tests/fixtures/feeds/example_feed.xml', encoding='utf-8').read()
assert data.count('<item>') == 308, data.count('<item>')
print('fixtures OK')
"
```

Expected: `fixtures OK`

- [ ] **Step 3: Commit**

```bash
git add backend/tests/fixtures/feeds/multifeed.tsv backend/tests/fixtures/feeds/example_feed.xml
git commit -m "test: add real-world example feeds as fixtures"
```

---

### Task 2: RFC-4180 stream parsing in `parse_delimited`

**Files:**
- Modify: `backend/app/ingest/delimited.py` (whole `parse_delimited` body)
- Modify: `backend/app/ingest/flat_notation.py` (`_split_csv_cell` only)
- Test: `backend/tests/test_delimited_reader.py` (add `TestRFC4180`)

**Interfaces:**
- Consumes: `parse_header(headers: list[str], registry) -> HeaderPlan`, `split_row(cells: list[str], plan: HeaderPlan) -> tuple[dict, RowError | None]` (unchanged, from `app/ingest/flat_notation.py`).
- Produces: `parse_delimited(data: bytes, source_format: str, registry: RegistryDocument) -> IngestReport` — same signature, same fields (`products`, `row_errors`, `source_fields`), but RFC-4180-correct. `RowError.line` = physical line number where the logical row ends (reader's `line_num` after the row).
- Produces (new test class): `TestRFC4180` in `tests/test_delimited_reader.py`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_delimited_reader.py` (after `TestBOM`), reusing the file's existing helpers `_registry`, `_scalar`, `_structured`, `_repeated_structured`:

```python
class TestRFC4180:
    def test_quoted_multiline_cell_is_one_row(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "title": _scalar("title"),
            "description": _scalar("description"),
        })
        data = b'id\tdescription\ttitle\n1\t"Line one\nLine two"\tShirt\n'
        report = parse_delimited(data, "tsv", reg)

        assert report.row_errors == []
        assert len(report.products) == 1
        assert report.products[0]["description"] == "Line one\nLine two"
        assert report.products[0]["title"] == "Shirt"

    def test_embedded_newline_row_error_line_points_at_row_end(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "shipping": _repeated_structured("shipping", _SHIPPING_FIELDS),
        })
        data = (
            b"id\tshipping(country:price)\n"
            b'1\t"US:6.49\nUSD"\n'
            b"2\tUS:6.49:extra:more\n"
        )
        report = parse_delimited(data, "tsv", reg)

        assert len(report.products) == 1
        assert len(report.row_errors) == 1
        assert report.row_errors[0].line == 4

    def test_multiline_fixture_parses(self) -> None:
        from registry.loader import load_registry

        reg = load_registry()
        data = (_FIXTURES / "multifeed.tsv").read_bytes()
        report = parse_delimited(data, "tsv", reg)

        assert len(report.products) == 14
        assert report.row_errors == []
        first = report.products[0]
        assert first["id"].startswith("shopify_US_")
        assert "\n" not in first["title"]
        assert "shipping" in first and isinstance(first["shipping"], dict)
        assert isinstance(first["additional_image_link"], list)
```

Notes on these tests:
- The second test uses the ANNOTATED header `shipping(country:price)` — a bare structured header plans as `generic` (deliberate behavior from commit `60e6eb0`, spec §5.8: "bare structured columns parse as generic") and would never colon-validate. Row 1 (`1\t"US:6.49\nUSD"`) is a valid quoted cell spanning physical lines 2–3 (no parse error); the bad row `2\tUS:6.49:extra:more` (surplus colons for a 2-sub-field plan) ends on physical line 4 → `RowError.line == 4`. Also assert `len(report.products) == 1` (the valid multi-line row survives). This proves line numbers count PHYSICAL lines even after a multi-line row.
- The third test asserts `isinstance(first["shipping"], dict)` — a single annotated `shipping(...)` column plans as `structured` (dict). The dict is wrapped to `[dict]` later by `apply_mapping` (REPEATED_STRUCTURED target), so the full chain still yields a list where it matters. `title` is single-line in the data (only `description` cells contain newlines).

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_delimited_reader.py::TestRFC4180 -v
```

Expected: all three FAIL — the first two because multi-line quoted cells get shredded by the current line-splitting implementation (wrong product counts / wrong line numbers), the third (`test_multiline_fixture_parses`) with `HeaderError: unknown sub-field 'location_group_name'` (Task 3 not applied yet — expected; the rest of that test's assertions never run).

- [ ] **Step 3: Rewrite `parse_delimited`**

Replace the entire body of `parse_delimited` in `backend/app/ingest/delimited.py`. The final file must be exactly:

```python
from __future__ import annotations

import csv
import io

from registry.model import RegistryDocument

from .flat_notation import HeaderError, parse_header, split_row
from .report import IngestReport, RowError, SourceField


def _detect_delimiter(source_format: str, sample: str) -> str:
    if source_format in ("tsv", "wide_tsv"):
        return "\t"
    if source_format == "csv":
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            return dialect.delimiter
        except csv.Error:
            return ","
    raise ValueError(f"unsupported source format: {source_format!r}")


def parse_delimited(
    data: bytes, source_format: str, registry: RegistryDocument
) -> IngestReport:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]

    text = data.decode("utf-8")
    first_line = text.split("\n", 1)[0]
    delimiter = _detect_delimiter(source_format, first_line)

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    parsed: list[tuple[int, list[str]]] = []
    for cells in reader:
        if any(cell.strip() for cell in cells):
            parsed.append((reader.line_num, cells))

    if not parsed:
        return IngestReport()

    plan = parse_header(parsed[0][1], registry)

    source_fields = [
        SourceField(
            name=spec.name,
            kind="scalar" if spec.kind == "generic" else spec.kind,
            sub_fields=tuple(spec.sub_fields),
        )
        for spec in plan.columns
    ]

    products: list[dict] = []
    row_errors: list[RowError] = []

    for line, cells in parsed[1:]:
        product, error = split_row(cells, plan)
        if error is not None:
            row_errors.append(RowError(line=line, message=error.message))
        else:
            products.append(product)

    return IngestReport(
        products=products, row_errors=row_errors, source_fields=source_fields
    )
```

Notes:
- `io.StringIO(text, newline="")` — the `newline=""` argument is REQUIRED so `csv.reader` sees raw newlines inside quoted cells (mirrors the documented `open(..., newline="")` contract for csv module).
- Keep the `HeaderError` import even though `parse_delimited` no longer catches it — `from app.ingest.delimited import HeaderError` must keep working for any external importer.
- `line_num` is captured after the row is consumed → for multi-line rows it points at the physical line where the row ENDS. Single-line rows keep the exact same numbers as the old implementation (existing test `TestMalformedRows` asserts `line == 2` and must keep passing).

**Also fix `_split_csv_cell` in `backend/app/ingest/flat_notation.py` (same commit).** Its current `csv.reader(io.StringIO(cell))` treats embedded newlines as record boundaries, so a scalar cell value that legitimately contains `\n` (delivered intact by the new stream parser, quotes stripped by the outer TSV pass) gets truncated to its first physical line — the description from `US-MULTIFEED-2026.tsv` would lose content. `csv.reader` is the wrong tool here (record semantics); replace it with a quote-aware comma scanner that preserves ALL existing behavior:

Replace `_split_csv_cell` (and remove the now-unused `csv`/`io` imports ONLY if nothing else in the file uses them — `parse_header` does not, but check `split_row` and the module header first) with:

```python
def _split_csv_cell(cell: str) -> list[str] | str:
    """Split a cell by comma, respecting RFC-4180 quoting.

    Returns a list if the cell contains commas (split or quoted).
    Returns a bare string if it's a single unquoted value.
    """
    parts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    for ch in cell:
        if ch == '"':
            in_quotes = not in_quotes
            continue
        if ch == "," and not in_quotes:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    if len(parts) == 1 and not (cell.startswith('"') and cell.endswith('"')):
        return parts[0]
    return parts
```

Behavior parity (verified against the current implementation — the existing tests `test_comma_separated`, `test_quoted_comma_preserved`, `test_single_value_no_split` in `tests/test_flat_notation.py` must keep passing):

| input | old | new |
|---|---|---|
| `'a,b'` | `['a', 'b']` | `['a', 'b']` |
| `'"quoted,comma"'` | `['quoted,comma']` | `['quoted,comma']` |
| `'img1.jpg'` | `'img1.jpg'` | `'img1.jpg'` |
| `'"img1.jpg,img2.jpg"'` | `['img1.jpg,img2.jpg']` | `['img1.jpg,img2.jpg']` |
| `'"single"'` | `['single']` | `['single']` |
| `''` | `''` | `''` |
| `'Line one\nLine two'` | `'Line one'` (BUG) | `'Line one\nLine two'` |

- [ ] **Step 4: Run the full delimited/flat test suites**

```bash
cd backend && uv run pytest tests/test_delimited_reader.py tests/test_flat_notation.py -v
```

Expected: `TestRFC4180` tests 1 and 2 PASS; `test_multiline_fixture_parses` still FAILS with `HeaderError` (unknown sub-field `location_group_name`) — that is Task 3. All pre-existing tests except `TestRepeatedScalar::test_comma_split` must PASS — especially `TestMalformedRows::test_bad_row_skipped_populates_errors` asserting `err.line == 2` (single-line rows keep exact old line numbers). `TestRepeatedScalar::test_comma_split` MAY still pass at this stage (old code comma-splits every scalar cell, and its synthetic registry declares `additional_image_link` as scalar — Task 5A amends that test's registry to repeated_scalar and makes splitting kind-aware). Do not fix it here.

If any pre-existing test fails, the implementation drifted — fix before committing.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/delimited.py backend/app/ingest/flat_notation.py backend/tests/test_delimited_reader.py
git commit -m "fix: RFC-4180 stream parsing for quoted multi-line cells in delimited reader"
```

---

### Task 3: Header leniency for unknown annotated sub-fields

**Files:**
- Modify: `backend/app/ingest/flat_notation.py:62-70` (annotated branch of `parse_header`)
- Test: `backend/tests/test_flat_notation.py` (modify `TestParseHeaderUnknownSubFieldError`, add `TestParseHeaderLenientSubFields`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_header` no longer raises on unknown annotated sub-fields; `ColumnSpec.sub_fields` = exactly the header-declared list, order preserved. Strict errors remain for: duplicate scalar columns, non-adjacent repeated structured, annotating a non-structured registry attribute.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_flat_notation.py`:

1. Replace the entire `TestParseHeaderUnknownSubFieldError` class with:

```python
class TestParseHeaderLenientSubFields:
    def test_unknown_sub_field_is_kept_positionally(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(["shipping(country:unknown_thing:price)"], reg)
        assert plan.columns == [
            ColumnSpec(
                name="shipping",
                kind="structured",
                sub_fields=["country", "unknown_thing", "price"],
            ),
        ]

    def test_unknown_sub_field_value_alignment_preserved(self) -> None:
        reg = _registry({
            "shipping": _structured("shipping", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("price", "Price", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(["shipping(country:unknown_thing:price)"], reg)
        result, err = split_row(["US:middle:6.49 USD"], plan)
        assert err is None
        assert result == {"shipping": {"country": "US", "unknown_thing": "middle", "price": "6.49 USD"}}

    def test_registry_known_attribute_with_unknown_subfields_repeats_ok(self) -> None:
        reg = _registry({
            "tax": _structured("tax", (
                SubField("country", "String", RequirementStatus.REQUIRED),
                SubField("rate", "String", RequirementStatus.OPTIONAL),
                SubField("tax_ship", "Boolean", RequirementStatus.OPTIONAL),
            )),
        })
        plan = parse_header(
            ["tax(country:location_group_name:rate:tax_ship)", "tax(country:location_group_name:rate:tax_ship)"],
            reg,
        )
        assert plan.columns == [
            ColumnSpec(
                name="tax",
                kind="repeated_structured",
                sub_fields=["country", "location_group_name", "rate", "tax_ship"],
                arity=2,
            ),
        ]
```

2. Add a strictness regression guard (new class, after `TestParseHeaderDuplicateScalarError`):

```python
class TestParseHeaderStillStrict:
    def test_annotating_non_structured_attribute_raises(self) -> None:
        reg = _registry({
            "title": _scalar("title"),
        })
        with pytest.raises(HeaderError, match="non-structured"):
            parse_header(["title(a:b)"], reg)

    def test_duplicate_scalar_raises(self) -> None:
        reg = _registry({
            "title": _scalar("title"),
        })
        with pytest.raises(HeaderError, match="title"):
            parse_header(["title", "title"], reg)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_flat_notation.py::TestParseHeaderLenientSubFields -v
```

Expected: first two FAIL with `HeaderError` (unknown sub-field `unknown_thing`), third FAIL with `HeaderError` (`unknown sub-field 'location_group_name'`). `TestParseHeaderStillStrict` passes already (guards against over-lenience).

- [ ] **Step 3: Remove the unknown-sub-field check**

In `backend/app/ingest/flat_notation.py`, inside `parse_header`'s annotated branch, delete exactly this block:

```python
                registry_field_names = {f.name for f in attr.fields}
                for sf in sub_fields:
                    if sf not in registry_field_names:
                        raise HeaderError(
                            f"Column '{header}' references unknown sub-field '{sf}'",
                            column=header,
                        )
```

(Keep the `attr.kind not in (STRUCTURED, REPEATED_STRUCTURED)` check directly above it — annotating a non-structured attribute stays an error.)

- [ ] **Step 4: Run the full flat-notation + delimited suites**

```bash
cd backend && uv run pytest tests/test_flat_notation.py tests/test_delimited_reader.py -v
```

Expected: ALL PASS, including `TestRFC4180::test_multiline_fixture_parses` from Task 2 (the real multifeed.tsv now parses: 14 products, 0 row errors, `shipping` dict present, `additional_image_link` list).

Also run the ingest-step integration tests to catch anything that relied on the old strictness:

```bash
cd backend && uv run pytest tests/test_ingest_step.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/flat_notation.py backend/tests/test_flat_notation.py
git commit -m "fix: tolerate registry-unknown sub-fields in annotated flat-notation headers"
```

---

### Task 4: Shared baseline-required constants + registry API flag

**Files:**
- Modify: `backend/app/qc/constants.py` (append constants)
- Modify: `backend/app/qc/rules.py:11-14` (`BaselineRequired._REQUIRED`)
- Modify: `backend/app/schemas/field_mapping.py:42-48` (`RegistryAttributeOut`)
- Modify: `backend/app/routes/registry.py:13-32` (`list_registry_attributes`)
- Test: `backend/tests/test_registry_api.py` (extend shape test, add flag test)
- Test: `backend/tests/test_qc_rules.py` (no new tests needed — behavior unchanged — just confirm suite passes)

**Interfaces:**
- Produces: `app/qc/constants.py` exports `BASELINE_REQUIRED: tuple[str, ...] = ("id", "link", "image_link", "availability", "price", "condition")` and `BASELINE_ALTERNATIVE_PAIRS: tuple[tuple[str, str], ...] = (("title", "structured_title"), ("description", "structured_description"))`.
- Produces: `GET /registry/attributes` items gain `"baseline_required": bool` — true iff `name in BASELINE_REQUIRED or name in {m for pair in BASELINE_ALTERNATIVE_PAIRS for m in pair}`.

- [ ] **Step 1: Write the failing API test**

In `backend/tests/test_registry_api.py`, modify `test_registry_attributes_returns_list_with_expected_shape` (line 68):

```python
        assert set(item.keys()) == {"name", "kind", "required", "sub_fields", "enum_values", "baseline_required"}
```

And append this test at the end of the file:

```python
async def test_registry_attributes_baseline_required_flag(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/registry/attributes")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {a["name"]: a for a in body}

    assert by_name["id"]["baseline_required"] is True
    assert by_name["link"]["baseline_required"] is True
    assert by_name["image_link"]["baseline_required"] is True
    assert by_name["availability"]["baseline_required"] is True
    assert by_name["price"]["baseline_required"] is True
    assert by_name["condition"]["baseline_required"] is True
    assert by_name["title"]["baseline_required"] is True
    assert by_name["structured_title"]["baseline_required"] is True
    assert by_name["description"]["baseline_required"] is True
    assert by_name["structured_description"]["baseline_required"] is True

    assert by_name["brand"]["baseline_required"] is False
    assert by_name["vin"]["baseline_required"] is False
    assert by_name["store_code"]["baseline_required"] is False
    assert by_name["gtin"]["baseline_required"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_registry_api.py::test_registry_attributes_baseline_required_flag tests/test_registry_api.py::test_registry_attributes_returns_list_with_expected_shape -v
```

Expected: FAIL — `baseline_required` missing from response (`KeyError` or key-set mismatch).

- [ ] **Step 3: Implement the constants and wire the flag**

Append to `backend/app/qc/constants.py`:

```python
BASELINE_REQUIRED: tuple[str, ...] = (
    "id",
    "link",
    "image_link",
    "availability",
    "price",
    "condition",
)

BASELINE_ALTERNATIVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("title", "structured_title"),
    ("description", "structured_description"),
)
```

In `backend/app/qc/rules.py`, replace the class attribute of `BaselineRequired` (lines 11-14):

```python
class BaselineRequired:
    rule_id = "baseline_required"
    _REQUIRED = BASELINE_REQUIRED
```

and add to the imports at the top of the file:

```python
from .constants import (
    BASELINE_REQUIRED,
    EXEMPT_TAXONOMY_IDS,
    IMAGE_FORMATS,
    IMAGE_SIZE_ENFORCEMENT_DATE,
)
```

(Replace the existing `from .constants import EXEMPT_TAXONOMY_IDS, IMAGE_FORMATS, IMAGE_SIZE_ENFORCEMENT_DATE` line.)

In `backend/app/schemas/field_mapping.py`, add the field to `RegistryAttributeOut`:

```python
class RegistryAttributeOut(BaseModel):
    name: str
    kind: str
    required: str
    baseline_required: bool
    sub_fields: list[RegistrySubFieldOut]
    enum_values: list[str]
```

In `backend/app/routes/registry.py`, import the constants and set the flag:

```python
from ..qc.constants import BASELINE_ALTERNATIVE_PAIRS, BASELINE_REQUIRED
```

and inside `list_registry_attributes`, replace the comprehension body:

```python
    baseline_names = set(BASELINE_REQUIRED)
    for pair in BASELINE_ALTERNATIVE_PAIRS:
        baseline_names.update(pair)
    return [
        RegistryAttributeOut(
            name=attribute.name,
            kind=attribute.kind.value,
            required=attribute.required.value,
            baseline_required=attribute.name in baseline_names,
            sub_fields=[
                RegistrySubFieldOut(
                    name=sub.name,
                    type=sub.type,
                    required=sub.required.value,
                )
                for sub in attribute.fields
            ],
            enum_values=list(attribute.enum_values),
        )
        for attribute in sorted(registry.attributes.values(), key=lambda attr: attr.name)
    ]
```

- [ ] **Step 4: Run backend tests**

```bash
cd backend && uv run pytest tests/test_registry_api.py tests/test_qc_rules.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
cd backend && uv run ruff check . && uv run mypy .
```

Expected: clean.

```bash
git add backend/app/qc/constants.py backend/app/qc/rules.py backend/app/schemas/field_mapping.py backend/app/routes/registry.py backend/tests/test_registry_api.py
git commit -m "feat: expose baseline_required flag on registry attributes"
```

---

### Task 5A: Kind-aware comma splitting (registry-truth fix)

**Files:**
- Modify: `backend/app/ingest/flat_notation.py` (bare-header kind inference + `split_row` scalar branch)
- Test: `backend/tests/test_flat_notation.py`, `backend/tests/test_delimited_reader.py` (amend synthetic registries; add split-behavior tests)

**Interfaces:**
- Consumes: `registry.attributes[name].kind` (SCALAR vs REPEATED_SCALAR for bare headers).
- Produces: `ColumnSpec.kind` may now be `"repeated_scalar"`; `split_row` comma-splits ONLY `repeated_scalar` columns (scalar/generic cells stay whole strings — commas are content); `SourceField.kind` for such columns is `"repeated_scalar"` (passes through `_COMPATIBLE_KINDS["repeated_scalar"] = {"repeated_scalar"}` for same-named targets).

**Why (verified live):** spec §5.8 says "Comma-separated cell values → repeated scalar" — comma-splitting belongs to REPEATED_SCALAR columns only. Current code splits EVERY scalar/generic cell, so 13/14 `multifeed.tsv` descriptions (free text with commas) become lists and `apply_mapping` DROPS them (scalar shape mismatch). The user's feed loses its descriptions. With the fix: `description` (registry SCALAR) stays a string; `additional_image_link` (registry REPEATED_SCALAR, 14/14 rows comma-separated URLs) still splits.

- [ ] **Step 1: Write/amend the tests**

In `backend/tests/test_flat_notation.py`:

1. `TestSplitRowRepeatedScalar`: change all three plans' `kind="scalar"` to `kind="repeated_scalar"` (columns named `additional_image_link`; the split cases and `single_value_no_split` keep their inputs/asserts — a single value still yields a bare string: `{"additional_image_link": "img3.jpg"}`).
2. Add:

```python
class TestSplitRowScalarKeepsCommas:
    def test_scalar_cell_with_commas_stays_whole(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="description", kind="scalar", sub_fields=[]),
        ])
        result, err = split_row(["Classic, confident, crafted"], plan)
        assert result == {"description": "Classic, confident, crafted"}
        assert err is None

    def test_generic_cell_with_commas_stays_whole(self) -> None:
        plan = HeaderPlan(columns=[
            ColumnSpec(name="internal_note", kind="generic", sub_fields=[]),
        ])
        result, err = split_row(["note one, note two"], plan)
        assert result == {"internal_note": "note one, note two"}
        assert err is None
```

3. `TestParseHeaderBareScalar` etc. stay unchanged (plain scalars plan `scalar`). Add:

```python
class TestParseHeaderBareRepeatedScalar:
    def test_bare_repeated_scalar_attribute_kind(self) -> None:
        reg = _registry({
            "additional_image_link": RegistryAttribute(
                name="additional_image_link",
                kind=AttributeKind.REPEATED_SCALAR,
                type="URL",
                required=RequirementStatus.OPTIONAL,
                domain=FeedDomain.PRIMARY,
                export_status=ExportStatus.EXPORTABLE,
            ),
        })
        plan = parse_header(["additional_image_link"], reg)
        assert plan.columns == [
            ColumnSpec(name="additional_image_link", kind="repeated_scalar", sub_fields=[]),
        ]
```

(If `test_flat_notation.py` lacks an `_repeated_scalar` helper, build the `RegistryAttribute` inline as above — do NOT add a helper for one use.)

In `backend/tests/test_delimited_reader.py`:

4. `TestRepeatedScalar::test_comma_split`: change the registry entry from `_scalar("additional_image_link")` to a repeated-scalar attribute:

```python
def _repeated_scalar(name: str) -> RegistryAttribute:
    return RegistryAttribute(
        name=name,
        kind=AttributeKind.REPEATED_SCALAR,
        type="URL",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=ExportStatus.EXPORTABLE,
    )
```

(Add this helper next to `_scalar`; the existing imports already cover `AttributeKind`, `ExportStatus`, `FeedDomain`, `RegistryAttribute`, `RequirementStatus` — keep the fixture's assertions unchanged: `["img1.jpg", "img2.jpg"]` and bare `"img3.jpg"`.)

5. Add after `TestRFC4180`:

```python
class TestScalarCommaContent:
    def test_scalar_description_with_commas_not_split(self) -> None:
        reg = _registry({
            "id": _scalar("id"),
            "description": _scalar("description"),
        })
        data = b"id\tdescription\n1\tClassic, confident, crafted\n"
        report = parse_delimited(data, "tsv", reg)

        assert report.row_errors == []
        assert len(report.products) == 1
        assert report.products[0]["description"] == "Classic, confident, crafted"
```

- [ ] **Step 2: Verify RED**

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_flat_notation.py tests/test_delimited_reader.py -q
```

Expected: new tests FAIL (scalar/generic cells currently comma-split; bare repeated_scalar headers plan as `scalar`); the amended `TestSplitRowRepeatedScalar`/`TestRepeatedScalar` FAIL (old kind no longer splits after… no wait — at RED stage the OLD code splits everything, so the amended repeated-scalar tests still PASS at RED; only the four NEW tests fail: `test_scalar_cell_with_commas_stays_whole`, `test_generic_cell_with_commas_stays_whole`, `test_bare_repeated_scalar_attribute_kind`, `test_scalar_description_with_commas_not_split`).

- [ ] **Step 3: Implement**

In `backend/app/ingest/flat_notation.py`:

1. Bare-header kind inference (currently: structured kinds → `generic`, everything else → `scalar`) becomes:

```python
            attr = registry.attributes.get(header)
            if attr is not None:
                if attr.kind in (
                    AttributeKind.STRUCTURED,
                    AttributeKind.REPEATED_STRUCTURED,
                ):
                    kind = "generic"
                elif attr.kind is AttributeKind.REPEATED_SCALAR:
                    kind = "repeated_scalar"
                else:
                    kind = "scalar"
            else:
                kind = "generic"
```

2. `split_row`'s else-branch (scalar/generic) becomes:

```python
        else:
            # scalar, repeated_scalar or generic
            cell = cells[col_idx] if col_idx < len(cells) else ""
            col_idx += 1
            if not cell:
                continue
            if spec.kind == "repeated_scalar":
                values = _split_csv_cell(cell)
            else:
                values = cell
            result[spec.name] = values
```

(Keep the comment exactly as shown — it replaces the old `# scalar or generic` comment.)

3. `delimited.py` `source_fields` mapping is UNCHANGED — spec.kind is now `"scalar"`, `"repeated_scalar"`, `"structured"`, `"repeated_structured"`, or `"generic"`; the existing `kind="scalar" if spec.kind == "generic" else spec.kind` passes `repeated_scalar` through correctly.

- [ ] **Step 4: Verify GREEN**

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_flat_notation.py tests/test_delimited_reader.py tests/test_ingest_step.py tests/test_mapping_matcher.py -q
```

Expected: ALL PASS (amended + new + all pre-existing).

- [ ] **Step 5: Run full suite, commit**

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto
```

Expected: 0 failures.

```bash
git add backend/app/ingest/flat_notation.py backend/tests/test_flat_notation.py backend/tests/test_delimited_reader.py
git commit -m "fix: comma-split only repeated-scalar columns; scalar cells keep commas as content"
```

---

### Task 5B: Full-chain regression tests with the real example feeds (registry-true scope)

**Files:**
- Create: `backend/tests/test_example_feed_chain.py`

**Interfaces:**
- Consumes: `read_feed(data, source_format, registry) -> IngestReport` (`app/ingest/__init__.py`); `auto_match(source_fields, registry, existing=None) -> dict[str, MappingEntry]` (`app/mapping/matcher.py`); `apply_mapping(product, mappings, registry)` (`app/mapping/apply.py`); `render_feed(products, registry, channel)` (`app/export/renderer.py`); `BaselineRequired` (`app/qc/rules.py`); `load_registry()` (`registry/loader.py`); `QcContext(feed_source_id, currency, volume_drop_threshold_pct, registry, clock, image_probe, previous_export_run)` (`app/qc/engine.py`).
- Produces: proof that both real example feeds survive parse → auto-map → apply → QC → render.

Verified facts the assertions rely on (registry-true, re-verified after Task 5A):
- REGISTRY GAP (recorded as follow-up, do NOT work around): the registry contains ONLY `custom_label_0` and `custom_label_4` — the parser never expanded the `` `custom_label_0` … `custom_label_4` `` name range (gmc_def.md:127), so `custom_label_1/2/3` do not exist. `auto_match` therefore does NOT claim `custom_label_1` — the source field stays unmapped and its values are dropped (dropped_unmapped). That is the current, correct lenient behavior; the feeds still work end-to-end.
- TSV: 70-col header, 14 logical rows, 0 row errors; `custom_label_1` column EMPTY in all rows (so even after a future registry fix, no product data); `tax` column empty in all rows → no `tax` key in any product; `shipping` populated in 13/14 rows as a dict at ingest, wrapped to `[dict]` by `apply_mapping` (REPEATED_STRUCTURED target); after Task 5A, `description` stays a whole string in all 14 products (all baseline fields present in every row → 0 baseline findings); `additional_image_link` comma-splits to a list (registry REPEATED_SCALAR).
- XML: 308 products; `custom_label_0` present on some products (registry-true check — 0 items carry `custom_label_1` post-mapping since it's unmapped); the fixture itself is missing data on some products: 9 products missing ≥1 hard baseline field, 18 missing the description pair → `BaselineRequired` yields EXACTLY 27 findings (9 hard-field + 18 description-pair; 0 title-pair). These findings are the system working as designed (real feed, real gaps) — the test asserts the exact count, NOT zero.

- [ ] **Step 1: Write the chain test file**

Create `backend/tests/test_example_feed_chain.py` (complete file — `_make_ctx` copied from `tests/test_qc_rules.py`, `BaselineRequired.check` is async so the module uses `pytestmark = pytest.mark.asyncio` and the chain tests are `async def`):

```python
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.clock import TestClock
from app.export.renderer import ChannelMetadata, render_feed
from app.ingest import read_feed
from app.mapping.apply import apply_mapping
from app.mapping.matcher import auto_match
from app.qc.engine import QcContext
from app.qc.rules import BaselineRequired
from registry.loader import load_registry
from registry.model import RegistryDocument

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "feeds"


def _make_ctx() -> QcContext:
    return QcContext(
        feed_source_id=1,
        currency="USD",
        volume_drop_threshold_pct=20,
        registry=RegistryDocument(attributes={}),
        clock=TestClock(datetime(2026, 6, 1, tzinfo=timezone.utc)),
        image_probe=AsyncMock(),
        previous_export_run=None,
    )


async def _baseline_findings(products: list[dict]) -> list:
    rule = BaselineRequired()
    findings = []
    for product in products:
        findings.extend(await rule.check(product, _make_ctx()))
    return [f for f in findings if f.rule_id == "baseline_required"]


class TestMultifeedTsvChain:
    async def test_full_chain(self) -> None:
        data = (_FIXTURES / "multifeed.tsv").read_bytes()
        registry = load_registry()
        report = read_feed(data, "tsv", registry)

        assert len(report.products) == 14
        assert report.row_errors == []

        mappings = auto_match(report.source_fields, registry)
        for source, target in [
            ("id", "id"),
            ("title", "title"),
            ("description", "description"),
            ("link", "link"),
            ("image_link", "image_link"),
            ("price", "price"),
            ("availability", "availability"),
            ("condition", "condition"),
            ("brand", "brand"),
            ("gtin", "gtin"),
            ("shipping", "shipping"),
        ]:
            assert mappings[source].target == target, source

        mapped_products = []
        for product in report.products:
            mapped, _stats = apply_mapping(product, mappings, registry)
            mapped_products.append(mapped)

        first = mapped_products[0]
        assert isinstance(first["shipping"], list)
        assert first["shipping"][0]["country"] == "US"
        assert first["shipping"][0]["price"] == "14.99 USD"
        assert "location_group_name" not in first["shipping"][0]

        for product in mapped_products:
            assert isinstance(product["description"], str)
            assert "," in product["description"]
            assert "tax" not in product
            assert "custom_label_1" not in product

        assert await _baseline_findings(mapped_products) == []

        xml = render_feed(
            mapped_products,
            registry,
            ChannelMetadata(title="t", link="https://example.com", description="d"),
        )
        text = xml.decode("utf-8")
        assert text.count("<item>") == 14
        assert "<g:id>shopify_US_" in text
        assert "<g:description>" in text


class TestExampleXmlChain:
    async def test_full_chain(self) -> None:
        data = (_FIXTURES / "example_feed.xml").read_bytes()
        registry = load_registry()
        report = read_feed(data, "xml", registry)

        assert len(report.products) == 308
        assert report.row_errors == []

        mappings = auto_match(report.source_fields, registry)
        assert mappings["id"].target == "id"
        assert mappings["title"].target == "title"
        assert mappings["description"].target == "description"

        mapped_products = []
        for product in report.products:
            mapped, _stats = apply_mapping(product, mappings, registry)
            mapped_products.append(mapped)

        findings = await _baseline_findings(mapped_products)
        assert len(findings) == 27
        assert all(f.severity == "critical" for f in findings)

        xml = render_feed(
            mapped_products,
            registry,
            ChannelMetadata(title="t", link="https://example.com", description="d"),
        )
        text = xml.decode("utf-8")
        assert text.count("<item>") == 308
        assert "<g:custom_label_0>" in text
```

- [ ] **Step 2: Run the chain tests**

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_example_feed_chain.py -v
```

Expected: 2 PASS. Troubleshooting notes:
- If `mappings["gtin"]` fails: `gtin` is registry REPEATED_SCALAR and the TSV `gtin` column plans (after Task 5A) as `repeated_scalar` → `_COMPATIBLE_KINDS["repeated_scalar"] = {"repeated_scalar"}` → claim succeeds. A failure means Task 5A's kind inference regressed.
- If `"," in product["description"]` fails for some product: Task 5A's comma-content fix regressed.
- If the XML findings count ≠ 27: count per-field — 9 hard-baseline (id/link/image_link/availability/price/condition) + 18 description-pair + 0 title-pair. Do not weaken the count; investigate which field's mapping changed.
- `assert "<g:description>" in text` (TSV): descriptions survive to export — the exact regression this cycle fixes.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_example_feed_chain.py
git commit -m "test: full-chain regression with real example feeds (tsv + xml)"
```

---

### Task 6: Frontend — baseline-only required-uncovered alert

**Files:**
- Modify: `frontend/src/api/types.ts:78-84` (`RegistryAttribute`)
- Modify: `frontend/src/features/setup/MappingTab.tsx:80-90` (`requiredUncovered`)
- Test: `frontend/src/features/setup/MappingTab.test.tsx`

**Interfaces:**
- Consumes: `RegistryAttribute` now has `baseline_required?: boolean` from `/registry/attributes` (Task 4).
- Produces: `requiredUncovered: string[]` — baseline attrs only; pair members covered iff either member mapped; uncovered pairs list both members.

- [ ] **Step 1: Update the type**

In `frontend/src/api/types.ts`, change `RegistryAttribute`:

```typescript
export type RegistryAttribute = {
  name: string;
  kind: string;
  required: string;
  baseline_required?: boolean;
  sub_fields: RegistrySubField[];
  enum_values: string[];
};
```

- [ ] **Step 2: Write the failing tests**

In `frontend/src/features/setup/MappingTab.test.tsx`:

1. Update `registryAttrs` fixture — add `baseline_required` to every entry:

```typescript
const registryAttrs: RegistryAttribute[] = [
  { name: 'title', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'description', kind: 'scalar', required: 'optional', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'id', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'brand', kind: 'scalar', required: 'required', baseline_required: false, sub_fields: [], enum_values: [] },
  { name: 'installment', kind: 'structured', required: 'optional', baseline_required: false, sub_fields: [
    { name: 'months', type: 'string', required: 'optional' },
    { name: 'amount', type: 'string', required: 'optional' },
  ], enum_values: [] },
];
```

2. Replace the test `shows required-uncovered alert for uncovered required attrs` (lines 116-127) with:

```typescript
  it('shows required-uncovered alert for uncovered baseline attrs only', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(mappingDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    expect(await screen.findByText(/required registry attributes not covered/i)).toBeInTheDocument();
    expect(screen.getAllByText(/id/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/brand/i)).not.toBeInTheDocument();
  });
```

3. Add a pair-coverage test after it:

```typescript
  it('structured_title alone covers the title pair', async () => {
    const altDoc: FieldMappingDoc = {
      ...mappingDoc,
      mappings: {
        title: { target: 'structured_title', origin: 'auto' },
        description: { target: 'description', origin: 'auto' },
        product_id: { target: 'id', origin: 'auto' },
      },
    };
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(altDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.queryByText(/required registry attributes not covered/i)).not.toBeInTheDocument();
    });
  });
```

Note on the existing test at lines 270-295 (`required-uncovered alert disappears when all required attrs are covered`): under the new logic the alert fires for every uncovered BASELINE attr, and its current `fullyCoveredDoc` only maps `title`/`description`/`id`/`brand` — but `brand` no longer counts and the registry fixture lacks `link`, `image_link`, `availability`, `price`, `condition`. Rewrite that test: keep the same `registryAttrs` fixture (it now has `baseline_required` flags), and change `fullyCoveredDoc` to map every baseline attr — replace its `mappings` and extend `source_fields` with:

```typescript
    const fullyCoveredDoc: FieldMappingDoc = {
      ...mappingDoc,
      source_fields: [
        ...mappingDoc.source_fields,
        { name: 'link', kind: 'scalar', sub_fields: [] },
        { name: 'image_link', kind: 'scalar', sub_fields: [] },
        { name: 'availability', kind: 'scalar', sub_fields: [] },
        { name: 'price', kind: 'scalar', sub_fields: [] },
        { name: 'condition', kind: 'scalar', sub_fields: [] },
      ],
      mappings: {
        title: { target: 'title', origin: 'auto' },
        description: { target: 'description', origin: 'auto' },
        product_id: { target: 'id', origin: 'auto' },
        synonym_field: { target: 'brand', origin: 'manual' },
        link: { target: 'link', origin: 'auto' },
        image_link: { target: 'image_link', origin: 'auto' },
        availability: { target: 'availability', origin: 'auto' },
        price: { target: 'price', origin: 'auto' },
        condition: { target: 'condition', origin: 'auto' },
      },
    };
```

The registry fixture must also contain those baseline attrs for the covered/uncovered math to be exercised — the `registryAttrs` in Step 2.1 above already lists `title`, `description`, `id` as baseline; ADD these entries to `registryAttrs` as well:

```typescript
  { name: 'link', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'image_link', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'availability', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'price', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'condition', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'structured_title', kind: 'structured', required: 'optional', baseline_required: true, sub_fields: [], enum_values: [] },
```

With those in place, also update the first test's expectation (`shows required-uncovered alert for uncovered baseline attrs only`): the uncovered baseline set for the ORIGINAL `mappingDoc` (maps title, description, id only) is `image_link`, `link`, `availability`, `price`, `condition` — keep the alert-present assertion and the "brand not shown" assertion; additionally assert `screen.queryByText(/structured_title/i)` presence is allowed (pair member listed) — simplest robust check: `expect(screen.getAllByText(/price/i).length).toBeGreaterThanOrEqual(1)`.

- [ ] **Step 3: Implement the new `requiredUncovered`**

In `frontend/src/features/setup/MappingTab.tsx`, replace the memo (lines 80-90) with:

```typescript
  const requiredUncovered = useMemo(() => {
    if (!Array.isArray(registryQuery.data)) return [];
    const baselineAttrs = registryQuery.data.filter((attr) => attr.baseline_required === true);
    const alternativePairs: Array<[string, string]> = [
      ['title', 'structured_title'],
      ['description', 'structured_description'],
    ];
    const uncovered: string[] = [];
    for (const attr of baselineAttrs) {
      const pair = alternativePairs.find(([a, b]) => a === attr.name || b === attr.name);
      if (pair) {
        if (coveredTargets.has(pair[0]) || coveredTargets.has(pair[1])) continue;
        if (uncovered.includes(pair[0])) continue;
        uncovered.push(pair[0], pair[1]);
        continue;
      }
      if (!coveredTargets.has(attr.name)) uncovered.push(attr.name);
    }
    return uncovered;
  }, [registryQuery.data, coveredTargets]);
```

No comments in the code.

- [ ] **Step 4: Run frontend tests**

```bash
cd frontend && npm run test
```

Expected: ALL `MappingTab` tests PASS (updated fixtures/expectations). No other frontend tests reference `requiredUncovered`.

- [ ] **Step 5: Typecheck and commit**

```bash
cd frontend && npm run typecheck
```

Expected: clean.

```bash
git add frontend/src/api/types.ts frontend/src/features/setup/MappingTab.tsx frontend/src/features/setup/MappingTab.test.tsx
git commit -m "fix: mapping alert lists baseline-required attrs only, with alternative pairs"
```

---

### Task 7: Docs update

**Files:**
- Modify: `backend/docs/architecture.md` (ingest section)
- Modify: `backend/docs/api.md` (`/registry/attributes`)
- Modify: `frontend/docs/architecture.md` (only if it documents the mapping alert — check first)
- Modify: `docs/superpowers/specs/2026-09-02-lenient-tsv-ingest-and-baseline-alert-design.md` (registry gap note — recorded follow-up)

**Interfaces:**
- Consumes: all previous tasks.

**Recorded follow-up (write into the spec's Non-goals section, one paragraph):** the registry parser does not expand backtick name ranges (`` `custom_label_0` … `custom_label_4` `` at gmc_def.md:127), so only `custom_label_0` and `custom_label_4` exist. `custom_label_1/2/3` are unmapped by auto-match today; feeds carrying those columns work (values dropped as unmapped fields). A future cycle should teach the parser to expand same-prefix numbered ranges and regenerate `registry/attributes.json` — required before the Labelizer plugin (spec §5.9, target_label slots 0–4) ships. Do NOT change the parser in this cycle.

- [ ] **Step 1: Update backend architecture docs**

In `backend/docs/architecture.md`, find the ingest/parsing section. Update to state:

- Delimited inputs parse via a single RFC-4180 `csv.reader` stream pass; quoted cells may contain embedded newlines; row-error line numbers are physical end-of-row lines.
- Annotated headers `attr(sub1:sub2:…)` trust the header's declared sub-field list as the positional truth; sub-fields unknown to the registry are tolerated and dropped at mapping/export (both filter structured values to registry-known sub-fields).
- Comma-splitting of cell values applies ONLY to repeated-scalar columns (registry REPEATED_SCALAR attributes); scalar and generic columns keep commas as content.
- Structural header errors still fail the import: duplicate scalar columns, non-adjacent repeated structured columns, annotating a non-structured attribute.
- `qc/constants.py` `BASELINE_REQUIRED` + `BASELINE_ALTERNATIVE_PAIRS` are the single source of the baseline-required definition (shared by the QC rule and `/registry/attributes`).

Only edit what exists — if a statement there contradicts the new behavior, fix it; do not rewrite unrelated sections.

- [ ] **Step 2: Update API docs**

In `backend/docs/api.md`, find the `/registry/attributes` entry and add `baseline_required: boolean` to the documented response fields (true for the §7 baseline set incl. `title`/`structured_title` and `description`/`structured_description` pair members; false otherwise).

- [ ] **Step 3: Check frontend docs**

```bash
grep -n "requiredUncovered\|Required registry\|mapping" frontend/docs/architecture.md | head -20
```

If (and only if) it describes the mapping-tab alert semantics, update it to the baseline-required + alternative-pair behavior. If it doesn't mention it, leave it untouched.

- [ ] **Step 4: Commit**

```bash
git add backend/docs/architecture.md backend/docs/api.md
git commit -m "docs: lenient ingest parsing and baseline_required registry flag"
```

(Add `frontend/docs/architecture.md` to the commit only if Step 3 changed it.)

---

### Task 8: Full verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Backend full suite**

```bash
cd backend && uv run pytest -n auto
```

Expected: ALL PASS (requires `TEST_DATABASE_URL` — per repo AGENTS.md it's configured in the environment; if the DB isn't up, `docker compose up -d postgres` first).

- [ ] **Step 2: Backend lint + typecheck**

```bash
cd backend && uv run ruff check . && uv run mypy .
```

Expected: clean.

- [ ] **Step 3: Frontend tests + typecheck**

```bash
cd frontend && npm run test && npm run typecheck
```

Expected: clean.

- [ ] **Step 4: Plugin contract tests (explicit per repo rules)**

```bash
cd backend && uv run pytest tests/test_plugin_contract.py -v
```

Expected: PASS (nothing plugin-related changed, but the repo mandates running it when in doubt).

- [ ] **Step 5: Final commit if anything was fixed during the sweep**

If the sweep surfaced fixes, commit them with a fitting message; otherwise nothing to do.
