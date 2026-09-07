# Labelizer View & Overlap Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Labelizer data page (feed-level bulk-ID surface) into a slot-selected view with a coverage dashboard, collapsible priority-ordered rule cards, client-side shadowed-ID detection, and a fixed ID-counter overlap bug.

**Architecture:** Backend `evaluate_rules` gains an any-slot `labeledAny` count (small response extension). Frontend adds a pure `shadowing.ts` module (syntactic first-match-wins analysis of ID lists) plus four new components — `SlotSelector`, `CoverageDashboard`, `RuleCard`, `ShadowList` — and rewires the `idsPanel` of `CustomLabelsUI` from stacked `SlotGroup` cards to a SegmentedControl-selected single-slot view. `SlotGroup.tsx` is deleted. The rules config surface (`LabelizerSetup` path) is untouched.

**Tech Stack:** React 19, TypeScript, Mantine 9.5.2, TanStack Query, i18next (en/de), vitest + React Testing Library; Python/FastAPI plugin, pytest.

## Global Constraints

- Mantine version is 9.5.2 — do not add dependencies or upgrade.
- Spec: `docs/superpowers/specs/2026-09-07-labelizer-view-refactor-design.md` (read it first).
- The rules config surface (`rulesPanel`, `LabelizerSetup`, `SortableRuleRow`, `MatchFieldCombobox`) must keep working unchanged.
- Every user-visible string goes through i18next namespace `customLabels`; both `frontend/public/locales/en/customLabels.json` AND `frontend/public/locales/de/customLabels.json` get every new key.
- Backend commands run from `backend/`; frontend commands run from `frontend/`.
- Frontend test invocation: `npm run test -- --run <file>` (vitest). Typecheck: `npm run typecheck`.
- Backend test invocation: `uv run pytest tests/<file> -q`. Lint/typecheck: `uv run ruff check .` and `uv run mypy .`.
- Plugin contract test must pass after the plugin changes: `uv run pytest tests/test_plugin_contract.py -q`.
- Scope merge semantics, save semantics (whole `slotIds` dict saved to the current data tier), and dirty blocking are unchanged.
- Commit style: conventional commits with scope, e.g. `feat(frontend): ...`, `feat(backend): ...`, `docs: ...`.

---

### Task 1: Backend — `labeledAny` in the preview response

**Files:**
- Modify: `plugins/core/custom_labels/plugin.py` (`evaluate_rules`, ~line 195-255)
- Modify: `backend/tests/test_custom_labels_preview.py` (add one test to `TestPreviewRoute`)
- Modify: `backend/docs/api.md:95`
- Modify: `backend/docs/plugins.md` (~line 236-244, the `POST /plugins/custom_labels/preview` block)

**Interfaces:**
- Consumes: nothing new.
- Produces: `evaluate_rules(...)` returns `{"total": int, "labeledAny": int, "rules": {...}, "slots": {...}}`. Frontend `PreviewResult` gains `labeledAny?: number` (Task 3 relies on the JSON key `labeledAny`).

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_custom_labels_preview.py`, add this test inside `class TestPreviewRoute:` (after `test_mounted_route_returns_counts`):

```python
    async def test_labeled_any_counts_products_labeled_in_any_slot(self, app_factory):
        client = await logged_in_client(app_factory)
        _app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            _rule("r1", "custom_label_0", matchField="brand"),
            _rule("r2", "custom_label_1", matchField="id", valueTemplate="fixed"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "Acme", "r2": "nobrand"},
        })
        assert resp.status_code == 200
        body = resp.json()
        # active, non-excluded rows: a1 (brand Acme), a2 (brand Beta), nobrand (brand "")
        # a1 labeled in slot 0 (brand match, "{brand} - r1" renders);
        # nobrand labeled in slot 1 (id match, token-free template);
        # a2 labeled nowhere -> labeledAny counts the UNION, not the sum.
        assert body["total"] == 3
        assert body["labeledAny"] == 2
        assert body["slots"]["custom_label_0"]["labeled"] == 1
        assert body["slots"]["custom_label_1"]["labeled"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `backend/`): `uv run pytest tests/test_custom_labels_preview.py -k labeled_any -q`
Expected: FAIL with `KeyError: 'labeledAny'` (assertion error on `body["labeledAny"]`).

- [ ] **Step 3: Implement `labeledAny` in `evaluate_rules`**

In `plugins/core/custom_labels/plugin.py`, edit `evaluate_rules`. Replace the product loop and the return statement (the loop beginning `for product_id, product in rows:` through `return {"total": total, "rules": per_rule, "slots": slots}`):

```python
    labeled_any = 0
    for product_id, product in rows:
        product = product or {}
        product_labeled = False
        for slot, slot_rules in by_slot.items():
            winner: str | None = None
            any_matched = False
            for rule in slot_rules:
                if not rule["matchAll"] and not matches(
                    product, rule["matchField"], rule["ids"]
                ):
                    continue
                any_matched = True
                stats = per_rule[rule["id"]]
                stats["matched"] += 1
                if len(stats["sample"]) < sample_size:
                    stats["sample"].append(product_id)
                if winner is None:
                    value = render_template(rule["template"], product)
                    if value is not None:
                        winner = rule["id"]
                        stats["labeled"] += 1
            if winner is None and any_matched and slot_rules[0]["fallback"]:
                fallback_value = render_template(slot_rules[0]["fallback"], product)
                if fallback_value:
                    winner = slot
            if winner is not None:
                slots[slot]["labeled"] += 1
                product_labeled = True
        if product_labeled:
            labeled_any += 1

    if total:
        for entry in slots.values():
            entry["coverage"] = round(entry["labeled"] / total * 100, 1)
    return {
        "total": total,
        "labeledAny": labeled_any,
        "rules": per_rule,
        "slots": slots,
    }
```

Also update the `evaluate_rules` docstring: append one line — `Response also carries labeledAny: products labeled in at least one slot (fallback wins included).`

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `backend/`): `uv run pytest tests/test_custom_labels_preview.py -q`
Expected: all PASS (existing tests unaffected — the response only gains a key).

- [ ] **Step 5: Run the plugin contract test and gates**

Run (from `backend/`): `uv run pytest tests/test_plugin_contract.py -q && uv run ruff check . && uv run mypy .`
Expected: all PASS.

- [ ] **Step 6: Update backend docs**

In `backend/docs/api.md` line 95, change the Response shape and add the `labeledAny` explanation:

```
- `POST /plugins/custom_labels/preview` — live custom-labels preview. Body: `{feed_source_id, rules, slotIds, sample_size}` (1–50, default 5). Response `{total, labeledAny, rules: {id: {matched, labeled, sample}}, slots: {slot: {labeled, coverage, rules}}}` over active, non-excluded staged products; `labeledAny` counts products labeled in at least one slot (fallback wins included). Evaluation mirrors the plugin's run-time `process()` exactly (first-match-wins per slot, token skip, first-rule fallback); `labeled` per rule counts only template-rendered wins, fallback wins credit the slot. 404 unknown feed source; 422 `{"errors": [...]}` on invalid rules; 503 database unavailable.
```

