# Task 6: XML Reader (GMC Feed XML) — Report

## Status: DONE

## Commits

- `fd3418f` — feat: XML reader for GMC feed format (rss/atom)

## Summary

Implemented `app/ingest/xml_reader.py` with `parse_xml(data: bytes, registry: RegistryDocument) -> IngestReport` and `XmlParseError`.

### Implementation details

- Detects root element: `rss` → `channel/item`; `feed` (Atom) → `entry`
- Strips `g:` namespace prefix from element tags via `_strip_ns()`
- Handles Atom's default namespace (`xmlns="http://www.w3.org/2005/Atom"`) by preserving namespace URI when finding `entry` elements
- Repeated sibling elements → Python list (single occurrence stays scalar, consistent with delimited reader)
- Nested elements → dicts via recursive `_element_to_dict()`
- Mixed content (text + children) → `ValueError` → per-item `RowError`
- Malformed XML → `XmlParseError` (run-level failure)
- Bad items → caught per-item, skipped, `row_errors` populated

### Files created

- `backend/app/ingest/xml_reader.py` — implementation (105 lines)
- `backend/tests/test_xml_reader.py` — 6 test classes, 6 tests
- `backend/tests/fixtures/feeds/simple_rss.xml` — RSS with `g:`-namespaced tags
- `backend/tests/fixtures/feeds/simple_atom.xml` — Atom with bare tags
- `backend/tests/fixtures/feeds/nested_shipping.xml` — nested `g:shipping`
- `backend/tests/fixtures/feeds/repeated_images.xml` — repeated `g:additional_image_link`
- `backend/tests/fixtures/feeds/malformed.xml` — invalid XML
- `backend/tests/fixtures/feeds/bad_item.xml` — mixed content in `g:shipping`

## Test summary

6/6 passing — `uv run pytest tests/test_xml_reader.py -x -q` → green

| Test | What it verifies |
|------|-----------------|
| `TestRSS` | 3 products parsed from `g:`-namespaced RSS |
| `TestAtom` | 3 products parsed from Atom with default namespace |
| `TestNestedShipping` | Nested elements → `{"shipping": {"country": "US", "price": "6.49 USD"}}` |
| `TestRepeatedImages` | Multiple siblings → list; single sibling → scalar |
| `TestMalformedXML` | Raises `XmlParseError` |
| `TestBadItem` | Mixed content item skipped, `row_errors` populated, valid item preserved |

## Concerns

None. All task requirements met.
