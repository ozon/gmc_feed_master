# Nested Source Sub-Field Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow mapping individual sub-fields of structured/repeated-structured source fields to GMC attribute targets, with dotted mapping keys (`ship.price → shipping.price`), validation, auto-matcher support, and expandable UI rows.

**Architecture:** Mapping keys in `MappingDocument.mappings` become source paths (dotted keys) with no document format change (keys are already opaque strings). Backend: `_validate_mappings` resolves dotted keys against `source_fields` (exact-name-first), enforces exclusivity (whole field OR sub-fields, never both) and kind compat; `apply_mapping` extracts sub-values (broadcast over repeated elements) and merges element-wise into repeated structured targets; `auto_match` gains a sub-field matching pass. Frontend: `MappingTable` renders expandable rows with per-sub-field target Selects; `MappingTab` enforces exclusivity client-side. Design spec: `docs/superpowers/specs/2026-09-03-nested-source-field-mapping-design.md` (authoritative).

**Tech Stack:** Python 3.10+/FastAPI/SQLAlchemy async (backend, `uv run pytest -n auto`, `uv run ruff check .`, `uv run mypy .` from `backend/`), React 19/TypeScript/Mantine/vitest (frontend, `npm run test`, `npm run typecheck` from `frontend/`).

## Global Constraints

- Target grammar unchanged: `attr` or `attr.subfield` only (≤2 dot segments). Positional target paths (`shipping.1.price`) stay a 422.
- Disambiguation rule (apply everywhere): a mapping key that **exactly equals a source field name** is a whole-field mapping; only otherwise is it resolved as `parent.sub`.
- Exclusivity: if a whole-field mapping for `parent` exists in the same payload, any `parent.<sub>` key → 422 error `"{source}: conflicts with whole-field mapping {parent!r}"`.
- Effective source kind for compat: sub of `structured` → `scalar`; sub of `repeated_structured` → `repeated_scalar`; checked against `_COMPATIBLE_KINDS`.
- Registry facts (verified against `backend/registry/attributes.json` — rely on these, do not guess):
  - `installment` = `structured`, sub-fields `months`, `amount`, `downpayment`, `credit_type`.
  - `shipping` = `repeated_structured`, sub-fields include `country`, `region`, `postal_code`, `service`, `price`, `location_group_name`, …
  - `tax` = `structured`, sub-fields `country`, `region`, `postal_code`, `location_id`, `rate`, `tax_ship`.
  - `title`, `price`, `id`, `image_link` = `scalar`; `additional_image_link`, `gtin` = `repeated_scalar`.
  - There is NO whole attribute named `country` or `months`. Whole attribute `price` EXISTS (scalar).
  - Sub-field `months` exists ONLY on `installment`; sub-field `rate` exists ONLY on `tax`.
- Sub-values that are absent (`None`) are skipped (no output, no error). Non-dict element inside a repeated parent list, or non-str sub value → `shape_mismatch` (counted, value dropped).
- A dotless mapping key that is NOT a known source field keeps the CURRENT lenient behavior (target validated, source kind not checked, stored) — the existing test `test_put_field_mapping_stores_manual_entries` (`mystery_field`) depends on it. Keys with ≥2 dots → 422 `"{source}: invalid source path"`.
- 422 response shape stays `{"errors": ["key: message", ...]}` — frontend `parseRowErrors` splits on first colon.
- No comments in code (repo convention). No new dependencies. No DB migration. Document version stays 1.
- Backend commands run from `backend/`; frontend from `frontend/`. API tests need `TEST_DATABASE_URL` (already configured in this environment).
- Commit after every green step, conventional commit messages (`feat:`, `test:`, `docs:` — see `git log` for style).

---

### Task 1: `apply_mapping` — dotted-key sub-value extraction and merge

**Files:**
- Modify: `backend/app/mapping/apply.py`
- Test: `backend/tests/test_mapping_apply.py`

