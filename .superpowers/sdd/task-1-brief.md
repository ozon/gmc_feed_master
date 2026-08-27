### Task 1: Registry Extension — Cardinality Fields + Parser Fix

**Goal:** Add `min_items` and `item_max_length` to `Cardinality`, fix the parser regex to capture them, and regenerate `attributes.json`.

**Files:**
- Modify: `backend/registry/model.py`
- Modify: `backend/registry/parser.py`
- Modify: `backend/registry/generate.py`
- Modify: `backend/registry/loader.py`
- Regenerate: `backend/registry/attributes.json`
- Modify: `backend/tests/test_registry_parser.py`

**Interfaces:**
- Produces: `Cardinality.min_items: int | None`, `Cardinality.item_max_length: int | None`

#### Steps

- [ ] **Step 1: Add `min_items` and `item_max_length` to `Cardinality`**

```python
# backend/registry/model.py — Cardinality dataclass
@dataclass(frozen=True, slots=True)
class Cardinality:
    max_items: int | None = None
    min_items: int | None = None
    item_max_length: int | None = None
```

- [ ] **Step 2: Fix parser `_constraints()` regex and add `min_items`/`item_max_length` extraction**

The current fallback regex `max\.?\s*(?:of\s*)?(\d+)\b` matches "max 500 MB" as `max_length=500`. Fix it to require the word "char" or be inside a character-length context. Also add extraction of `min_items` from "min. N" patterns and `item_max_length` from "1–150 chars each" patterns.

```python
# backend/registry/parser.py — _constraints function (lines 46-90)
def _constraints(description: str) -> tuple[Constraints, Cardinality]:
    constraints = Constraints()
    cardinality = Cardinality()

    # Existing exact patterns (keep as-is)
    if m := re.search(r"max(?:imum)?\s+(\d[\d,]*)\s+char", description, re.IGNORECASE):
        constraints.max_length = _parse_int(m.group(1))
    if m := re.search(r"min(?:imum)?\s+(\d[\d,]*)\s+char", description, re.IGNORECASE):
        constraints.min_length = _parse_int(m.group(1))
    if m := re.search(r"exactly\s+(\d[\d,]*)\s+char", description, re.IGNORECASE):
        constraints.max_length = constraints.min_length = _parse_int(m.group(1))

    # Fixed fallback: only match "max N" when followed by char/letter context or at end of sentence
    if constraints.max_length is None:
        if m := re.search(r"max\.?\s*(\d+)\s*(?:char|letter)", description, re.IGNORECASE):
            constraints.max_length = _parse_int(m.group(1))
        elif m := re.search(r"max\.?\s*(\d+)\s*\.", description):
            constraints.max_length = _parse_int(m.group(1))

    # Format detection (keep as-is)
    if re.search(r"\bURL\b", description):
        constraints.format = "url"
    elif re.search(r"\bISO\s+8601\b", description):
        constraints.format = "date"

    # Cardinality: max_items from "up to N" or "max. N" (non-char context)
    if m := re.search(r"up\s+to\s+(\d+)", description, re.IGNORECASE):
        cardinality.max_items = _parse_int(m.group(1))
    if m := re.search(r"max\.?\s*(\d+)\s*(?:item|product|entry|element|value)", description, re.IGNORECASE):
        cardinality.max_items = _parse_int(m.group(1))

    # NEW: min_items from "min. N" patterns
    if m := re.search(r"min\.?\s*(\d+)\s*(?:item|product|entry|element|value)", description, re.IGNORECASE):
        cardinality.min_items = _parse_int(m.group(1))

    # NEW: item_max_length from "1–150 chars each" or "up to 150 chars each"
    if m := re.search(r"(?:up\s+to\s+)?(\d+)\s*[-–]\s*(\d+)\s*char", description, re.IGNORECASE):
        cardinality.item_max_length = _parse_int(m.group(2))
    elif m := re.search(r"(\d+)\s+char\s+each", description, re.IGNORECASE):
        cardinality.item_max_length = _parse_int(m.group(1))

    return constraints, cardinality
```

- [ ] **Step 3: Update `_type_info()` to populate `min_items` from "up to N" patterns**

```python
# backend/registry/parser.py — _type_info function (around line 225)
# After existing cardinality.max_items assignment, add:
    # min_items from "min. N items" pattern
    if m := re.search(r"min\.?\s*(\d+)\s*(?:item|product|entry|element|value)", description, re.IGNORECASE):
        cardinality.min_items = _parse_int(m.group(1))
```

- [ ] **Step 4: Update `generate.py` `_as_json()` to include new fields**

```python
# backend/registry/generate.py — _as_json function (line 10)
def _as_json(document: RegistryDocument) -> dict[str, Any]:
    return {
        "attributes": {
            name: {
                "type": info.type,
                "cardinality": {
                    key: value
                    for key, value in {
                        "max_items": info.cardinality.max_items,
                        "min_items": info.cardinality.min_items,
                        "item_max_length": info.cardinality.item_max_length,
                    }.items()
                    if value is not None
                } if info.cardinality.max_items is not None or info.cardinality.min_items is not None or info.cardinality.item_max_length is not None else None,
                "constraints": {
                    key: value
                    for key, value in {
                        "max_length": info.constraints.max_length,
                        "min_length": info.constraints.min_length,
                        "format": info.constraints.format,
                    }.items()
                    if value is not None
                } if info.constraints else None,
                "enum_values": info.enum_values or None,
            }
            for name, info in document.attributes.items()
        }
    }
```

- [ ] **Step 5: Update `loader.py` to parse new fields**

```python
# backend/registry/loader.py — _parse_attributes function (line 53)
# Update Cardinality construction:
    cardinality_data = attr.get("cardinality") or {}
    cardinality = Cardinality(
        max_items=cardinality_data.get("max_items"),
        min_items=cardinality_data.get("min_items"),
        item_max_length=cardinality_data.get("item_max_length"),
    )
```

- [ ] **Step 6: Run tests to verify parser changes don't break existing behavior**

Run: `cd backend && python -m pytest tests/test_registry_parser.py tests/test_registry_generation.py -v`
Expected: PASS (existing tests should still pass with updated expectations)

- [ ] **Step 7: Update parser test assertions**

```python
# backend/tests/test_registry_parser.py — update cardinality assertions
# The product_highlight attribute should now have min_items=2, max_items=100, item_max_length=150
# The additional_image_link attribute should have max_items=10
# Update any test that asserts cardinality.max_items for additional_image_link:
assert document.attributes["additional_image_link"].cardinality.max_items == 10
# Add new assertions for min_items and item_max_length where applicable
```

- [ ] **Step 8: Regenerate attributes.json and verify gate**

Run: `cd backend && python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json`
Run: `cd backend && python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check`
Expected: PASS (gate green)

- [ ] **Step 9: Commit**

```bash
git add backend/registry/model.py backend/registry/parser.py backend/registry/generate.py backend/registry/loader.py backend/registry/attributes.json backend/tests/test_registry_parser.py
git commit -m "feat(registry): add min_items/item_max_length to Cardinality, fix parser regex"
```

---