In `backend/docs/plugins.md`, in the `POST /plugins/custom_labels/preview` block (~line 236), change the Response sentence to:

```
- `POST /plugins/custom_labels/preview` — live preview of draft rules against
  staged products. Body: `{feed_source_id, rules, slotIds, sample_size (1–50,
  default 5)}`. Response `{total, labeledAny, rules: {id: {matched, labeled,
  sample}}, slots: {slot: {labeled, coverage, rules}}}` against active,
  non-excluded staged products (raw_data as mapped state); `labeledAny` counts
  products labeled in at least one slot. Evaluation mirrors the plugin's
  run-time `process()` exactly: a rule matches when a candidate value of its
  matchField is in the rule's id list (`matchAll` rules match every product);
  first-match-wins per slot with token skip; the first rule's fallback credits
  the slot, never a rule. 404 unknown feed source; 422 `{"errors": [...]}`
  on invalid rules; 503 database unavailable.
```

- [ ] **Step 7: Commit**

```bash
git add plugins/core/custom_labels/plugin.py backend/tests/test_custom_labels_preview.py backend/docs/api.md backend/docs/plugins.md
git commit -m "feat(backend): custom_labels preview returns labeledAny (any-slot coverage)"
```

---

### Task 2: Frontend — pure shadowing module

**Files:**
- Create: `frontend/src/features/customLabels/shadowing.ts`
- Test: `frontend/src/features/customLabels/shadowing.test.ts`

**Interfaces:**
- Consumes: `parseIdList` from `./ids` (exists: `parseIdList(raw: string | undefined | null): Set<string>`), `ScopedSlotRule` from `./scopeMerge` (has `id, name, isActive, targetSlot, matchField, matchMode?: 'values' | 'all', valueTemplate, fallbackTemplate, origin`).
- Produces: `computeShadowing(rules: ReadonlyArray<ScopedSlotRule>, values: Readonly<Record<string, string>>): Record<string, RuleShadowInfo>` where `RuleShadowInfo = { shadowed: Set<string>; shadowedBy: Map<string, string> }` — keyed by rule id; `shadowedBy` maps each shadowed value to the name of the first higher-priority claiming rule. Tasks 5 and 6 rely on these exact names.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/customLabels/shadowing.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { computeShadowing } from './shadowing';
import type { ScopedSlotRule } from './scopeMerge';

function rule(
  over: Partial<ScopedSlotRule> & { id: string; name: string; targetSlot: string },
): ScopedSlotRule {
  return {
    isActive: true,
    matchField: 'id',
    matchMode: 'values',
    valueTemplate: 'x',
    fallbackTemplate: '',
    ...over,
  };
}