**Interfaces:**
- Consumes: `MappingEntry(target: str, origin: str)`; `RegistryDocument.attributes: dict[str, RegistryAttribute]` (`kind: AttributeKind`, `fields: tuple[SubField, ...]`); `ApplyStats(dropped_unmapped: int, shape_mismatches: int)`.
- Produces: `apply_mapping(product, mappings, registry) -> tuple[dict, ApplyStats]` extended semantics (used as-is by Tasks 2/3's tests and the pipeline — no signature change): mapping keys `"<parent>.<sub>"` where `parent` is a product key and the full dotted key is NOT itself a product key resolve to sub-values. Sub of dict parent → `list[str]` with one element. Sub of list-of-dicts parent → `list[str]` broadcast per element. Str into `attr.subfield` of a `structured` attr → `result[attr][sub] = value`; of a `repeated_structured` attr → element 0 of `result[attr]` (wrapping as `[dict]` when absent). `list[str]` into `attr.subfield` of `repeated_structured` → element-wise merge by index with auto-extend; into `attr.subfield` of `structured` → single-element list collapses, longer lists are `shape_mismatch`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_mapping_apply.py` (imports already present: `pytest`, `ApplyStats`, `MappingEntry`, `apply_mapping`, `load_registry`):

```python
def test_dotted_key_sub_of_dict_to_repeated_structured_subfield_wraps(registry):
    product = {"ship": {"country": "US", "service": "X"}}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {"shipping": [{"country": "US"}]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_sub_of_dict_to_structured_subfield(registry):
    result, stats = apply_mapping(
        {"fin": {"m": "6"}},
        {"fin.m": MappingEntry("installment.months", "manual")},
        registry,
    )
    assert result == {"installment": {"months": "6"}}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_absent_sub_value_skipped(registry):
    result, stats = apply_mapping(
        {"ship": {}}, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_exact_product_key_wins(registry):
    product = {"a.b": "kept", "a": {"b": "dropped"}}
    result, stats = apply_mapping(
        product, {"a.b": MappingEntry("title", "manual")}, registry
    )
    assert result == {"title": "kept"}
    assert stats == ApplyStats(dropped_unmapped=1, shape_mismatches=0)


def test_dotted_key_parent_with_sub_mapping_not_counted_unmapped(registry):
    result, stats = apply_mapping(
        {"ship": {"country": "US"}},
        {"ship.country": MappingEntry("shipping.country", "manual")},
        registry,
    )
    assert stats.dropped_unmapped == 0


def test_dotted_key_repeated_source_broadcasts(registry):
    product = {"ship": [{"country": "US"}, {"country": "CA"}]}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {"shipping": [{"country": "US"}, {"country": "CA"}]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_repeated_source_element_wise_merge_multiple_subs(registry):
    product = {"ship": [{"country": "US", "price": "5"}, {"country": "CA", "price": "7"}]}
    result, stats = apply_mapping(
        product,
        {
            "ship.country": MappingEntry("shipping.country", "manual"),
            "ship.price": MappingEntry("shipping.price", "manual"),
        },
        registry,
    )
    assert result == {
        "shipping": [
            {"country": "US", "price": "5"},
            {"country": "CA", "price": "7"},
        ]
    }
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_repeated_source_auto_extends_target_list(registry):
    product = {"ship": [{"country": "US"}, {"country": "CA"}]}
    result, stats = apply_mapping(
        product,
        {
            "ship.country": MappingEntry("shipping.country", "manual"),
            "ship.price": MappingEntry("shipping.price", "manual"),
        },
        registry,
    )
    assert result["shipping"][0] == {"country": "US", "price": "5"}
    assert result["shipping"][1] == {"country": "CA", "price": "7"}


def test_dotted_key_repeated_source_sparse_sub_values_merge_by_index(registry):
    product = {"ship": [{"country": "US"}, {"price": "7"}]}
    result, stats = apply_mapping(
        product,
        {
            "ship.country": MappingEntry("shipping.country", "manual"),
            "ship.price": MappingEntry("shipping.price", "manual"),
        },
        registry,
    )
    assert result == {
        "shipping": [{"country": "US"}, {"price": "7"}],
    }
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_sub_to_scalar_attr(registry):
    result, stats = apply_mapping(
        {"detail": {"name": "Shirt"}},
        {"detail.name": MappingEntry("title", "manual")},
        registry,
    )
    assert result == {"title": "Shirt"}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_sub_of_repeated_source_to_repeated_scalar_attr(registry):
    product = {"ship": [{"country": "US"}, {"country": "CA"}]}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("additional_image_link", "manual")}, registry
    )
    assert result == {"additional_image_link": ["US", "CA"]}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_list_into_structured_subfield_single_element_collapses(registry):
    product = {"ship": [{"months": "6"}]}
    result, stats = apply_mapping(
        product, {"ship.months": MappingEntry("installment.months", "manual")}, registry
    )
    assert result == {"installment": {"months": "6"}}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_list_into_structured_subfield_multi_element_mismatches(registry):
    product = {"ship": [{"months": "6"}, {"months": "12"}]}
    result, stats = apply_mapping(
        product, {"ship.months": MappingEntry("installment.months", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_dotted_key_non_dict_parent_list_element_shape_mismatch(registry):
    product = {"ship": [{"country": "US"}, "oops"]}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_dotted_key_non_str_sub_value_shape_mismatch(registry):
    product = {"ship": {"country": 42}}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_dotted_key_non_str_sub_value_in_list_shape_mismatch(registry):
    product = {"ship": [{"country": 42}]}
    result, stats = apply_mapping(
        product, {"ship.country": MappingEntry("shipping.country", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=1)


def test_dotted_key_scalar_parent_value_skipped_not_mismatch(registry):
    result, stats = apply_mapping(
        {"detail": "plain"}, {"detail.name": MappingEntry("title", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)


def test_dotted_key_three_segments_unresolvable_skipped(registry):
    product = {"a": {"b": {"c": "deep"}}}
    result, stats = apply_mapping(
        product, {"a.b.c": MappingEntry("title", "manual")}, registry
    )
    assert result == {}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mapping_apply.py -v` (from `backend/`)
Expected: all new dotted-key tests FAIL — current `apply_mapping` looks up mapping keys only among top-level product keys, so `ship.country` never matches; sub-values are dropped as unmapped (wrong stats) and results are `{}`.

- [ ] **Step 3: Implement**

Replace the content of `backend/app/mapping/apply.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from registry.model import AttributeKind, RegistryDocument

from .document import MappingEntry


@dataclass
class ApplyStats:
    dropped_unmapped: int = 0
    shape_mismatches: int = 0


def _sub_values(value: Any, sub: str) -> tuple[list[str] | None, bool]:
    if isinstance(value, dict):
        item = value.get(sub)
        if item is None:
            return None, False
        if not isinstance(item, str):
            return None, True
        return [item], False
    if isinstance(value, list):
        if not all(isinstance(elem, dict) for elem in value):
            return None, True
        result: list[str] = []
        for elem in value:
            item = elem.get(sub)
            if item is None:
                result.append("")
                continue
            if not isinstance(item, str):
                return None, True
            result.append(item)
        if not any(result):
            return None, False
        return result, False
    return None, False


def _merge_elementwise(
    result: dict[str, Any], attr_name: str, subfield: str, values: list[str]
) -> None:
    bucket = result.get(attr_name)
    if not isinstance(bucket, list):
        bucket = []
        result[attr_name] = bucket
    while len(bucket) < len(values):
        bucket.append({})
    for index, item in enumerate(values):
        if item == "":
            continue
        bucket[index][subfield] = item


def apply_mapping(
    product: dict[str, Any],
    mappings: dict[str, MappingEntry],
    registry: RegistryDocument,
) -> tuple[dict[str, Any], ApplyStats]:
    stats = ApplyStats()
    result: dict[str, Any] = {}
    parent_has_sub_mapping = {
        key.partition(".")[0]
        for key in mappings
        if "." in key and key not in product
    }

    for source, value in product.items():
        entry = mappings.get(source)
        if entry is not None:
            _apply_entry(result, source, value, entry, registry, stats)
        elif source not in parent_has_sub_mapping:
            stats.dropped_unmapped += 1

    for key, entry in mappings.items():
        if key in product or "." not in key:
            continue
        parent, _, sub = key.partition(".")
        if not sub or "." in sub or parent not in product:
            continue
        values, mismatch = _sub_values(product[parent], sub)
        if mismatch:
            stats.shape_mismatches += 1
            continue
        if values is not None:
            _apply_entry(result, key, values, entry, registry, stats)

    return result, stats


def _apply_entry(
    result: dict[str, Any],
    source: str,
    value: Any,
    entry: MappingEntry,
    registry: RegistryDocument,
    stats: ApplyStats,
) -> None:
    attr_name, _, subfield = entry.target.partition(".")
    attribute = registry.attributes.get(attr_name)
    if attribute is None:
        stats.shape_mismatches += 1
        return

    if subfield:
        if attribute.kind.value not in ("structured", "repeated_structured"):
            stats.shape_mismatches += 1
            return
        if isinstance(value, str):
            if attribute.kind is AttributeKind.STRUCTURED:
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
            if attribute.kind is AttributeKind.STRUCTURED:
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

    kind = attribute.kind
    if kind is AttributeKind.SCALAR:
        if isinstance(value, str):
            result[attr_name] = value
        else:
            stats.shape_mismatches += 1
    elif kind is AttributeKind.REPEATED_SCALAR:
        if isinstance(value, str):
            result[attr_name] = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            result[attr_name] = list(value)
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

Semantics notes for the implementer:
- `parent_has_sub_mapping` suppresses `dropped_unmapped` for product keys that any dotted mapping key references (the parent's data is consumed piecemeal, or was attempted).
- `_sub_values` returns `(values, mismatch)`: `(None, False)` = skip silently (absent everywhere / parent not a container); `(None, True)` = shape mismatch; `(list, False)` = usable, where `""` marks an absent element's slot so indices stay aligned.
- Dotted resolution only fires for keys that are NOT themselves product keys (exact-name-first) and have exactly one dot.
- The `str`-into-`repeated_structured`-subfield branch writes element 0 (auto-extend semantics of spec §5.7); multiple sub-mappings into the same repeated attribute merge by index via `_merge_elementwise`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mapping_apply.py tests/test_example_feed_chain.py -v` (from `backend/`)
Expected: ALL PASS (old + new; example-feed chains prove whole-struct behavior unchanged).

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy .` (from `backend/`)
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/mapping/apply.py backend/tests/test_mapping_apply.py
git commit -m "feat: apply nested source sub-field mappings in mapping step"
```

---

### Task 2: `_validate_mappings` — dotted-key validation + exclusivity

**Files:**
- Modify: `backend/app/mapping/matcher.py` (add two shared constants)
- Modify: `backend/app/routes/field_mapping.py:34-72`
- Test: `backend/tests/test_field_mapping_api.py`

**Interfaces:**
- Consumes: `MappingDocument.source_fields: list[SourceField]` (`SourceField(name, kind, sub_fields)`); `_STRUCTURED_KINDS` at `field_mapping.py:18` (target-side structured kinds, keep it); `_COMPATIBLE_KINDS` imported from `..mapping.matcher` (existing precedent of importing module-private constants from matcher).
- Produces: `_validate_mappings(mappings: dict[str, str], document: MappingDocument) -> list[str]` — same signature, extended rules. In `matcher.py`: new module-level `_STRUCTURED_SOURCE_KINDS: frozenset[str] = frozenset({"structured", "repeated_structured"})` and `_SUB_EFFECTIVE_KINDS: dict[str, str] = {"structured": "scalar", "repeated_structured": "repeated_scalar"}` (Task 3 consumes these same constants).

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_field_mapping_api.py` (reuse existing helpers `logged_in_client`, `create_feed_source`, `seed_field_mapping`, `source_field` defined at the top of that file):

```python
def nested_doc(*fields):
    return {
        "version": 1,
        "auto_mapped": True,
        "source_fields": list(fields),
        "mappings": {},
    }


async def test_put_nested_key_unknown_parent_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory, fs_id, nested_doc(source_field("product_name", "scalar"))
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"ghost.price": {"target": "shipping.price"}}},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_nested_key_non_structured_parent_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory, fs_id, nested_doc(source_field("product_name", "scalar"))
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"product_name.sub": {"target": "title"}}},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_nested_key_unknown_sub_field_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        nested_doc(source_field("ship", "structured", ["country", "price"])),
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"ship.bogus": {"target": "title"}}},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_nested_key_two_dots_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory, fs_id, nested_doc(source_field("ship", "structured", ["country"]))
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"a.b.c": {"target": "title"}}},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_nested_key_conflicts_with_whole_field_mapping_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        nested_doc(source_field("ship", "structured", ["country", "price"])),
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {
                "ship": {"target": "shipping"},
                "ship.country": {"target": "shipping.country"},
            }
        },
    )
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert isinstance(errors, list)
    assert any("ship.country" in err for err in errors)


