# Labelizer View & Overlap Logic — Design

Date: 2026-09-07
Status: Approved (brainstorming session 2026-09-07)
Scope: Labelizer **data page** (feed-level bulk-ID surface) only; `LabelizerSetup` (rule config surface) is untouched.

## Problem

The Labelizer data page (`CustomLabelsUI` with `onlyTab="ids"`, reached via `LabelizerPage`) stacks one `SlotGroup` card per populated slot. Users must scroll through all slots, cannot see overall coverage at a glance, cannot collapse individual rules, and get no signal when an ID list contains values that a higher-priority rule already claims (first-match-wins semantics make those entries inert). The `idCount` footer rendered inside the Textarea `bottomSection` overlaps the last lines of the input.

## Decisions (from brainstorming)

1. **Surface scope:** data page only.
2. **Coverage metric:** any-slot — "N / M staged products labeled" counts products carrying at least one custom label. Requires a small backend extension (per-slot counts overlap, so it is not client-derivable).
3. **Shadowing detection:** client-side, syntactic — a value is shadowed when a higher-priority **active** rule of the same slot already contains it (or is `all`-mode). Instant updates while typing, exact per-ID attribution, no backend involvement.
4. **ID presentation:** keep the editable Textarea; add a "Shadowed IDs" section listing only shadowed values with strikethrough + tooltip. Full styled ID-list rendering was rejected for performance (lists reach ~10k IDs).

## 1. Backend: any-slot coverage

`evaluate_rules` (plugins/core/custom_labels/plugin.py) gains an any-label tracker: for each staged product, set a flag when any slot's evaluation produced a winner (including fallback winners). Response gains `labeledAny: number`. Request shape, validation, and existing response fields are unchanged.

Frontend `PreviewResult` (features/customLabels/usePreview.ts) gains `labeledAny?: number`.

Dashboard quick stats derive as:

| Stat | Source |
|---|---|
| Total Products | `preview.total` |
| Labeled Count | `preview.labeledAny` |
| Unlabeled Count | `total − labeledAny` |
| Total Active Rules | count of active rules across all slots (client-side, merged rules) |

Progress bar: `labeledAny / total` percent — green section for labeled, gray remainder; caption "74 / 389 staged products labeled" (i18n). States as today: pending (Loader), preview-unavailable, errors, "no staged products" when `total === 0`.

## 2. Shadowing module — `features/customLabels/shadowing.ts`

```ts
export type RuleShadowInfo = {
  shadowed: Set<string>;          // values ignored in this rule
  shadowedBy: Map<string, string>; // value -> name of first higher-priority claimer
};
export function computeShadowing(
  rules: ScopedSlotRule[],
  values: Record<string, string>,
): Record<string, RuleShadowInfo>; // keyed by rule id
```

Algorithm, per slot (rules grouped by `targetSlot`):

- Walk **active** rules in evaluation order (the merged array order), maintaining `claimed: Map<value, ruleName>` for the slot.
- `values`-mode rule: parse its ID list (`parseIdList` from `./ids`); a value already in `claimed` is shadowed (attributed to the claimer); otherwise claim it under this rule's name.
- `all`-mode rule: claims no specific values but marks **every** value of all lower-priority active rules in the slot as shadowed, attributed to the all-mode rule's name.
- Inactive rules are skipped entirely: they neither claim nor are shadowed and are not shown on the data page (existing behavior — data page lists active rules only).

Pure module; unit-tested in isolation.

## 3. UI structure (ids panel)

```
ScopeContextBar            (unchanged)
SlotSelector               Mantine SegmentedControl, options CUSTOM_LABEL_0..4
                           (all five, always); default = first slot with active
                           rules, else custom_label_0; selection is local state
CoverageDashboard          Card: caption, Progress (green/gray), 4 quick stats
Rule cards                 Mantine Accordion (chevron, multiple expand, all
                           collapsed by default); one Accordion.Item per active
                           rule of the selected slot, in evaluation order
  Header                   Rule name · `#N Priority` badge (index in the slot's
                           active-rule order) · matched badge from preview
                           ruleStats (`18 Matched`, existing neverApplied
                           tooltip retained) · shadowed badge (`3 Overridden`,
                           only when count > 0) · inherited-from badge (existing
                           scope badge) · value-template preview text
  Panel                    Values mode: Textarea for IDs (as today, editable,
                           inherited-value semantics unchanged). All mode: the
                           existing controlled-by-rule Paper. Plus ShadowList
                           (only when shadowed values exist): each value with
                           `text-decoration: line-through`, dimmed color, Tooltip
                           "Already matched by higher priority rule: <Rule Name>"
Empty selected slot         Dimmed "no rules for this slot" notice
```

- **Overlap bug fix:** the `9734 unique IDs` counter moves out of the Textarea `bottomSection` to a `Text` below the Textarea with proper `Stack` gap — removes the clipping/overlap entirely rather than patching CSS.
- **Component boundaries:** new `SlotSelector`, `CoverageDashboard`, `RuleCard`, `ShadowList` components; `SlotGroup.tsx` is retired (its slot-level stats move to `CoverageDashboard`; per-rule columns become `RuleCard`s). `RuleCard` renders an `Accordion.Item` and is only used inside the ids panel's `Accordion`.
- **State:** slot selection and card expansion are local `useState`; ID values continue to flow through the existing `slotIds` draft state (whole-dict save to the current data tier, dirty blocking, Save/Cancel buttons — unchanged).
- **i18n:** new keys in the `customLabels` namespace (priority badge, coverage caption/stats, shadowed/overridden, shadow tooltip, empty slot).

## 4. Error handling

Unchanged from today: config/data query errors render `ErrorState` with retry; preview 422s render inline error text; preview unavailability degrades the dashboard to the unavailable notice while rule cards still work (shadowing is client-side and remains available).

## 5. Testing

- `shadowing.test.ts` (new): claims order, duplicates across rules, all-mode shadowing, inactive-rule skipping, empty lists.
- `CustomLabelsUI.test.tsx`: update for SegmentedControl slot switching, dashboard stats, accordion expand/collapse, shadow badges and shadow list, ID counter placement.
- `usePreview.test.tsx`: assert `labeledAny` mapping.
- Backend: extend `evaluate_rules` tests for `labeledAny`; run plugin contract tests (`uv run pytest backend/tests/test_plugin_contract.py`).
- Full gates: `uv run pytest -n auto`, `uv run ruff check .`, `uv run mypy .` (backend); `npm run test`, `npm run typecheck`, `npm run build` (frontend).

## 6. Documentation updates (same change)

- `backend/docs/api.md` and/or `backend/docs/plugins.md`: preview response now includes `labeledAny`.
- `frontend/docs/` pages describing the Labelizer data page layout, if any.
- No ADR changes: merge semantics, save semantics, and pipeline order are untouched (ADR-0005 consequence note still accurate).

## Out of scope

- `LabelizerSetup` (rules config surface) — no slot SegmentedControl, priority badges, or card redesign there.
- Drag-reorder of rules on the data page (ordering is edited in Setup).
- Backend semantic shadowing (staged-product-based) — may be revisited later.
- Virtualized full ID-list rendering.