describe('computeShadowing', () => {
  it('marks values claimed by a higher-priority rule of the same slot', () => {
    const rules = [
      rule({ id: 'a', name: 'Bleeder', targetSlot: 'custom_label_0' }),
      rule({ id: 'b', name: 'Later', targetSlot: 'custom_label_0' }),
    ];
    const result = computeShadowing(rules, { a: '1,2', b: '2,3' });
    expect([...result.b.shadowed]).toEqual(['2']);
    expect(result.b.shadowedBy.get('2')).toBe('Bleeder');
    expect(result.a.shadowed.size).toBe(0);
  });

  it('ignores values in rules of other slots', () => {
    const rules = [
      rule({ id: 'a', name: 'One', targetSlot: 'custom_label_0' }),
      rule({ id: 'b', name: 'Two', targetSlot: 'custom_label_1' }),
    ];
    const result = computeShadowing(rules, { a: '1', b: '1' });
    expect(result.b.shadowed.size).toBe(0);
  });

  it('skips inactive rules entirely (no claims, no shadowing)', () => {
    const rules = [
      rule({ id: 'a', name: 'Off', targetSlot: 'custom_label_0', isActive: false }),
      rule({ id: 'b', name: 'On', targetSlot: 'custom_label_0' }),
    ];
    const result = computeShadowing(rules, { a: '1', b: '1' });
    expect(result.b.shadowed.size).toBe(0);
  });

  it('an all-mode rule shadows every value of lower-priority rules', () => {
    const rules = [
      rule({ id: 'a', name: 'Catch All', targetSlot: 'custom_label_0', matchMode: 'all' }),
      rule({ id: 'b', name: 'Later', targetSlot: 'custom_label_0' }),
    ];
    const result = computeShadowing(rules, { b: '9,8' });
    expect([...result.b.shadowed].sort()).toEqual(['8', '9']);
    expect(result.b.shadowedBy.get('9')).toBe('Catch All');
  });

  it('values claimed before an all-mode rule stay attributed to their claimer', () => {
    const rules = [
      rule({ id: 'a', name: 'First', targetSlot: 'custom_label_0' }),
      rule({ id: 'm', name: 'Catch All', targetSlot: 'custom_label_0', matchMode: 'all' }),
      rule({ id: 'b', name: 'Last', targetSlot: 'custom_label_0' }),
    ];
    const result = computeShadowing(rules, { a: '7', b: '7,8' });
    expect(result.b.shadowedBy.get('7')).toBe('First');
    expect(result.b.shadowedBy.get('8')).toBe('Catch All');
  });

  it('returns empty entries for rules without values', () => {
    const rules = [rule({ id: 'a', name: 'A', targetSlot: 'custom_label_0' })];
    const result = computeShadowing(rules, {});
    expect(result.a).toEqual({ shadowed: new Set(), shadowedBy: new Map() });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm run test -- --run src/features/customLabels/shadowing.test.ts`
Expected: FAIL — cannot resolve `./shadowing`.

- [ ] **Step 3: Implement `shadowing.ts`**

Create `frontend/src/features/customLabels/shadowing.ts`:

```ts
import { parseIdList } from './ids';
import type { ScopedSlotRule } from './scopeMerge';

export type RuleShadowInfo = {
  /** Values present in this rule but ignored — a higher-priority rule claims them. */
  shadowed: Set<string>;
  /** Shadowed value -> name of the first higher-priority rule that claims it. */
  shadowedBy: Map<string, string>;
};

/**
 * Syntactic first-match-wins analysis: per slot, walk ACTIVE rules in
 * evaluation order; a value already claimed by an earlier rule is shadowed.
 * An `all`-mode rule shadows every value of all lower-priority rules in the
 * slot. Inactive rules neither claim nor are shadowed.
 */
export function computeShadowing(
  rules: ReadonlyArray<ScopedSlotRule>,
  values: Readonly<Record<string, string>>,
): Record<string, RuleShadowInfo> {
  const result: Record<string, RuleShadowInfo> = {};
  for (const rule of rules) {
    result[rule.id] = { shadowed: new Set(), shadowedBy: new Map() };
  }
  const bySlot = new Map<string, ScopedSlotRule[]>();
  for (const rule of rules) {
    if (!rule.isActive) continue;
    const list = bySlot.get(rule.targetSlot) ?? [];
    list.push(rule);
    bySlot.set(rule.targetSlot, list);
  }
  for (const slotRules of bySlot.values()) {
    const claimedBy = new Map<string, string>();
    let firstAllName: string | undefined;
    for (const rule of slotRules) {
      const info = result[rule.id];
      const allOwner = firstAllName;
      if (rule.matchMode === 'all') {
        firstAllName ??= rule.name;
      }
      for (const value of parseIdList(values[rule.id] ?? '')) {
        const owner = claimedBy.get(value) ?? allOwner;
        if (owner !== undefined && owner !== rule.name) {
          info.shadowed.add(value);
          info.shadowedBy.set(value, owner);
        } else if (rule.matchMode !== 'all') {
          claimedBy.set(value, rule.name);
        }
      }
    }
  }
  return result;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `frontend/`): `npm run test -- --run src/features/customLabels/shadowing.test.ts`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/shadowing.ts frontend/src/features/customLabels/shadowing.test.ts
git commit -m "feat(frontend): labelizer shadowing analysis (syntactic first-match-wins)"
```

---

### Task 3: Frontend — `labeledAny` in the preview hook

**Files:**
- Modify: `frontend/src/features/customLabels/usePreview.ts:5-11`
- Modify: `frontend/src/features/customLabels/usePreview.test.tsx`

**Interfaces:**
- Consumes: backend JSON key `labeledAny` (Task 1).
- Produces: `PreviewResult` gains `labeledAny?: number`. Task 6's `CoverageDashboard` reads `preview.result?.labeledAny`.

- [ ] **Step 1: Write the failing test**

In `frontend/src/features/customLabels/usePreview.test.tsx`:

1. Change the `RESULT` constant (line 21-25) to add `labeledAny`:

```ts
const RESULT: PreviewResult = {
  total: 10,
  labeledAny: 7,
  rules: { r1: { matched: 5, labeled: 4, sample: ['a1'] } },
  slots: { custom_label_0: { labeled: 4, coverage: 40, rules: ['r1'] } },
};
```

2. In the `Probe` component (line 27-42), add one span after the `total` span:

```tsx
      <span data-testid="labeledany">{state.result?.labeledAny ?? ''}</span>
```

3. In the first test (`fires one debounced preview request and renders the result`), add after the existing `total` waitFor:

```ts
    expect(
      document.querySelector('[data-testid="labeledany"]')?.textContent,
    ).toBe('7');
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm run test -- --run src/features/customLabels/usePreview.test.tsx`
Expected: FAIL — type error (`Object literal may only specify known properties` / `labeledAny` missing from `PreviewResult`) or assertion `'7'` vs `''`.

- [ ] **Step 3: Implement the type**

In `frontend/src/features/customLabels/usePreview.ts`, change `PreviewResult` (lines 7-11):

```ts
export type PreviewResult = {
  total: number;
  labeledAny?: number;
  rules: Record<string, PreviewRuleStats>;
  slots: Record<string, { labeled: number; coverage: number; rules: string[] }>;
};
```

No runtime change — the hook returns the parsed response as-is.

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `frontend/`): `npm run test -- --run src/features/customLabels/usePreview.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/usePreview.ts frontend/src/features/customLabels/usePreview.test.tsx
git commit -m "feat(frontend): labelizer preview result carries labeledAny"
```

---

### Task 4: i18n keys (en + de)

**Files:**
- Modify: `frontend/public/locales/en/customLabels.json`
- Modify: `frontend/public/locales/de/customLabels.json`

**Interfaces:**
- Consumes: nothing.
- Produces: keys used by Tasks 5 and 6 — `priority`, `slotSelectorLabel`, `coverage.labeledOf`, `coverage.totalProducts`, `coverage.labeled`, `coverage.unlabeled`, `coverage.activeRules`, `shadowedCount`, `shadowListTitle`, `shadowedBy`, `noRulesForSlot`. Existing keys reused: `idCount`, `matchedCount`, `neverApplied`, `neverAppliedHint`, `inheritedFrom`, `activeRulesCount_one/_other`, `slotExplanations.*`, `bulk.*`, `idsPlaceholder`, `clearValues`, `previewUnavailable`, `noStagedProducts`.

- [ ] **Step 1: Add the keys to the en locale**

In `frontend/public/locales/en/customLabels.json`, add these top-level keys (e.g. directly after `"emptySlots": "No rules yet for:",` at line 15):

```json
  "slotSelectorLabel": "Custom label slot",
  "priority": "#{{index}} Priority",
  "coverage": {
    "labeledOf": "{{count}} / {{total}} staged products labeled",
    "totalProducts": "Total products",
    "labeled": "Labeled",
    "unlabeled": "Unlabeled",
    "activeRules": "Active rules"
  },
  "shadowedCount": "{{count}} overridden",
  "shadowListTitle": "Overridden IDs (already matched by a higher-priority rule)",
  "shadowedBy": "Already matched by higher priority rule: {{name}}",
  "noRulesForSlot": "No active rules for this slot yet — add them under Slot rules.",
```

- [ ] **Step 2: Add the keys to the de locale**

In `frontend/public/locales/de/customLabels.json`, add the same top-level keys (the de file mirrors the en key set; place them in the same relative position):

```json
  "slotSelectorLabel": "Custom-Label-Slot",
  "priority": "Nr. {{index}} Priorität",
  "coverage": {
    "labeledOf": "{{count}} / {{total}} gestagte Produkte gelabelt",
    "totalProducts": "Produkte insgesamt",
    "labeled": "Gelabelt",
    "unlabeled": "Nicht gelabelt",
    "activeRules": "Aktive Regeln"
  },
  "shadowedCount": "{{count}} überschrieben",
  "shadowListTitle": "Überschriebene IDs (bereits durch eine Regel mit höherer Priorität abgedeckt)",
  "shadowedBy": "Bereits abgedeckt durch Regel mit höherer Priorität: {{name}}",
  "noRulesForSlot": "Noch keine aktiven Regeln für diesen Slot — unter Slot-Regeln hinzufügen.",
```

- [ ] **Step 3: Verify both files are valid JSON with matching keys**

Run (from repo root): `node -e "const en=require('./frontend/public/locales/en/customLabels.json');const de=require('./frontend/public/locales/de/customLabels.json');const flat=(o,p='')=>Object.entries(o).flatMap(([k,v])=>typeof v==='object'?flat(v,p+k+'.'):[p+k]);const ek=new Set(flat(en)),dk=new Set(flat(de));const miss=[...ek].filter(k=>!dk.has(k));if(miss.length)throw new Error('de missing: '+miss);console.log('keys ok:',ek.size)"`
Expected: `keys ok: <N>` with no error.

- [ ] **Step 4: Commit**

```bash
git add frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json
git commit -m "feat(frontend): labelizer i18n keys for slot selection, coverage, shadowing"
```

---

### Task 5: `RuleCard` + `ShadowList` components

**Files:**
- Create: `frontend/src/features/customLabels/ShadowList.tsx`
- Create: `frontend/src/features/customLabels/RuleCard.tsx`
- Test: `frontend/src/features/customLabels/RuleCard.test.tsx`

**Interfaces:**
- Consumes: `parseIdList`, `renderPreview` from `./ids`; `renderPreview(template: string, sample?): string`; `RuleShadowInfo`/`computeShadowing` from `./shadowing` (Task 2); `PreviewRuleStats` from `./usePreview`; `ScopedSlotRule`, `SlotRule`, `Tier` from `./scopeMerge`; i18n keys from Task 4.
- Produces: `RuleCard` renders a Mantine `Accordion.Item` (must be wrapped in `Accordion` by the parent); `RuleCardProps` as below; `ShadowList` with prop `shadowedBy: ReadonlyMap<string, string>`. Task 6 wires these into `CustomLabelsUI`.

**IMPORTANT for tests:** with Mantine 9.5.2 + React 19.2.7, a collapsed `Accordion.Panel`'s content is hidden via React `<Activity mode="hidden">` — it is **not in the DOM**. Therefore (a) assertions about panel content (textarea, ID counter, all-mode summary, shadow list) are only valid AFTER clicking the control to expand, and (b) use waiting queries (`findByText` / `findByRole` / `findByLabelText`) after expansion clicks — Mantine's collapse needs a requestAnimationFrame tick before the content appears. Assertions on `Accordion.Control` header content (rule name, badges) are always valid.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/customLabels/RuleCard.test.tsx`:

```tsx
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Accordion } from '@mantine/core';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { RuleCard } from './RuleCard';
import type { ScopedSlotRule } from './scopeMerge';

const RULE: ScopedSlotRule = {
  id: 'r1', name: 'Mid Funnel', isActive: true, targetSlot: 'custom_label_1',
  matchField: 'id', matchMode: 'values', valueTemplate: '{brand} - Mid',
  fallbackTemplate: '', origin: 'client',
};

function renderCard(over: Partial<Parameters<typeof RuleCard>[0]> = {}) {
  const onSetIds = vi.fn();
  render(
    <Accordion multiple>
      <RuleCard
        rule={RULE}
        priority={1}
        value=""
        dirty={false}
        inheritedFrom={null}
        editable={false}
        showLive={false}
        shadowedBy={new Map()}
        onSetIds={onSetIds}
        onPatchRule={() => {}}
        {...over}
      />
    </Accordion>,
  );
  return { onSetIds };
}

beforeAll(async () => {
  await i18n.loadNamespaces(['customLabels', 'common']);
});

describe('RuleCard', () => {
  it('collapsed header shows name and priority badge, hides the editor', () => {
    renderCard();
    expect(screen.getByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText('#1 Priority')).toBeInTheDocument();
    expect(
      screen.queryByRole('textbox', { name: /product ids — mid funnel/i }),
    ).not.toBeInTheDocument();
  });

  it('expanding reveals the textarea with the ID counter below it (no overlap)', async () => {
    const { onSetIds } = renderCard();
    await userEvent.click(screen.getByText('Mid Funnel'));
    const textarea = await screen.findByRole('textbox', { name: /product ids — mid funnel/i });
    expect(textarea).toBeInTheDocument();
    // the counter is NOT inside the textarea (the old bottomSection overlap bug)
    expect(textarea.tagName).toBe('TEXTAREA');
    expect(await screen.findByText('0 unique IDs')).toBeInTheDocument();
    expect(screen.queryByText('3 unique IDs')).not.toBeInTheDocument();
    await userEvent.type(textarea, 'a,b, c');
    expect(onSetIds).toHaveBeenLastCalledWith('a,b, c');
    expect(screen.getByText('3 unique IDs')).toBeInTheDocument();
  });

  it('shows a shadowed count badge and lists shadowed values with attribution tooltip', async () => {
    renderCard({
      value: '2,3,5',
      shadowedBy: new Map([['2', 'Bleeder'], ['3', 'Bleeder']]),
    });
    expect(screen.getByText('2 overridden')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(await screen.findByText(/overridden IDs/i)).toBeInTheDocument();
    const value2 = await screen.findByText('2', { exact: true });
    expect(value2).toHaveStyle({ textDecoration: 'line-through' });
    expect(screen.getByText('3', { exact: true })).toHaveStyle({
      textDecoration: 'line-through',
    });
    // unshadowed values are NOT struck through (they live in the textarea only)
    expect(screen.queryByText('5', { exact: true })).not.toBeInTheDocument();
    await userEvent.hover(value2);
    expect(await waitFor(() =>
      screen.getByText(/already matched by higher priority rule: bleeder/i),
      { timeout: 3000 })).toBeInTheDocument();
  });

  it('all-mode rules show the controlled-by summary instead of a textarea', async () => {
    renderCard({
      rule: { ...RULE, matchMode: 'all', valueTemplate: '{brand} - All' },
      editable: true,
    });
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(await screen.findByText(/every product gets: brand - all/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /switch to value list/i }),
    ).toBeInTheDocument();
  });

  it('inherited rules show the tier badge', () => {
    renderCard({ inheritedFrom: 'client' });
    expect(screen.getByText('Inherited from Client')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm run test -- --run src/features/customLabels/RuleCard.test.tsx`
Expected: FAIL — cannot resolve `./RuleCard`.

- [ ] **Step 3: Implement `ShadowList`**

Create `frontend/src/features/customLabels/ShadowList.tsx`:

```tsx
import { Group, Stack, Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function ShadowList({ shadowedBy }: { shadowedBy: ReadonlyMap<string, string> }) {
  const { t } = useTranslation('customLabels');
  if (shadowedBy.size === 0) return null;
  return (
    <Stack gap={4} data-testid="shadow-list">
      <Text size="xs" c="dimmed">{t('shadowListTitle')}</Text>
      <Group gap="xs" wrap="wrap">
        {[...shadowedBy].map(([value, ruleName]) => (
          <Tooltip
            key={value}
            label={t('shadowedBy', { name: ruleName })}
            withArrow
            position="top"
          >
            <Text size="xs" c="dimmed" style={{ textDecoration: 'line-through' }}>
              {value}
            </Text>
          </Tooltip>
        ))}
      </Group>
    </Stack>
  );
}
```

- [ ] **Step 4: Implement `RuleCard`**

Create `frontend/src/features/customLabels/RuleCard.tsx`:

```tsx
import {
  Accordion, Badge, Button, CloseButton, Group, Indicator, Paper, Stack, Text, Textarea, Tooltip,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { parseIdList, renderPreview } from './ids';
import { ShadowList } from './ShadowList';
import type { ScopedSlotRule, SlotRule, Tier } from './scopeMerge';
import type { PreviewRuleStats } from './usePreview';

export type RuleCardProps = {
  rule: ScopedSlotRule;
  /** 1-based evaluation position within the selected slot. */
  priority: number;
  value: string;
  dirty: boolean;
  inheritedFrom: Tier | null;
  editable: boolean;
  matchedStats?: PreviewRuleStats;
  showLive: boolean;
  shadowedBy: ReadonlyMap<string, string>;
  onSetIds: (value: string) => void;
  onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
};

export function RuleCard({
  rule, priority, value, dirty, inheritedFrom, editable, matchedStats,
  showLive, shadowedBy, onSetIds, onPatchRule,
}: RuleCardProps) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  const allMode = rule.matchMode === 'all';
  const count = parseIdList(value).size;
  const neverApplied = showLive
    && matchedStats !== undefined
    && matchedStats.matched > 0
    && matchedStats.labeled === 0;

  return (
    <Accordion.Item value={rule.id} data-testid={`rule-card-${rule.id}`}>
      <Accordion.Control>
        <Group gap="xs" wrap="nowrap">
          <Indicator color="orange" size={8} offset={-4} position="top-end" disabled={!dirty}>
            <Text size="sm" fw={600} component="span">{rule.name}</Text>
          </Indicator>
          <Badge size="xs" variant="light" color="blue" data-testid="priority-badge">
            {t('priority', { index: priority })}
          </Badge>
          {inheritedFrom !== null && (
            <Badge size="xs" variant="light" color="teal">
              {t('inheritedFrom', { tier: tCommon(`scope.${inheritedFrom}`) })}
            </Badge>
          )}
          {showLive && matchedStats ? (
            neverApplied ? (
              <Tooltip
                label={`${t('neverApplied')} — ${t('neverAppliedHint')}`}
                withArrow
                position="top"
              >
                <Badge size="xs" variant="light" color="gray">
                  {t('matchedCount', { count: matchedStats.matched })}
                </Badge>
              </Tooltip>
            ) : (
              <Badge size="xs" variant="light">
                {t('matchedCount', { count: matchedStats.matched })}
              </Badge>
            )
          ) : null}
          {shadowedBy.size > 0 && (
            <Badge size="xs" variant="light" color="orange" data-testid="shadowed-badge">
              {t('shadowedCount', { count: shadowedBy.size })}
            </Badge>
          )}
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="xs">
          <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
          {allMode ? (
            <Paper withBorder p="xs" data-testid={`all-mode-${rule.id}`}>
              <Stack gap={4}>
                <Text size="sm" c="dimmed">{t('bulk.controlledByRule')}</Text>
                <Text size="sm" fw={600}>
                  {t('bulk.allProductsGet', { preview: renderPreview(rule.valueTemplate) })}
                </Text>
                {editable && (
                  <Button
                    variant="subtle"
                    size="xs"
                    onClick={() => onPatchRule(rule.id, { matchMode: 'values' })}
                  >
                    {t('bulk.switchToValueList')}
                  </Button>
                )}
              </Stack>
            </Paper>
          ) : (
            <Stack gap={4}>
              <Textarea
                label={rule.matchField === 'id'
                  ? t('bulk.productIds')
                  : t('bulk.valuesFor', { field: rule.matchField })}
                aria-label={rule.matchField === 'id'
                  ? `${t('bulk.productIds')} — ${rule.name}`
                  : `${t('bulk.valuesFor', { field: rule.matchField })} — ${rule.name}`}
                minRows={5}
                autosize
                styles={{
                  input: {
                    maxHeight: 400,
                    overflowY: 'auto',
                    fontFamily: 'var(--mantine-font-family-monospace)',
                  },
                }}
                value={value}
                onChange={(e) => onSetIds(e.currentTarget.value)}
                placeholder={t('idsPlaceholder')}
              />
              <Group gap="xs" justify="space-between" wrap="nowrap">
                <Text size="xs" c="dimmed" data-testid={`id-count-${rule.id}`}>
                  {t('idCount', { count })}
                </Text>
                <Group gap={6} wrap="nowrap">
                  <Text size="xs" c="dimmed">{rule.matchField}</Text>
                  {value !== '' && (
                    <CloseButton
                      size="xs"
                      aria-label={`${t('clearValues')} — ${rule.name}`}
                      onClick={() => onSetIds('')}
                    />
                  )}
                </Group>
              </Group>
            </Stack>
          )}
          <ShadowList shadowedBy={shadowedBy} />
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run (from `frontend/`): `npm run test -- --run src/features/customLabels/RuleCard.test.tsx`
Expected: 5 tests PASS. If the tooltip-hover assertion is flaky in this environment, first check the Mantine Tooltip opens on hover (waitFor timeout is already 3000 ms); do not delete the assertion.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/customLabels/RuleCard.tsx frontend/src/features/customLabels/ShadowList.tsx frontend/src/features/customLabels/RuleCard.test.tsx
git commit -m "feat(frontend): labelizer collapsible rule card with shadow list"
```

---

### Task 6: Slot selector, coverage dashboard, and idsPanel rewire

**Files:**
- Create: `frontend/src/features/customLabels/SlotSelector.tsx`
- Create: `frontend/src/features/customLabels/CoverageDashboard.tsx`
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Delete: `frontend/src/features/customLabels/SlotGroup.tsx`
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: `RuleCard`/`RuleCardProps` (Task 5), `computeShadowing` (Task 2), `preview.result?.labeledAny` (Task 3), i18n keys (Task 4), existing `TARGET_SLOTS` constant in `CustomLabelsUI`.
- Produces: the new ids-panel DOM — test ids `slot-selector`, `coverage-dashboard`, `coverage-stat-total`, `coverage-stat-labeled`, `coverage-stat-unlabeled`, `coverage-stat-active-rules`, `rules-${slot}` (Accordion), `rule-card-${ruleId}`, `id-count-${ruleId}`.

- [ ] **Step 1: Create `SlotSelector`**

Create `frontend/src/features/customLabels/SlotSelector.tsx`:

```tsx
import { Group, Indicator, SegmentedControl, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function SlotSelector({
  slots, value, onChange, dirty, activeCount,
}: {
  slots: ReadonlyArray<string>;
  value: string;
  onChange: (slot: string) => void;
  dirty: boolean;
  activeCount: number;
}) {
  const { t } = useTranslation('customLabels');
  return (
    <Stack gap={4}>
      <Indicator color="orange" size={8} offset={-2} position="top-end" disabled={!dirty}>
        <SegmentedControl
          aria-label={t('slotSelectorLabel')}
          data={slots.map((slot) => ({ value: slot, label: slot.toUpperCase() }))}
          value={value}
          onChange={onChange}
          data-testid="slot-selector"
        />
      </Indicator>
      <Group gap="xs" wrap="wrap">
        <Text size="xs" c="dimmed">
          {t(`slotExplanations.${value}` as 'slotExplanations.custom_label_0')}
        </Text>
        <Text size="xs" c="dimmed">
          {t('activeRulesCount', { count: activeCount })}
        </Text>
      </Group>
    </Stack>
  );
}
```

- [ ] **Step 2: Create `CoverageDashboard`**

Create `frontend/src/features/customLabels/CoverageDashboard.tsx`:

```tsx
import { Card, Group, Loader, Progress, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export type CoverageDashboardProps = {
  total: number | undefined;
  labeledAny: number | undefined;
  activeRules: number;
  pending: boolean;
  errors: string[] | null;
  unavailable: boolean;
};

export function CoverageDashboard({
  total, labeledAny, activeRules, pending, errors, unavailable,
}: CoverageDashboardProps) {
  const { t } = useTranslation('customLabels');
  if (unavailable) {
    return <Text size="xs" c="dimmed">{t('previewUnavailable')}</Text>;
  }
  if (errors) {
    return (
      <Stack gap={2}>
        {errors.map((error) => (
          <Text key={error} size="xs" c="dimmed">{error}</Text>
        ))}
      </Stack>
    );
  }
  if (total === 0) {
    return <Text size="xs" c="dimmed">{t('noStagedProducts')}</Text>;
  }
  if (total === undefined || labeledAny === undefined) {
    return pending ? <Loader size="xs" /> : null;
  }
  const pct = Math.min(100, Math.max(0, Math.round((labeledAny / total) * 100)));
  return (
    <Card withBorder p="sm" data-testid="coverage-dashboard">
      <Stack gap="xs">
        <Group gap="xs" wrap="nowrap">
          {pending && <Loader size="xs" />}
          <Text size="sm" fw={600}>
            {t('coverage.labeledOf', { count: labeledAny, total })}
          </Text>
        </Group>
        <Progress size="sm" data-testid="coverage-progress">
          <Progress.Section value={pct} color="green" />
        </Progress>
        <Group gap="lg" wrap="wrap">
          {([
            ['totalProducts', total, 'coverage-stat-total'],
            ['labeled', labeledAny, 'coverage-stat-labeled'],
            ['unlabeled', total - labeledAny, 'coverage-stat-unlabeled'],
            ['activeRules', activeRules, 'coverage-stat-active-rules'],
          ] as const).map(([label, count, testId]) => (
            <Stack key={testId} gap={0}>
              <Text size="xs" c="dimmed">{t(`coverage.${label}`)}</Text>
              <Text size="sm" fw={600} data-testid={testId}>{count}</Text>
            </Stack>
          ))}
        </Group>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 3: Rewire `CustomLabelsUI`**

Edit `frontend/src/features/customLabels/CustomLabelsUI.tsx`:

1. Change the React import (line 1) and Mantine import (lines 2-5) to:

```tsx
import { useEffect, useMemo, useState } from 'react';
import {
  Accordion, ActionIcon, Button, Card, Drawer, Group,
  SegmentedControl, Select, Stack, Switch, Tabs, Text, TextInput,
} from '@mantine/core';
```

(`Badge` is dropped — it was only used by the removed empty-slots row. `SegmentedControl` and `Select`/`Switch`/`TextInput` remain for the rules panel.)

2. Replace the `SlotGroup` import (line 23) with:

```tsx
import { SlotSelector } from './SlotSelector';
import { CoverageDashboard } from './CoverageDashboard';
import { RuleCard } from './RuleCard';
import { computeShadowing } from './shadowing';
```

3. After the `const [deleteOpen, ...]` line (~line 164), add slot state:

```tsx
  const [selectedSlot, setSelectedSlot] = useState<string>(TARGET_SLOTS[0]);
  const [slotTouched, setSlotTouched] = useState(false);
```

4. Right after `const activeRules = effectiveRules.filter((r) => r.isActive);` (line 153), add:

```tsx
  const populatedSlots = TARGET_SLOTS.filter(
    (slot) => activeRules.some((r) => r.targetSlot === slot),
  );
  useEffect(() => {
    if (!slotTouched && populatedSlots.length > 0 && !populatedSlots.includes(selectedSlot)) {
      setSelectedSlot(populatedSlots[0]);
    }
  }, [slotTouched, populatedSlots, selectedSlot]);
  const shadow = useMemo(
    () => computeShadowing(effectiveRules, effectiveIds),
    [effectiveRules, effectiveIds],
  );
```

Note: `effectiveIds` is declared at line 147, `activeRules` at 153 — this block sits after both, before the early returns (line 225+). Hooks must stay above the `if (configPending || dataPending) return <LoadingState />;` early return — this placement satisfies that.

5. Delete the now-duplicated `populatedSlots`/`emptySlots` definitions from the lower section (lines ~251-256):

```tsx
  const populatedSlots = TARGET_SLOTS.filter(
    (slot) => activeRules.some((r) => r.targetSlot === slot),
  );
  const emptySlots = TARGET_SLOTS.filter(
    (slot) => !activeRules.some((r) => r.targetSlot === slot),
  );
```

(keep the `idsUnavailable`, `initialTab`, and `ruleEditable` lines that surround them).

6. Replace the entire `idsPanel` definition (lines ~258-314, from `const idsPanel = idsUnavailable ? (` through its closing `);`) with:

```tsx
  const slotRules = activeRules.filter((r) => r.targetSlot === selectedSlot);
  const slotDirty = dirtyIds
    && slotRules.some(
      (r) => (effectiveIds[r.id] ?? '') !== (serverIds[r.id]?.value ?? ''),
    );

  const idsPanel = idsUnavailable ? (
    <Text c="dimmed">{t('idsUnavailable')}</Text>
  ) : (
    <Stack gap="sm">
      <Group justify="flex-end">
        <Button variant="default" onClick={() => setSlotIds(null)} disabled={!dirtyIds}>
          {tCommon('actions.cancel')}
        </Button>
        <Button onClick={() => void saveIds()} loading={saveData.isPending} disabled={!dirtyIds}>
          {tCommon('actions.save')}
        </Button>
      </Group>
      <SlotSelector
        slots={TARGET_SLOTS}
        value={selectedSlot}
        onChange={(slot) => {
          setSlotTouched(true);
          setSelectedSlot(slot);
        }}
        dirty={slotDirty}
        activeCount={slotRules.length}
      />
      {atFeed && (
        <CoverageDashboard
          total={preview.result?.total}
          labeledAny={preview.result?.labeledAny}
          activeRules={activeRules.length}
          pending={preview.isPending}
          errors={preview.errors}
          unavailable={preview.unavailable}
        />
      )}
      <Accordion multiple data-testid={`rules-${selectedSlot}`}>
        {slotRules.map((rule, index) => (
          <RuleCard
            key={rule.id}
            rule={rule}
            priority={index + 1}
            value={effectiveIds[rule.id] ?? ''}
            dirty={dirtyIds
              && (effectiveIds[rule.id] ?? '') !== (serverIds[rule.id]?.value ?? '')}
            inheritedFor={(id) =>
              serverIds[id]?.inherited === true
                && (effectiveIds[id] ?? '') === serverIds[id].value
                ? serverIds[id].sourceTier
                : null
            }
            ...
          />
        ))}
      </Accordion>
    </Stack>
  );
```

The `...` above is not literal — write the `RuleCard` props fully as follows (inline the `inheritedFor` logic since `RuleCard` takes a plain `inheritedFrom`):

```tsx
        {slotRules.map((rule, index) => (
          <RuleCard
            key={rule.id}
            rule={rule}
            priority={index + 1}
            value={effectiveIds[rule.id] ?? ''}
            dirty={dirtyIds
              && (effectiveIds[rule.id] ?? '') !== (serverIds[rule.id]?.value ?? '')}
            inheritedFrom={
              serverIds[rule.id]?.inherited === true
                && (effectiveIds[rule.id] ?? '') === serverIds[rule.id].value
                ? serverIds[rule.id].sourceTier
                : null
            }
            editable={ruleEditable(rule)}
            matchedStats={preview.result?.rules[rule.id]}
            showLive={atFeed}
            shadowedBy={shadow[rule.id]?.shadowedBy ?? new Map()}
            onSetIds={(next) => onSetSlotIds(next)}
            onPatchRule={patchRule}
          />
        ))}
      </Accordion>
      {slotRules.length === 0 && (
        <Text size="sm" c="dimmed" data-testid="empty-slot-notice">
          {t('noRulesForSlot')}
        </Text>
      )}
    </Stack>
  );
```

where `onSetSlotIds` is a small helper added next to `patchRule`:

```tsx
  function onSetSlotIds(ruleId: string, next: string) {
    setSlotIds({ ...effectiveIds, [ruleId]: next });
  }
```

and the `RuleCard` call uses `onSetIds={(next) => onSetSlotIds(rule.id, next)}`.

7. Delete `frontend/src/features/customLabels/SlotGroup.tsx` (`rm frontend/src/features/customLabels/SlotGroup.tsx`).

- [ ] **Step 4: Typecheck**

Run (from `frontend/`): `npm run typecheck`
Expected: no errors. (The integration tests will still be red — that is Step 5.)

- [ ] **Step 5: Update the integration tests**

Edit `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`. The rules-panel, tier-navigation, tier-override, and rule-actions `describe` blocks stay as they are. Change only the tests below.

**a. Replace** `it('renders one column per active merged rule (global + client)')` with:

```tsx
  it('selects the first populated slot by default; switching slots swaps the ruleset', async () => {
    renderUI({ feedSourceId: 1 });
    const selector = await screen.findByTestId('slot-selector');
    // default = first slot with active rules (custom_label_1: Mid Funnel)
    expect(within(selector).getByText('CUSTOM_LABEL_1')).toBeInTheDocument();
    expect(screen.getByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.queryByText('Client Only')).not.toBeInTheDocument();
    // switch to custom_label_2 (Client Only)
    await userEvent.click(within(selector).getByText('CUSTOM_LABEL_2'));
    expect(screen.getByText('Client Only')).toBeInTheDocument();
    expect(screen.queryByText('Mid Funnel')).not.toBeInTheDocument();
  });
```

**b. Replace** `it('shows the parsed/deduped ID count from prefilled data')` with:

```tsx
  it('shows the parsed/deduped ID count inside the expanded card', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand the accordion
    expect(await screen.findByText('3 unique IDs')).toBeInTheDocument();
  });
```

**b2. Replace** `it('values textarea accessible name matches the localized label plus rule name')` with:

```tsx
  it('values textarea accessible name matches the localized label plus rule name', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(
      await screen.findByRole('textbox', { name: 'Product IDs — Mid Funnel' }),
    ).toBeInTheDocument();
  });
```

**c. Replace** `it('marks client-tier bulk values as inherited at feed tier with a Client badge')` with:

```tsx
  it('marks client-tier bulk values as inherited at feed tier with a Client badge', async () => {
    const handler = (url: string) => {
      if (url.includes('/plugins/custom_labels/data?feed_source_id=')) return jsonResponse({});
      return jsonResponseFor(url);
    };
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', handler);
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    // only the selected slot's rules are rendered
    expect(screen.getAllByText('Inherited from Client').length).toBe(1);
    const selector = screen.getByTestId('slot-selector');
    await userEvent.click(within(selector).getByText('CUSTOM_LABEL_2'));
    expect(screen.getAllByText('Inherited from Client').length).toBe(1);
  });
```

**d. Replace** `it('groups the bulk tab by target slot in registry order')` with:

```tsx
  it('slots without active rules show the empty notice when selected', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    const selector = screen.getByTestId('slot-selector');
    await userEvent.click(within(selector).getByText('CUSTOM_LABEL_0'));
    expect(screen.getByTestId('empty-slot-notice')).toBeInTheDocument();
    expect(screen.queryByText('Mid Funnel')).not.toBeInTheDocument();
  });