async def test_put_nested_key_structured_sub_to_scalar_attr_ok(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory, fs_id, nested_doc(source_field("detail", "structured", ["name"]))
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"detail.name": {"target": "title"}}},
    )
    assert resp.status_code == 200
    assert resp.json()["mappings"] == {
        "detail.name": {"target": "title", "origin": "manual"}
    }


async def test_put_nested_key_repeated_source_subfield_targets_ok(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        nested_doc(source_field("ship", "repeated_structured", ["country", "price"])),
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {
                "ship.country": {"target": "shipping.country"},
                "ship.price": {"target": "shipping.price"},
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mappings"] == {
        "ship.country": {"target": "shipping.country", "origin": "manual"},
        "ship.price": {"target": "shipping.price", "origin": "manual"},
    }
    persisted = (await client.get(f"/feed-sources/{fs_id}/field-mapping")).json()
    assert persisted["mappings"] == body["mappings"]


async def test_put_nested_key_kind_incompatible_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory, fs_id, nested_doc(source_field("ship", "structured", ["country"]))
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"ship.country": {"target": "shipping"}}},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_nested_key_sub_target_conflicts_across_parents_returns_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        nested_doc(
            source_field("ship", "structured", ["country"]),
            source_field("tax", "structured", ["country"]),
        ),
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {
                "ship.country": {"target": "shipping.country"},
                "tax.country": {"target": "shipping.country"},
            }
        },
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["errors"], list)


