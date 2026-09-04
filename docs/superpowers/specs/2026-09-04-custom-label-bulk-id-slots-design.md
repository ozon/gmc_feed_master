# Custom Label Bulk-ID Slots & Dynamic Rules — Design

Date: 2026-09-04
Status: Approved; implementation on hold pending owner go-ahead (spec amended 2026-09-04 after owner review — see §8)

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

`config_scope: ["global", "client"]` — aligned with the Labelizer precedent: slot templates are structural and shared across markets (three-tier merge per `backend/docs/plugins.md`). Config JSON:

```json
{
  "slotRules": [
    {
      "id": "uuid",
      "name": "Mid Funnel",
      "isActive": true,
      "targetSlot": "custom_label_1",
      "matchField": "item_group_id",
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
- `matchField`: **registry attribute path** (see §2.1) — NOT a raw source field. Default `id`.
- `valueTemplate`: static text plus `{field}` tokens, where `field` is a registry attribute path (see §2.1).
- `fallbackTemplate`: optional. Declared on the **first rule in priority order that targets a given slot**; rules after the first targeting the same slot must not declare a fallback (validated at save). This makes fallback per-slot, not per-rule.
- Array order = priority index (index 0 evaluated first).

### 1.2 Plugin data

`data_scope: ["client", "feed_source"]` — shared ID lists live at client scope; a market (feed source) overrides individual rule lists without duplicating shared ones. Stored/served through the reserved plugin data route; the three-tier resolver merges `slotIds` per key (per rule `id`), so a feed_source entry overrides only that rule's list.

```json
{ "slotIds": { "<rule_id>": "id1,id2\nid3" } }
```

Raw text exactly as pasted (newlines and/or commas as separators). Parsing happens once per run (see §3); the save endpoint also parses for a live count preview but persists the raw text. Both paths use the **same shared `parse_id_list()` function** — no divergent parsing logic.

Because `config_hash` already includes each instance's `resolved_data` (backend/docs/data-model.md), a data edit at any scope changes the hash and triggers reprocessing of affected products.

## 2. Rule Engine

### 2.1 Field resolution: registry paths only

Products reaching the plugin stage are post-mapping (`apply_mapping`, M4): they contain **registry attribute names only**; unmapped source fields are dropped. Raw source fields such as `sku` do not exist here (they map onto registry targets like `id`/`offer_id`). Therefore:

- `matchField` and every `{field}` token in a template MUST be a registry attribute path, resolved against `RegistryDocument`:
  - `attr` for `scalar` / `repeated_scalar` attributes (repeated value → matches/render per element rules below).
  - `attr.subfield` for `structured` / `repeated_structured` attributes; `repeated_structured` resolves only when there is exactly one element, otherwise the path is treated as empty.
- Validated at save against the registry document; UI suggestions are drawn from the registry, not hardcoded.
- For matching, a repeated_scalar match field matches if **any** element's value is in the rule's ID set.

### 2.2 Evaluation (`process()`)

For each product:

1. Group active rules by `targetSlot`, preserving priority order within each group.
2. **Per slot:** the first rule whose match-field value (coerced with `str()`, trimmed) is a member of that rule's parsed ID set wins → render `valueTemplate` by substituting each `{field}` token with the resolved registry-path value.
3. **Token skip:** if any token in the template resolves to `None` or empty string, the rule is skipped and evaluation continues with the next rule for that slot. Static-only templates (no tokens) never skip. A missing/empty token means the rule does not match that product at all — the label is not partially rendered.
4. **Fallback:** if no rule matched for a slot and the slot declares a `fallbackTemplate`, render it (same token semantics; unresolved tokens → label left empty). Otherwise the label is omitted (null — field not written to the output product).
5. Continue to the next slot until all slots with rules are evaluated.

Matching is exact and case-sensitive after trimming. A missing match-field value means no match.

## 3. Performance & the `prepare_run` contract hook

Run-scoped preprocessing needs a home: `process()` is per product, plugin instances are module-level singletons, and runs of different feed sources may execute concurrently — instance state is unsafe.

**Contract extension:** an optional `prepare_run(config, data, ctx) -> state` hook is added to the plugin runtime contract. `PluginStep` calls it once per plugin instance per run, before the product loop, and passes the returned `state` to every `process()` call of that instance for the run. `process()` gains an optional trailing `state` parameter; plugins that do not implement `prepare_run` are unaffected (state is `None`). This is backward compatible and removes the incentive for plugins to stash per-run caches on `self`.

`custom_labels` uses `prepare_run` to:

- Parse each rule's raw ID text once — split on `\n` and `,`, trim, drop empties, deduplicate into a `frozenset[str]`. Membership checks are O(1) per product per rule.
- Compile each template once into an ordered list of literal chunks and token field names; per product it is a join, no regex re-matching.

Content-keyed memoization without instance state was rejected: hidden global state and invalidation complexity for no benefit over an explicit, per-run hook.

## 4. UI

### 4.1 Admin config interface (plugin frontend component)

Custom plugin frontend component (pattern established by `core/rules`; build-time discovery per `frontend/docs/plugin-uis.md`):

- Slot-rule list with dnd-kit vertical sorting (same `PointerSensor` activation constraint and `verticalListSortingStrategy` as `RulesUI`); drop position = new priority index.
- Editor panel: name, target-slot select (`custom_label_0`..`custom_label_4`), match-field input with suggestions from the **registry attribute list** (flat attributes plus `attr.subfield` paths for structured kinds), value-template input with a token hint (`{field} inserts the product's registry attribute value`), per-slot fallback template input.
- Save via the existing plugin config endpoint; unsaved-changes guard on navigation (same as rules UI).