```

**e. Replace** `it('shows the unsaved indicator on a slot badge only while its values differ from the server')` with:

```tsx
  it('shows unsaved dots on the rule card and slot selector while values differ', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    expect(document.querySelectorAll('.mantine-Indicator-indicator').length).toBe(0);
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    await userEvent.type(
      await screen.findByLabelText('Product IDs — Mid Funnel'),
      ',d',
    );
    // one dot on the rule card, one on the slot selector
    expect(document.querySelectorAll('.mantine-Indicator-indicator').length).toBe(2);
  });
```

**f. Replace** `it('info boxes show slot explanation and active rule count')` with:

```tsx
  it('shows the selected slot explanation and active rule count', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText(/mid-funnel segmentation/i)).toBeInTheDocument();
    expect(screen.getAllByText('1 active rule').length).toBe(1);
  });
```

**g.** In `it('active rule count pluralizes for more than one rule')` no change is needed (the selector header still renders `2 active rules`).

**h.** In `it('onlyTab="ids" renders the bulk grid without any rules tab or rules UI')`, replace the `slot-grid` assertion:

```tsx
    expect(await screen.findByTestId('slot-selector')).toBeInTheDocument();
```

**i.** In the `CustomLabelsUI bulk tab mode-awareness` describe:

- In `it('all-mode rules show a controlled-by summary instead of the value textarea')`, insert an expansion click before the summary assertion:

```tsx
    expect(await screen.findByText('All Products')).toBeInTheDocument();
    await userEvent.click(screen.getByText('All Products')); // expand the accordion
    expect(await screen.findByText(/every product gets: brand - all/i)).toBeInTheDocument();