async def test_put_exact_source_name_wins_over_path_resolution(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        nested_doc(
            source_field("ship", "structured", ["country"]),
            source_field("ship.price", "scalar"),
        ),
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"ship.price": {"target": "price"}}},
    )
    assert resp.status_code == 200
    assert resp.json()["mappings"] == {
        "ship.price": {"target": "price", "origin": "manual"}
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_field_mapping_api.py -v -k "nested or exact_source_name"` (from `backend/`)
Expected: FAIL — current validator treats dotted keys as plain names (no parent/sub resolution, no exclusivity); conflict and error tests fail on status code.

- [ ] **Step 3: Implement**

First add to `backend/app/mapping/matcher.py` (after the `_COMPATIBLE_KINDS` block; these are consumed by both the routes and Task 3):

```python
_STRUCTURED_SOURCE_KINDS = frozenset({"structured", "repeated_structured"})

_SUB_EFFECTIVE_KINDS: dict[str, str] = {
    "structured": "scalar",
    "repeated_structured": "repeated_scalar",
}
```

Then in `backend/app/routes/field_mapping.py`:
1. Extend the import at line 12 to:
   ```python
   from ..mapping.matcher import (
       _COMPATIBLE_KINDS,
       _STRUCTURED_SOURCE_KINDS,
       _SUB_EFFECTIVE_KINDS,
       auto_match,
   )
   ```
2. Replace `_validate_mappings` (lines 34-72) with:

```python
def _validate_mappings(
    mappings: dict[str, str],
    document: MappingDocument,
) -> list[str]:
    registry = load_registry()
    known_fields = {field.name: field for field in document.source_fields}
    errors: list[str] = []
    claimed: dict[str, str] = {}

    def check_target(source: str, target: str, source_kind: str | None) -> None:
        parts = target.split(".")
        if len(parts) > 2 or not all(parts):
            errors.append(f"{source}: invalid target path {target!r}")
            return
        attribute = registry.attributes.get(parts[0])
        if attribute is None:
            errors.append(f"{source}: unknown attribute {parts[0]!r}")
            return
        if len(parts) == 2:
            if attribute.kind.value not in _STRUCTURED_KINDS:
                errors.append(f"{source}: {parts[0]!r} has no sub-fields")
                return
            if parts[1] not in {sub.name for sub in attribute.fields}:
                errors.append(f"{source}: unknown sub-field {parts[1]!r} on {parts[0]!r}")
                return
        if (
            len(parts) == 1
            and source_kind is not None
            and attribute.kind.value not in _COMPATIBLE_KINDS.get(source_kind, frozenset())
        ):
            errors.append(
                f"{source}: kind {source_kind!r} incompatible with "
                f"{attribute.kind.value!r} target {target!r}"
            )
            return
        if target in claimed:
            errors.append(f"{source}: target {target!r} already claimed by {claimed[target]!r}")
            return
        claimed[target] = source

    whole_mapped_parents = {
        source for source in mappings if source in known_fields
    }

    for source, target in mappings.items():
        if source in known_fields:
            check_target(source, target, known_fields[source].kind)
            continue
        parent, dot, sub = source.partition(".")
        if not dot or not sub:
            check_target(source, target, None)
            continue
        if "." in sub:
            errors.append(f"{source}: invalid source path")
            continue
        if parent in whole_mapped_parents:
            errors.append(f"{source}: conflicts with whole-field mapping {parent!r}")
            continue
        field = known_fields.get(parent)
        if field is None:
            errors.append(f"{source}: unknown source field {parent!r}")
            continue
        if field.kind not in _STRUCTURED_SOURCE_KINDS:
            errors.append(f"{source}: {parent!r} is not a structured source field")
            continue
        if sub not in field.sub_fields:
            errors.append(f"{source}: unknown sub-field {sub!r} on {parent!r}")
            continue
        check_target(source, target, _SUB_EFFECTIVE_KINDS[field.kind])

    return errors
```

Implementation notes:
- The `not dot or not sub` branch preserves the legacy lenient behavior for dotless unknown source names (`mystery_field` in `test_put_field_mapping_stores_manual_entries` must keep passing): target validated, no source-kind check.
- `whole_mapped_parents` = parents explicitly mapped whole **in this payload**; sub-keys of unmapped parents are fine (the parent simply isn't mapped).
- `check_target` with a subfield target (`len(parts) == 2`) skips the kind-compat check (existing behavior — a scalar source may target `installment.months`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_field_mapping_api.py tests/test_m4_acceptance.py -v` (from `backend/`)
Expected: ALL PASS (old + new; `test_m4_acceptance.py` also exercises these endpoints end-to-end).

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy .` (from `backend/`)
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/mapping/matcher.py backend/app/routes/field_mapping.py backend/tests/test_field_mapping_api.py
git commit -m "feat: validate nested source sub-field mappings with exclusivity"
```

---

### Task 3: `auto_match` — sub-field matching pass

**Files:**
- Modify: `backend/app/mapping/matcher.py`
- Test: `backend/tests/test_mapping_matcher.py`

**Interfaces:**
- Consumes: Task 2's `_STRUCTURED_SOURCE_KINDS` and `_SUB_EFFECTIVE_KINDS` (now in matcher.py); `_normalize`; `SYNONYMS` (NOT applied to sub names); `_COMPATIBLE_KINDS`; `MappingEntry`.
- Produces: `auto_match(source_fields, registry, existing=None) -> dict[str, MappingEntry]` additionally emits `"parent.sub": MappingEntry(target, "auto")` entries. Sub-match ordering (pinned): (1) whole-attribute match on the sub name (normalized) with kind compat — mirrors exact-name-first; (2) else `attr.subfield` path scan over registry attributes in declared order, first unclaimed match wins.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_mapping_matcher.py`:

```python
def test_sub_field_prefers_whole_attribute_match(registry):
    fields = [SourceField("ship", "structured", ("price",))]
    result = auto_match(fields, registry)
    assert result == {"ship.price": MappingEntry("price", "auto")}


def test_sub_field_matches_unique_subfield_path(registry):
    fields = [SourceField("fin", "structured", ("months",))]
    result = auto_match(fields, registry)
    assert result == {"fin.months": MappingEntry("installment.months", "auto")}


def test_sub_field_normalized_match(registry):
    fields = [SourceField("ship", "structured", ("Sale_Price",))]
    result = auto_match(fields, registry)
    assert result == {"ship.Sale_Price": MappingEntry("sale_price", "auto")}


def test_sub_field_of_repeated_structured_uses_repeated_scalar_kind(registry):
    fields = [SourceField("imgs", "repeated_structured", ("image_link",))]
    result = auto_match(fields, registry)
    assert result == {"imgs.image_link": MappingEntry("image_link", "auto")}


def test_sub_field_kind_incompatible_no_match(registry):
    fields = [SourceField("box", "structured", ("shipping",))]
    result = auto_match(fields, registry)
    assert result == {}


def test_sub_field_no_synonyms(registry):
    fields = [SourceField("box", "structured", ("ean",))]
    result = auto_match(fields, registry)
    assert result == {}


def test_whole_field_mapping_suppresses_sub_pass(registry):
    fields = [SourceField("ship", "structured", ("country",))]
    existing = {"ship": MappingEntry("shipping", "manual")}
    result = auto_match(fields, registry, existing)
    assert result == {"ship": MappingEntry("shipping", "manual")}


def test_existing_sub_mapping_blocks_whole_field_auto(registry):
    fields = [SourceField("ship", "structured", ("country",))]
    existing = {"ship.country": MappingEntry("shipping.country", "manual")}
    result = auto_match(fields, registry, existing)
    assert result == {"ship.country": MappingEntry("shipping.country", "manual")}
```

Registry facts these rely on (verified): whole attr `price` exists (scalar) — sub `price` matches it first; sub `months` has no whole attr and `installment.months` is its only subfield path; sub `shipping` (whole attr `repeated_structured`) is kind-incompatible with effective `scalar`; no attr has a sub-field named `ean`; `image_link` is scalar (compatible with effective `repeated_scalar` per `_COMPATIBLE_KINDS["repeated_scalar"] = {"repeated_scalar"}` — wait, that set does NOT contain `scalar`).

Correction for the last fact: `_COMPATIBLE_KINDS["repeated_scalar"]` = `{"repeated_scalar"}` only. `image_link` is **scalar**, so `imgs.image_link → image_link` would be INCOMPATIBLE. Replace that test with one using a `repeated_scalar` attribute:

```python
def test_sub_field_of_repeated_structured_uses_repeated_scalar_kind(registry):
    fields = [SourceField("imgs", "repeated_structured", ("additional_image_link",))]
    result = auto_match(fields, registry)
    assert result == {
        "imgs.additional_image_link": MappingEntry("additional_image_link", "auto")
    }
```

(`additional_image_link` is `repeated_scalar`; sub of `repeated_structured` → effective `repeated_scalar` → compatible.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mapping_matcher.py -v` (from `backend/`)
Expected: all new tests FAIL — current `auto_match` iterates whole fields only, never emits dotted keys, and a manual sub-mapping in `existing` does not block a whole-field auto claim.

- [ ] **Step 3: Implement**

In `backend/app/mapping/matcher.py`, replace the `auto_match` function (keep `_SEPARATORS`, `SYNONYMS`, `_COMPATIBLE_KINDS`, Task 2's two constants, `_normalize`):

```python
def auto_match(
    source_fields: list[SourceField],
    registry: RegistryDocument,
    existing: dict[str, MappingEntry] | None = None,
) -> dict[str, MappingEntry]:
    result: dict[str, MappingEntry] = dict(existing or {})
    claimed = {entry.target for entry in result.values()}
    by_normalized = {_normalize(name): name for name in registry.attributes}

    def has_sub_mapping(field: SourceField) -> bool:
        prefix = f"{field.name}."
        return any(key.startswith(prefix) for key in result)

    def try_claim(field: SourceField, target: str, origin: str) -> None:
        if field.name in result or target in claimed:
            return
        attribute = registry.attributes[target]
        if attribute.kind.value not in _COMPATIBLE_KINDS.get(field.kind, frozenset()):
            return
        result[field.name] = MappingEntry(target=target, origin=origin)
        claimed.add(target)

    def try_claim_sub(field: SourceField, sub: str, target: str) -> bool:
        key = f"{field.name}.{sub}"
        if key in result or target in claimed:
            return False
        attr_name, _, attr_sub = target.partition(".")
        attribute = registry.attributes.get(attr_name)
        if attribute is None:
            return False
        effective = _SUB_EFFECTIVE_KINDS.get(field.kind, "")
        if attribute.kind.value not in _COMPATIBLE_KINDS.get(effective, frozenset()):
            return False
        if attr_sub:
            if attribute.kind.value not in ("structured", "repeated_structured"):
                return False
            if attr_sub not in {f.name for f in attribute.fields}:
                return False
        result[key] = MappingEntry(target=target, origin="auto")
        claimed.add(target)
        return True

    # Two passes enforce priority: auto (exact/normalized) beats synonym,
    # and within a pass the first source field in order wins the target.
    # A parent with any existing sub-mapping is protected from whole-field
    # auto/synonym claims (exclusivity).
    for field in source_fields:
        if has_sub_mapping(field):
            continue
        target = by_normalized.get(_normalize(field.name))
        if target is not None:
            try_claim(field, target, "auto")

    for field in source_fields:
        if has_sub_mapping(field):
            continue
        target = SYNONYMS.get(_normalize(field.name))
        if target is not None and target in registry.attributes:
            try_claim(field, target, "synonym")

    # Sub-field pass: for every structured source field without a whole
    # mapping, each sub name is matched first against whole attribute names,
    # then against attr.subfield paths (registry declared order, first
    # unclaimed compatible match wins). No sub-level synonyms.
    for field in source_fields:
        if field.kind not in _STRUCTURED_SOURCE_KINDS or field.name in result:
            continue
        for sub in field.sub_fields:
            whole_target = by_normalized.get(_normalize(sub))
            if whole_target is not None:
                if try_claim_sub(field, sub, whole_target):
                    continue
            for attr_name, attribute in registry.attributes.items():
                if attribute.kind.value not in ("structured", "repeated_structured"):
                    continue
                for attr_sub in attribute.fields:
                    if _normalize(attr_sub.name) == _normalize(sub):
                        if try_claim_sub(
                            field, sub, f"{attr_name}.{attr_sub.name}"
                        ):
                            break
                else:
                    continue
                break

    return result
```

Semantics notes:
- `try_claim_sub` kind check: effective sub kind vs the TARGET's kind. For a whole-attr target, `_COMPATIBLE_KINDS[effective]` must contain the attr kind (sub of `structured` → `scalar` can claim scalar or repeated_scalar attrs). For an `attr.subfield` target, the attr must be structured-kind and the sub name must exist on it (a scalar value flowing into a sub-field slot is always grammatically valid).
- The whole-field passes skip parents that already have sub-mappings (`has_sub_mapping`) — this makes `test_existing_sub_mapping_blocks_whole_field_auto` pass and preserves the operator's manual sub-choices.
- `test_sub_field_kind_incompatible_no_match`: sub `shipping` — whole attr `shipping` is `repeated_structured`, effective kind `scalar`, `_COMPATIBLE_KINDS["scalar"]` = `{scalar, repeated_scalar}` → rejected; the subfield-path scan finds no attr with a sub named `shipping` → `{}`. ✓

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mapping_matcher.py tests/test_mapping_apply.py tests/test_field_mapping_api.py tests/test_example_feed_chain.py tests/test_mapping_step.py -v` (from `backend/`)
Expected: ALL PASS. The feed-chain fixtures are safe: every structured source in `multifeed.tsv` and `example_feed.xml` (`shipping`, `tax`, `product_detail`, `certification`) whole-maps exactly, so the sub pass claims nothing extra on them.

- [ ] **Step 4b: Run the full backend suite**

Run: `uv run pytest -n auto` (from `backend/`)
Expected: ALL PASS.

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy .` (from `backend/`)
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/mapping/matcher.py backend/tests/test_mapping_matcher.py
git commit -m "feat: auto-match source sub-fields with exclusivity guard"
```

---

### Task 4: Frontend — `MappingTable` expandable sub-rows + i18n keys

**Files:**
- Modify: `frontend/src/features/setup/MappingTable.tsx`
- Modify: `frontend/public/locales/en/setup.json`
- Modify: `frontend/public/locales/de/setup.json`
- Test: `frontend/src/features/setup/MappingTable.test.tsx`

**Interfaces:**
- Consumes: `SourceField {name: string; kind: string; sub_fields: string[]}`; `mappings: Record<string, {target: string | null; origin: string | null}>`; `onChange(source: string, target: string | null): void`; `errors: Record<string, string>`; `buildTargetOptions`.
- Produces: `MappingTable` renders an expand toggle (`data-sub-toggle="<parent>"` attribute, aria-expanded) for source fields with `kind === 'structured' || 'repeated_structured'` AND non-empty `sub_fields`; expanded state renders one sub-row per `sf.sub_fields` keyed `"<parent>.<sub>"`, each with kind badge (raw `scalar`/`repeated_scalar` — same style as parent kind badges), origin badge, error text, and its own Select calling `onChange('parent.sub', target)`. New i18n keys (both locales): `mapping.table.expandSubFields` = "Show sub-fields of {{field}}" / de "Unterfelder von {{field}} anzeigen"; `mapping.table.collapseSubFields` = "Hide sub-fields of {{field}}" / de "Unterfelder von {{field}} ausblenden". Task 5's `MappingTab` test consumes the same `data-sub-toggle` attribute.

- [ ] **Step 1: Write failing tests**

Append inside `describe('MappingTable', ...)` in `frontend/src/features/setup/MappingTable.test.tsx`, and add the helper `mappingsFixture` right after the existing `mappings` const (change the existing const to call it):

```tsx
function mappingsFixture() {
  return {
    title: { target: 'title', origin: 'auto' },
    synonym_field: { target: 'description', origin: 'synonym' },
  };
}

const mappings = mappingsFixture();
```

New tests inside the describe:

```tsx
  it('shows no expand toggle for scalar rows', async () => {
    render(<MappingTable {...defaultProps()} />);
    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });
    expect(document.querySelector('[data-sub-toggle]')).toBeNull();
  });

  it('expands a structured row to show sub-field rows', async () => {
    const user = userEvent.setup();
    render(<MappingTable {...defaultProps()} />);
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    expect(toggle).not.toBeNull();
    await user.click(toggle);
    const monthsRow = (await screen.findByText('months', { selector: 'td p' })).closest('tr')!;
    expect(monthsRow).not.toBeNull();
    expect(screen.getByText('amount', { selector: 'td p' })).toBeInTheDocument();
    expect(monthsRow.querySelectorAll('td').length).toBe(2);
  });

  it('sub-row select calls onChange with dotted key', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MappingTable {...defaultProps({ onChange })} />);
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('months', { selector: 'td p' })).closest('tr')!;
    const select = subRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: 'installment.months' });
    await user.click(option);
    expect(onChange).toHaveBeenCalledWith('installment_data.months', 'installment.months');
  });

  it('sub-row shows error text for its dotted key', async () => {
    const user = userEvent.setup();
    render(
      <MappingTable {...defaultProps({ errors: { 'installment_data.months': 'unknown sub-field' } })} />,
    );
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    await user.click(toggle);
    expect(await screen.findByText('unknown sub-field')).toBeInTheDocument();
  });

  it('sub-row shows origin badge from dotted-key mapping', async () => {
    const user = userEvent.setup();
    render(
      <MappingTable
        {...defaultProps({
          mappings: {
            ...mappingsFixture(),
            'installment_data.months': { target: 'installment.months', origin: 'auto' },
          },
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('months', { selector: 'td p' })).closest('tr')!;
    expect(subRow.textContent).toContain('auto');
  });

  it('clearing a sub-row select calls onChange with null', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          mappings: {
            ...mappingsFixture(),
            'installment_data.months': { target: 'installment.months', origin: 'manual' },
          },
          onChange,
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('months', { selector: 'td p' })).closest('tr')!;
    const clearButton = subRow.querySelector('.mantine-InputClearButton-root');
    expect(clearButton).not.toBeNull();
    await user.click(clearButton!);
    expect(onChange).toHaveBeenCalledWith('installment_data.months', null);
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- src/features/setup/MappingTable.test.tsx` (from `frontend/`)
Expected: new tests FAIL — no `[data-sub-toggle]` attribute exists; sub-rows are not rendered.

- [ ] **Step 3: Implement**

Replace `frontend/src/features/setup/MappingTable.tsx` with:

```tsx
import { Fragment, useState } from 'react';
import { Badge, Box, Select, Stack, Table, Text, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { RegistryAttribute, SourceField } from '../../api/types';

type SelectOption = { value: string; label: string; group: string };

function buildTargetOptions(registryAttributes: RegistryAttribute[]): SelectOption[] {
  const options: SelectOption[] = [];
  for (const attr of registryAttributes) {
    const isStructured = attr.kind === 'structured' || attr.kind === 'repeated_structured';
    if (isStructured) {
      for (const sub of attr.sub_fields) {
        options.push({ value: `${attr.name}.${sub.name}`, label: `${attr.name}.${sub.name}`, group: attr.name });
      }
    } else {
      options.push({ value: attr.name, label: attr.name, group: attr.name });
    }
  }
  return options;
}

type MappingTableProps = {
  sourceFields: SourceField[];
  mappings: Record<string, { target: string | null; origin: string | null }>;
  registryAttributes: RegistryAttribute[];
  onChange: (source: string, target: string | null) => void;
  errors: Record<string, string>;
};

const originLabels: Record<string, string> = {
  auto: 'mapping.origins.auto',
  synonym: 'mapping.origins.synonym',
  manual: 'mapping.origins.manual',
};

const STRUCTURED_KINDS = new Set(['structured', 'repeated_structured']);

function isExpandable(sf: SourceField): boolean {
  return STRUCTURED_KINDS.has(sf.kind) && sf.sub_fields.length > 0;
}

function subFieldKind(parentKind: string): string {
  return parentKind === 'repeated_structured' ? 'repeated_scalar' : 'scalar';
}

function OriginBadge({ origin }: { origin: string | null }) {
  const { t } = useTranslation('setup');
  if (!origin) return null;
  return (
    <Badge
      size="xs"
      variant="outline"
      color={origin === 'auto' ? 'blue' : origin === 'synonym' ? 'yellow' : 'gray'}
    >
      {originLabels[origin] ? t(originLabels[origin] as 'mapping.origins.auto') : origin}
    </Badge>
  );
}

export function MappingTable({
  sourceFields,
  mappings,
  registryAttributes,
  onChange,
  errors,
}: MappingTableProps) {
  const { t } = useTranslation('setup');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const targetOptions = buildTargetOptions(registryAttributes);

  const grouped = new Map<string, SelectOption[]>();
  for (const opt of targetOptions) {
    const list = grouped.get(opt.group) ?? [];
    list.push(opt);
    grouped.set(opt.group, list);
  }

  const mantineData = Array.from(grouped.entries()).map(([group, items]) => ({
    group,
    items: items.map(({ value, label }) => ({ value, label })),
  }));

  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('mapping.table.source')}</Table.Th>
          <Table.Th>{t('mapping.table.target')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {sourceFields.map((sf) => {
          const mapping = mappings[sf.name];
          const origin = mapping?.origin ?? null;
          const targetValue = mapping?.target ?? null;
          const error = errors[sf.name] ?? null;
          const expandable = isExpandable(sf);
          const isOpen = expanded[sf.name] ?? false;

          return (
            <Fragment key={sf.name}>
              <Table.Tr>
                <Table.Td>
                  <Stack gap={4}>
                    <Box style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {expandable && (
                        <UnstyledButton
                          data-sub-toggle={sf.name}
                          aria-expanded={isOpen}
                          aria-label={t(
                            isOpen ? 'mapping.table.collapseSubFields' : 'mapping.table.expandSubFields',
                            { field: sf.name },
                          )}
                          onClick={() =>
                            setExpanded((prev) => ({ ...prev, [sf.name]: !prev[sf.name] }))
                          }
                        >
                          {isOpen ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
                        </UnstyledButton>
                      )}
                      <Text size="sm" fw={500}>
                        {sf.name}
                      </Text>
                      <Badge size="xs" variant="light">
                        {sf.kind}
                      </Badge>
                      <OriginBadge origin={origin} />
                    </Box>
                    {error && <Text size="xs" c="red">{error}</Text>}
                  </Stack>
                </Table.Td>
                <Table.Td>
                  <Select
                    data={mantineData}
                    value={targetValue}
                    onChange={(val) => onChange(sf.name, val)}
                    clearable
                    searchable
                    placeholder={t('mapping.table.selectTarget')}
                    size="sm"
                    error={!!error}
                  />
                </Table.Td>
              </Table.Tr>
              {expandable
                && isOpen
                && sf.sub_fields.map((sub) => {
                  const subKey = `${sf.name}.${sub}`;
                  const subMapping = mappings[subKey];
                  const subError = errors[subKey] ?? null;
                  return (
                    <Table.Tr key={subKey}>
                      <Table.Td>
                        <Stack gap={4}>
                          <Box style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 32 }}>
                            <Text size="sm" fw={500}>
                              {sub}
                            </Text>
                            <Badge size="xs" variant="light">
                              {subFieldKind(sf.kind)}
                            </Badge>
                            <OriginBadge origin={subMapping?.origin ?? null} />
                          </Box>
                          {subError && <Text size="xs" c="red">{subError}</Text>}
                        </Stack>
                      </Table.Td>
                      <Table.Td>
                        <Select
                          data={mantineData}
                          value={subMapping?.target ?? null}
                          onChange={(val) => onChange(subKey, val)}
                          clearable
                          searchable
                          placeholder={t('mapping.table.selectTarget')}
                          size="sm"
                          error={!!subError}
                        />
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
            </Fragment>
          );
        })}
      </Table.Tbody>
    </Table>
  );
}
```

Then add the i18n keys.

In `frontend/public/locales/en/setup.json`, inside `"mapping" → "table"`, after `"selectTarget"`:

```json
      "expandSubFields": "Show sub-fields of {{field}}",
      "collapseSubFields": "Hide sub-fields of {{field}}"
```

In `frontend/public/locales/de/setup.json`, same location:

```json
      "expandSubFields": "Unterfelder von {{field}} anzeigen",
      "collapseSubFields": "Unterfelder von {{field}} ausblenden"
```

(Keep valid JSON — add commas as needed for the surrounding entries.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/features/setup/MappingTable.test.tsx` (from `frontend/`)
Expected: ALL PASS (old + new).

- [ ] **Step 5: Typecheck**

Run: `npm run typecheck` (from `frontend/`)
Expected: no errors (`i18next.d.ts` infers the new keys from `en/setup.json` automatically).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/setup/MappingTable.tsx frontend/src/features/setup/MappingTable.test.tsx frontend/public/locales/en/setup.json frontend/public/locales/de/setup.json
git commit -m "feat: expandable sub-field rows in mapping table"
```

---

### Task 5: `MappingTab` — dotted-key save payload + UI exclusivity clearing

**Files:**
- Modify: `frontend/src/features/setup/MappingTab.tsx` (`handleTargetChange` only)
- Test: `frontend/src/features/setup/MappingTab.test.tsx`

**Interfaces:**
- Consumes: Task 4's `data-sub-toggle` and sub-row Selects. `MappingTab` state machinery (`localEdits`, `effectiveMappings`, `parseRowErrors`) already keyed by arbitrary source strings — no changes needed there.
- Produces: `handleTargetChange(source, target)` with exclusivity clearing: setting a dotted key (`parent.sub`) also clears the parent's local edit (`localEdits[parent] = null`); setting a whole parent also clears every `parent.*` local edit. The PUT payload builder (`handleSave`) already drops null-target entries, so cleared keys vanish from the payload.

- [ ] **Step 1: Write failing test**

Append to `describe('MappingTab', ...)` in `frontend/src/features/setup/MappingTab.test.tsx` (helpers `jsonResponse`, `stubFetch`, `putBody`, `renderTab`, and fixtures `mappingDoc`, `registryAttrs` already exist there):

```tsx
  it('save PUTs dotted sub-field keys and clears the conflicting parent edit', async () => {
    const user = userEvent.setup();
    const doc: FieldMappingDoc = {
      ...mappingDoc,
      source_fields: [
        ...mappingDoc.source_fields,
        { name: 'ship', kind: 'structured', sub_fields: ['country'] },
      ],
    };
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') {
        if (fetchMock.mock.calls.some(
          ([input, init]) => String(input) === url && init?.method === 'PUT',
        )) {
          return jsonResponse({ ...doc, auto_mapped: false });
        }
        return jsonResponse(doc);
      }
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('ship')).toBeInTheDocument();
    });

    const toggle = document.querySelector('[data-sub-toggle="ship"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('country', { selector: 'td p' })).closest('tr')!;
    const select = subRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: 'installment.months' });
    await user.click(option);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body).toBeDefined();
      expect(body?.mappings).toEqual(
        expect.objectContaining({
          'ship.country': { target: 'installment.months' },
        }),
      );
      expect((body?.mappings as Record<string, unknown>)['ship']).toBeUndefined();
    });
  });
