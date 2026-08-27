### Task 1: Registry Extension — Cardinality Fields + Parser Fix

**Status:** DONE

**Commits:**
- `7b8777f` feat(registry): add min_items/item_max_length to Cardinality, fix parser regex

**Test Summary:**
- 13 passed, 0 failed — `test_registry_parser.py` (10 tests) + `test_registry_generation.py` (3 tests)

**Changes Made:**
1. `registry/model.py` — Added `min_items: int | None = None` and `item_max_length: int | None = None` to `Cardinality` dataclass (pre-existing)
2. `registry/parser.py` — Fixed `_constraints()` fallback regex:
   - Changed `max\.\s*(\d+)\.` to `max\.\s*(\d+)\s+(?=[A-Z])(?!MB\b|s\b|px\b|year\b|chars?\b)`
   - This matches "max. N" in spec contexts (followed by space+uppercase letter) while rejecting unit contexts (MB, s, px, year, chars)
3. `registry/generate.py` — Included `min_items` and `item_max_length` in `_as_json()` cardinality output (pre-existing)
4. `registry/loader.py` — Parsed `min_items` and `item_max_length` from JSON in `_parse_attributes()` (pre-existing)
5. `registry/attributes.json` — Regenerated from gmc_def.md
6. `tests/test_registry_parser.py` — Added assertions for cardinality fields and parser regex fixes (pre-existing)

**Key Regex Fix Detail:**
The original fallback regex `max\.?\s*(?:of\s*)?(\d+)\b` matched "max 500 MB" as max_length=500. The fix uses:
- Primary: `max\.?\s*(\d+)\s*(?:char|letter)` — matches "max N char/letter" patterns
- Fallback: `max\.\s*(\d+)\s+(?=[A-Z])(?!MB\b|s\b|px\b|year\b|chars?\b)` — matches "max. N" only when followed by space+uppercase letter (spec context like "max. 150 Required"), excluding known units

**Concerns:** None — all tests pass, gate is green.