```

- In `it('values-mode rules relabel the textarea to the match field')`, replace the single assertion with:

```tsx
    await userEvent.click(await screen.findByText('By Brand')); // expand
    expect(await screen.findByLabelText(/values for brand/i)).toBeInTheDocument();
```

- In `it("clear button empties that rule's value list and zeroes the counter")`, insert `await userEvent.click(screen.getByText('Mid Funnel')); // expand` after the `findByText('Mid Funnel')` line, and change the Clear-button click + assertions to:

```tsx
    const textarea = await screen.findByLabelText('Product IDs — Mid Funnel');
    await userEvent.click(screen.getByRole('button', { name: 'Clear value list — Mid Funnel' }));
    expect(textarea).toHaveValue('');
    expect(screen.getByText('0 unique IDs')).toBeInTheDocument();
```

- In `it('at client tier an all-mode rule offers the switch-to-value-list override')`, insert `await userEvent.click(await screen.findByText('All Products')); // expand` before `const override = ...` (the rest of the test already uses `findByLabelText`).

**i2.** In `it('at client tier both config and data are fetched with client_id')`, the closing assertion `expect(screen.getByText('3 unique IDs')).toBeInTheDocument();` reads panel content, which is no longer in the DOM while collapsed. Change it to:

```tsx
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(await screen.findByText('3 unique IDs')).toBeInTheDocument();
```