```

Note: `registryAttrs` in that file already includes `installment` (structured, `months`/`amount`), so the option `installment.months` exists.

- [ ] **Step 2: Run test to verify current behavior**

Run: `npm run test -- src/features/setup/MappingTab.test.tsx` (from `frontend/`)
Expected: the new test PASSES or FAILS only on the `'ship'` absence assertion. If it passes fully without the exclusivity change, it still serves as payload regression coverage — implement Step 3 regardless (the exclusivity rule is a spec requirement).

- [ ] **Step 3: Implement**

In `frontend/src/features/setup/MappingTab.tsx`, replace `handleTargetChange` (currently lines 101-106) with:

```tsx
  const handleTargetChange = useCallback(
    (source: string, target: string | null) => {
      setLocalEdits((prev) => {
        const next = { ...prev, [source]: target };
        const dotIndex = source.indexOf('.');
        if (dotIndex > 0) {
          next[source.slice(0, dotIndex)] = null;
        } else {
          for (const key of Object.keys(next)) {
            if (key.startsWith(`${source}.`)) next[key] = null;
          }
        }
        return next;
      });
    },
    [],
  );
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/features/setup/MappingTable.test.tsx src/features/setup/MappingTab.test.tsx` (from `frontend/`)
Expected: ALL PASS.

- [ ] **Step 5: Full frontend verification**

Run: `npm run typecheck && npm run test` (from `frontend/`)
Expected: no type errors, all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/setup/MappingTab.tsx frontend/src/features/setup/MappingTab.test.tsx
git commit -m "feat: dotted-key save payload with exclusivity clearing in mapping tab"
```

