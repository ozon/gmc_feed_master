## Task 6: QC Rules — All 12 Implementations

**Status:** DONE

### Commits
- `2c0acf2` — feat(qc): implement all 12 QC rules

### Test Summary
42 tests passing across all 12 rules (42/42 passed in 2.88s)

### Files Created
- `backend/app/qc/rules.py` — All 12 rule classes
- `backend/tests/test_qc_rules.py` — Unit tests for each rule

### Rules Implemented
1. **BaselineRequired** — Per-product, critical. Checks 6 required fields + title/structured_title + description/structured_description
2. **BrandRequired** — Per-product, warning. Exempt taxonomy IDs for Books, DVDs, Music
3. **GtinMpn** — Per-product, mixed. Missing GTIN → warning (requires mpn+brand); invalid GS1 checksum → critical
4. **EnumValues** — Per-product, critical. Registry-driven enum validation
5. **ConditionalRequired** — Per-product, warning. Preorder needs date; unit_pricing_base_measure needs unit_pricing_measure
6. **DateFormat** — Per-product, critical. ISO 8601 with timezone for 3 date fields
7. **LengthLimits** — Per-product, warning. Registry-driven max_length constraints
8. **CardinalityRule** — Per-product, warning. Registry-driven min/max items + item_max_length
9. **CurrencyConsistency** — Per-product, critical. Currency prefix must match ctx.currency
10. **ImageRequirements** — Per-product, mixed. Format check, probe for dimensions, severity changes on enforcement date
11. **VariantConsistency** — Cross-product, warning. Groups by item_group_id, checks 8 base attrs
12. **VolumeDrop** — Cross-product, warning. Compares current vs previous export run count

### Concerns
- `CurrencyConsistency` expects price format `"USD 10"` (currency-first), not `"10 USD"`. This is intentional per the implementation in the task brief.