**j.** In the `CustomLabelsUI live preview stats` describe, replace the `PREVIEW` constant and both failing tests:

```tsx
  const PREVIEW = {
    total: 3,
    labeledAny: 2,
    rules: {
      r1: { matched: 2, labeled: 2, sample: ['a1', 'a2'] },
      r3: { matched: 1, labeled: 0, sample: ['z1'] },
    },
    slots: {
      custom_label_1: { labeled: 2, coverage: 66.7, rules: ['r1'] },
      custom_label_2: { labeled: 0, coverage: 0, rules: ['r3'] },
    },
  };

  it('renders the overall coverage dashboard and per-rule match badges', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) return jsonResponse(PREVIEW);
      return jsonResponseFor(url);
    });
    expect(await waitFor(() =>
      expect(screen.getByText(/2 \/ 3 staged products labeled/i)).toBeInTheDocument(),
      { timeout: 2500 })).toBeTruthy();
    expect(document.querySelectorAll('.mantine-Progress-root').length).toBe(1);
    expect(screen.getByTestId('coverage-stat-total')).toHaveTextContent('3');
    expect(screen.getByTestId('coverage-stat-labeled')).toHaveTextContent('2');
    expect(screen.getByTestId('coverage-stat-unlabeled')).toHaveTextContent('1');
    expect(screen.getByTestId('coverage-stat-active-rules')).toHaveTextContent('2');
    // default slot custom_label_1: r1 badge visible in the collapsed header
    expect(screen.getByText('2 matched')).toBeInTheDocument();
    // sample product deep-links are gone
    expect(screen.queryByRole('link', { name: 'a1' })).not.toBeInTheDocument();
    // switch to custom_label_2: r3 is matched-but-never-labeled
    const selector = screen.getByTestId('slot-selector');
    await userEvent.click(within(selector).getByText('CUSTOM_LABEL_2'));
    expect(screen.getByText('1 matched')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'z1' })).not.toBeInTheDocument();
  });
```