---

### Task 6: Documentation + final verification

**Files:**
- Modify: `backend/docs/architecture.md` (mapping stage row)
- Modify: `backend/docs/api.md` (field-mapping endpoints, lines 40-42)
- Modify: `docs/decisions.md` (append entry — follow the existing `## YYYY-MM-DD` heading style seen at the file tail)
- Verify: full backend + frontend suites

**Interfaces:**
- Consumes: all implemented behavior from Tasks 1-5.
- Produces: docs matching the spec `docs/superpowers/specs/2026-09-03-nested-source-field-mapping-design.md`.

- [ ] **Step 1: Update backend architecture doc**

In `backend/docs/architecture.md`, find the pipeline stage table row for stage 2 Mapping:

```
| 2. Mapping | `MappingStep` | Apply `FeedSource.field_mapping` (auto-mapped on first run); transform source fields → registry attributes |
```

Replace with:

```
| 2. Mapping | `MappingStep` | Apply `FeedSource.field_mapping` (auto-mapped on first run); transform source fields → registry attributes. Mapping keys may be dotted source paths (`parent.sub` for structured/repeated-structured sources; an exact source-field-name match wins over path resolution). A whole-field mapping and sub-field mappings of the same parent are mutually exclusive (PUT → 422). Sub-field values broadcast over all elements of repeated sources; `attr.subfield` targets of repeated structured attributes merge element-wise by index. |
```