### 4.2 Operational page (bulk-ID input)

- Horizontal grid of slot columns — one column per active rule, ordered by priority.
- Column header above each textarea: target slot (e.g. `custom_label_1`), match field (e.g. `item_group_id`), and the value template (e.g. `{brand} - Mid Funnel`).
- Column body: `Textarea` for bulk IDs, newline- or comma-separated.
- Wrapper has `overflow-x: auto` so more columns than fit the viewport scroll horizontally.
- Live parsed-ID count (post trim/dedupe, via the shared parser) under each textarea; save via `/plugins/custom_labels/data`.

### 4.3 Scope-aware rendering (fix, 2026-09-04)

Because `config_scope` (global, client) and `data_scope` (client, feed_source) are asymmetric, the UI must not send each payload kind's request to a URL tier the manifest does not declare (the backend answers 422 "scope not declared"). Resolution rules (`resolveKindScope` in `CustomLabelsUI`):

- URL tier declared for the kind → fetch at the URL tier.
- Feed-source URL + config → fetch at client tier (config is shared templates); the slot-rules tab renders read-only with a hint.
- Global URL + data → request not sent; the bulk-IDs tab is disabled with a hint and the slot-rules tab opens by default.
- `PluginPage` skips its generic config fetch for any plugin with a custom component (the component owns its fetching; a 422 there must not kill the page).

## 5. Validation & Error Handling

- `validate_config()` rejects: unknown `targetSlot`, empty `matchField`, empty `valueTemplate`, `matchField`/token paths that do not resolve against the registry document, duplicate rule IDs, a fallback declared on a rule that is not the first rule targeting its slot.
- **No save-time label-length check.** The ≤100-character custom-label limit is enforced by the registry-driven QC rule at run time; violations surface as QC findings, not save errors.
- A registry path that resolves to empty at run time is handled by the token-skip semantics (§2.2); no error.
- `process()` never mutates `original_product`; it writes `custom_label_N` keys on the working product copy only.

## 6. Testing

- **Backend (pytest):**
  - Shared `parse_id_list()`: split/trim/dedupe across newline and comma separators; identical results from save-preview and runtime paths.
  - Matching: hit, miss, repeated_scalar any-element match, missing match field.
  - Token rendering: full substitution, empty-token skip, static template, `attr.subfield` resolution (including repeated_structured multi-element → empty).
  - Per-slot first-match-wins with interleaved targets; fallback used when no rule matches; no fallback → label omitted.
  - `prepare_run` contract: called once per instance per run; `process()` receives the state; plugins without the hook still work (contract test `backend/tests/test_plugin_contract.py`).
  - Delta: a config edit **and** a data edit each change `config_hash` and trigger reprocessing.
- **Frontend (vitest):**
  - Parsed-ID count computation from raw text.
  - Template preview rendering.
  - Slot column layout renders one column per active rule with correct header metadata.

## 7. Out of Scope (v1)

- Condition-based inline rules inside this plugin (generic conditions remain the `core/rules` plugin's job; pipeline ordering composes them).
- Import/export of ID lists as files.
- Case-insensitive or partial ID matching.
- **`_source` sidecar** (carrying raw pre-mapping source values alongside mapped output): deferred with rationale. It would ripple through `apply_mapping`, staging hashes, and QC — a contract-level change not justified by the labelizer use case, since match targets (`id`, `item_group_id`, `brand`, …) are registry attributes. Revisit only if matching on raw pre-mapping values becomes a requirement.

## 8. Owner Review Amendments (2026-09-04)

Resolved with the owner before implementation:

1. **Scopes aligned with Labelizer:** `config_scope: ["global", "client"]` (was `["client", "feed_source"]`); `data_scope: ["client", "feed_source"]` (was `["feed_source"]`) so markets can override individual ID lists without duplicating shared ones.
2. **Field resolution restricted to registry paths** (§2.1) — the original design's `matchField: "sku"` was invalid: post-mapping products contain registry attributes only (M4 drop-unmapped). `_source` sidecar deferred with rationale (§7).
3. **`prepare_run(config, data, ctx) -> state` contract hook** added (§3) — run-scoped preprocessing now has a contract-sanctioned home; singleton instance state under concurrent runs is avoided.

This plugin replaces the "Labelizer" entry in `gmc-feed-engine-spec.md` §5.9; the engine-spec update (name, scopes, rule shape) lands with spec v7. Until then the engine spec is knowingly stale on this point — flagged to the operator per the documentation rule.