Keep `it('total=0 shows the never-run hint instead of zero stats')` unchanged. In `it('client page sends no preview request and shows no stats header')`, replace the last assertion:

```tsx
    expect(screen.queryByTestId('coverage-dashboard')).not.toBeInTheDocument();
```

**k.** Add a shadowing integration test to the `CustomLabelsUI live preview stats` describe (or a new `describe('CustomLabelsUI shadowing')`):

```tsx
describe('CustomLabelsUI shadowing', () => {
  it('flags values claimed by a higher-priority rule of the same slot', async () => {
    const config = {
      slotRules: [
        { id: 'r1', name: 'Bleeder', isActive: true, targetSlot: 'custom_label_0',
          matchField: 'id', valueTemplate: 'x', fallbackTemplate: '' },
        { id: 'r2', name: 'Later', isActive: true, targetSlot: 'custom_label_0',
          matchField: 'id', valueTemplate: 'y', fallbackTemplate: '' },
      ],
    };
    const handler = (url: string) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(config);
      if (url.startsWith('/plugins/custom_labels/data')) {
        return jsonResponse({ slotIds: { r1: '1,2', r2: '2,3' } });
      }
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
    };
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', handler);
    expect(await screen.findByText('Later')).toBeInTheDocument();
    expect(screen.getByText('1 overridden')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Later')); // expand
    expect(await screen.findByText(/overridden IDs/i)).toBeInTheDocument();
    const value2 = await screen.findByText('2', { exact: true });
    expect(value2).toHaveStyle({ textDecoration: 'line-through' });
  });
});
```