- [ ] **Step 2: Update API doc**

In `backend/docs/api.md`, replace the three field-mapping endpoint lines:

```
- `GET /feed-sources/{id}/field-mapping` — get mapping document
- `PUT /feed-sources/{id}/field-mapping` — save manual mappings `{mappings: {source_field: {target: registry_path}}}`
- `POST /feed-sources/{id}/field-mapping/auto` — run auto-mapper on demand
```

with:

```
- `GET /feed-sources/{id}/field-mapping` — get mapping document
- `PUT /feed-sources/{id}/field-mapping` — save manual mappings `{mappings: {source_path: {target: registry_path}}}`. `source_path` is a source field name or a dotted sub-field path `parent.sub` (parent must be a structured/repeated-structured source field, `sub` one of its sub-fields; a whole-field mapping of `parent` and its sub-field mappings are mutually exclusive). `target` is `attr` or `attr.subfield` only. Errors: 422 `{"errors": ["key: message", ...]}`
- `POST /feed-sources/{id}/field-mapping/auto` — run auto-mapper on demand (whole-field passes first — auto, then synonym — then a sub-field pass; whole-field mappings suppress sub matching for their parent, and existing sub-mappings block whole-field claims)
```

- [ ] **Step 3: Append decision record**

Append to the end of `docs/decisions.md`:

