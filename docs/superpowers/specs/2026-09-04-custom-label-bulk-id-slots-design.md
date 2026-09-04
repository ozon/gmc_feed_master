# Custom Label Bulk-ID Slots & Dynamic Rules — Design

Date: 2026-09-04
Status: Approved (pending spec review)

## Overview

Client-specific rule extension for Google Shopping custom labels (`custom_label_0` .. `custom_label_4`). Users define ordered slot rules that match products against bulk lists of IDs and assign label values from dynamic templates. Shipped as a new dedicated core plugin, `custom_labels`.

Decisions made during brainstorming:

- **New dedicated plugin** (`plugins/core/custom_labels/`), not an extension of `core/rules`.
- **Storage split:** slot-rule definitions (structure) = plugin **config**; bulk-ID lists (operational, frequently edited) = plugin **data** via the reserved `/plugins/{id}/data` route.
- **Unified priority matrix:** a single ordered rule list; array order is the priority index, managed with dnd-kit drag-and-drop.
- **Rule shape:** each rule is one thing — "product's `<matchField>` exists in this slot's ID list" → set `<targetSlot>` to the rendered `valueTemplate`. No separate condition engine; the match *is* the condition and the label assignment *is* the action.
- **Multiple slots per product:** evaluation continues after a match. First-match-wins applies **per slot**: a product can receive values in several slots from different rules; if two rules target the same slot, the higher-priority matching rule wins for that slot.
- **Per-slot fallback:** each slot may declare an optional fallback template used when no rule fills it.

## 1. Data Model

### 1.1 Plugin config

`config_scope: ["client", "feed_source"]` (three-tier merge per `backend/docs/plugins.md`). Config JSON:

```json
{
  "slotRules": [
    {
      "id": "uuid",
      "name": "Mid Funnel",
      "isActive": true,
      "targetSlot": "custom_label_1",
      "matchField": "sku",
      "valueTemplate": "{brand} - Mid Funnel",
      "fallbackTemplate": ""
    }
  ]
}
```

- `id`: stable UUID; keys the rule's bulk-ID entry in plugin data and dnd ordering.
- `name`: display name (e.g. "Mid Funnel", "Rising Stars").
- `isActive`: inactive rules are skipped at evaluation and their textarea hidden on the operational page.
- `targetSlot`: enum, `custom_label_0` .. `custom_label_4`.
- `matchField`: free-form product field name (default `id`); suggestions offered in UI: `id`, `sku`, `item_group_id`.
- `valueTemplate`: static text plus `{field_name}` tokens (regex `\{([a-zA-Z0-9_]+)\}`).
- `fallbackTemplate`: optional. Declared on the **first rule in priority order that targets a given slot**; rules after the first targeting the same slot must not declare a fallback (validated at save). This makes fallback per-slot, not per-rule.
- Array order = priority index (index 0 evaluated first).

### 1.2 Plugin data

`data_scope: ["feed_source"]`, stored/served through the reserved plugin data route:

```json
{ "slotIds": { "<rule_id>": "id1,id2\nid3" } }
```

Raw text exactly as pasted (newlines and/or commas as separators). Parsing happens at feed-run time; the save endpoint also parses for a live count preview but persists the raw text.

## 2. Rule Engine (`process()`)

For each product:

1. Group active rules by `targetSlot`, preserving priority order within each group.
2. **Per slot:** the first rule whose `product[matchField]` (coerced with `str()`, trimmed) is a member of that rule's parsed ID set wins → render `valueTemplate` by substituting each `{field}` token with `product[field]`.
3. **Token skip:** if any token in the template resolves to `None` or empty string, the rule is skipped and evaluation continues with the next rule for that slot. Static-only templates (no tokens) never skip. A missing/empty token means the rule does not match that product at all — the label is not partially rendered.
4. **Fallback:** if no rule matched for a slot and the slot declares a `fallbackTemplate`, render it (same token semantics; unresolved tokens → label left empty). Otherwise the label is omitted (null — field not written to the output product).
5. Continue to the next slot until all slots with rules are evaluated.

Matching is exact and case-sensitive after trimming. Non-string product values are coerced with `str()`; a missing match-field value means no match.

## 3. Performance

- **One-time parse per run:** at the start of `process()`, each rule's raw ID text is split on `\n` and `,`, trimmed, empties dropped, deduplicated into a `frozenset[str]`. Membership checks are O(1) per product per rule.
- **Pre-compiled templates:** each template is compiled once into an ordered list of literal chunks and token field names; per product it is a join, no regex re-matching.
- Both artifacts (ID sets, compiled templates) are computed in a run-scoped preprocessing step, not per product.

## 4. UI

### 4.1 Admin config interface (plugin frontend component)

Custom plugin frontend component (pattern established by `core/rules`; build-time discovery per `frontend/docs/plugin-uis.md`):

- Slot-rule list with dnd-kit vertical sorting (same `PointerSensor` activation constraint and `verticalListSortingStrategy` as `RulesUI`); drop position = new priority index.
- Editor panel: name, target-slot select (`custom_label_0`..`custom_label_4`), match-field input with datalist suggestions (`id`, `sku`, `item_group_id`), value-template input with a token hint (`{field_name} inserts the product's field value`), per-slot fallback template input.
- Save via the existing plugin config endpoint; unsaved-changes guard on navigation (same as rules UI).

### 4.2 Operational page (bulk-ID input)

- Horizontal grid of slot columns — one column per active rule, ordered by priority.
- Column header above each textarea: target slot (e.g. `custom_label_1`), match field (e.g. `sku`), and the rendered value template (e.g. `{brand} - Mid Funnel`).
- Column body: `Textarea` for bulk IDs, newline- or comma-separated.
- Wrapper has `overflow-x: auto` so more columns than fit the viewport scroll horizontally.
- Live parsed-ID count (post trim/dedupe) under each textarea; save via `/plugins/custom_labels/data`.

## 5. Validation & Error Handling

- `validate_config()` rejects: unknown `targetSlot`, empty `matchField`, empty `valueTemplate`, duplicate rule IDs, a fallback declared on a rule that is not the first rule targeting its slot.
- Templates referencing non-existent product fields: token resolves empty → rule skipped (engine semantics above); no error.
- `process()` never mutates `original_product`; it writes `custom_label_N` keys on the working product copy only.

## 6. Testing

- **Backend (pytest):**
  - ID parsing: split/trim/dedupe across newline and comma separators.
  - Matching: hit, miss, non-string coercion, missing match field.
  - Token rendering: full substitution, empty-token skip, static template.
  - Per-slot first-match-wins with interleaved targets; fallback used when no rule matches; no fallback → label omitted.
  - Plugin contract test (`backend/tests/test_plugin_contract.py`).
- **Frontend (vitest):**
  - Parsed-ID count computation from raw text.
  - Template preview rendering.
  - Slot column layout renders one column per active rule with correct header metadata.

## 7. Out of Scope (v1)

- Condition-based inline rules inside this plugin (generic conditions remain the `core/rules` plugin's job; pipeline ordering composes them).
- Import/export of ID lists as files.
- Case-insensitive or partial ID matching.