- [ ] **Step 6: Run the full frontend test suite**

Run (from `frontend/`): `npm run test -- --run`
Expected: all PASS, including the untouched rules-panel tests and the new shadowing/RuleCard tests.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/customLabels/
git commit -m "feat(frontend): labelizer slot-selected view with coverage dashboard and rule cards"
```

---

### Task 7: Frontend docs + full gates

**Files:**
- Modify: `frontend/docs/architecture.md:161`
- Modify: `frontend/docs/plugin-uis.md` (section "Live matching and slot-grouped bulk values", lines ~214-232)

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: docs matching the shipped behavior.

- [ ] **Step 1: Update `frontend/docs/architecture.md`**

Replace the `custom_labels` bullet at line 161 with:

```
  - `custom_labels` → `CustomLabelsUI` (`src/features/customLabels/`, UI name "Labelizer") — merged Global/Client/Feed tier view (union-by-id mirroring the runtime `config_merge`); the bulk tab is slot-selected via a top SegmentedControl (custom_label_0..4) with a coverage dashboard (any-slot labeled/total, progress bar, quick stats) and collapsible priority-ordered rule cards (matched + overridden badges, shadowed-value list with attribution tooltips), debounced draft preview via `POST /plugins/custom_labels/preview`; rule duplicate/delete, override-at-client-level, clickable tier navigation, help drawer, i18n (`customLabels` namespace)
```

- [ ] **Step 2: Update `frontend/docs/plugin-uis.md`**

Replace the two bullets "**Preview:**" and "**Grouped by slot:**" (lines 216-232) with:

```
- **Preview:** the feed-page bulk tab debounce-posts the current DRAFT
  (rules + values, unsaved edits included) to the plugin-local
  `POST /plugins/custom_labels/preview` and renders a header coverage
  dashboard over ALL slots: "X / N staged products labeled" (products
  labeled in at least one slot), a green/gray progress bar, and quick
  stats (total, labeled, unlabeled, active rules). Each rule card header
  carries an "N matched" badge (tooltip explains matched-but-never-applied
  rules). Distinct "no staged products yet" and preview-error states;
  client/global pages render no stats and send no request.
- **Slot-selected view:** a top SegmentedControl picks one of
  `custom_label_0..4` (default: first slot with active rules); only that
  slot's active rules render, as collapsible `Accordion` rule cards in
  evaluation order with `#N Priority` badges. Collapsed headers show
  rule name, priority, inherited-from tier, matched count, and an
  "N overridden" badge when a higher-priority rule of the same slot
  claims values from this rule's list (client-side syntactic analysis;
  an `all`-mode rule shadows everything below it). Expanded panels hold
  the 400px-capped monospace value-list textarea with the unique-ID
  counter BELOW the input (no bottomSection overlap), per-rule clear
  button, and a shadow list rendering each overridden value struck
  through with a tooltip naming the claiming rule. Empty slots show a
  notice when selected.
```

- [ ] **Step 3: Run all gates**

Run (from `frontend/`): `npm run typecheck && npm run test -- --run && npm run build`
Run (from `backend/`): `uv run pytest -n auto && uv run ruff check . && uv run mypy .`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/docs/architecture.md frontend/docs/plugin-uis.md
git commit -m "docs(frontend): labelizer slot-selected view and coverage dashboard"
```

---

## Self-Review Notes (resolved during planning)

- Spec coverage: §1 backend `labeledAny` → Task 1; §2 shadowing module → Task 2; §3 UI (SegmentedControl §1, dashboard §2, cards §3, shadowing UI §4, overlap fix in Task 5's counter placement) → Tasks 5-6; §5 tech standards (Mantine 9 components only, local state, immediate preview) honored throughout; testing §5 → Tasks 1-6 steps; docs §6 → Tasks 1 and 7.
- The rules config surface, scope merge, and save semantics are untouched, per spec "Out of scope".
- Type consistency: `RuleShadowInfo.shadowedBy` (Map<string, string>) is produced by Task 2's `computeShadowing`, consumed by Task 5's `RuleCardProps.shadowedBy` and `ShadowList`; `PreviewResult.labeledAny` is produced by Task 3 and consumed by Task 6's `CoverageDashboardProps.labeledAny`; backend JSON key `labeledAny` (Task 1) matches the frontend type field exactly.