```markdown
## 2026-09-03

### Nested source field mapping representation

- **Topic:** How sub-field mappings of structured source fields are stored and governed
- **Decision:** Mapping keys in `FeedSource.field_mapping` (`MappingDocument.mappings`) are dotted source paths (`ship.price → shipping.price`). No document format change (keys are opaque strings; version stays 1). An exact source-field-name match wins over path resolution everywhere (validation, apply, auto-match). A whole-field mapping and sub-field mappings of the same parent are mutually exclusive (PUT returns 422 on conflict). Sub of `structured` behaves as `scalar`, sub of `repeated_structured` as `repeated_scalar` for kind compatibility; repeated sources broadcast per element and merge element-wise into `attr.subfield` targets by index. The auto-mapper gains a sub-field pass (sub name matched first against whole attribute names, then `attr.subfield` paths in registry order; no sub-level synonyms), suppressed by whole-field mappings of the same parent; existing sub-mappings block whole-field auto claims.
- **Rationale:** Avoids a document version bump and migration; keeps the PUT payload shape unchanged; the one ambiguity (a source column literally named `parent.sub`) is resolved by a single exact-name-first rule applied uniformly. Rejected: nested `MappingEntry.sub_mappings` (v2 migration, 33 call sites) and a parallel `sub_mappings` section (cross-dict exclusivity checks in every consumer).
```

- [ ] **Step 4: Full verification**

Run backend (from `backend/`): `uv run pytest -n auto && uv run ruff check . && uv run mypy .`
Run frontend (from `frontend/`): `npm run test && npm run typecheck`
Expected: everything green.

- [ ] **Step 5: Commit**

```bash
git add backend/docs/architecture.md backend/docs/api.md docs/decisions.md
git commit -m "docs: nested source field mapping semantics and decision record"
```

---

## Spec coverage check (self-review)

| Spec section | Task(s) |
|---|---|
| §3 dotted keys + exact-name-first disambiguation | 1 (apply), 2 (validate), 3 (matcher) |
| §4.1 validation rules (unknown parent/sub, non-structured parent, exclusivity, kind compat, ≥2 dots) | 2 |
| §4.1 legacy leniency for dotless unknown keys (preserved behavior) | 2 |
| §4.2 apply semantics (broadcast, element-wise merge, auto-extend, skip-absent, shape mismatch, stats) | 1 |
| §4.3 auto-matcher sub pass + ordering + exclusivity both directions | 3 |
| §5.1 expandable rows, per-sub Select, dotted keys, UI exclusivity | 4 (table), 5 (tab) |
| §5.3 i18n keys (en + de) | 4 |
| §6 backend tests (apply, api, matcher) | 1, 2, 3 |
| §6 frontend tests (MappingTable, MappingTab) | 4, 5 |
| §7 docs (architecture, api, decisions) | 6 |
| §8 out-of-scope guards (no positional paths, no doc migration) | Global Constraints |
