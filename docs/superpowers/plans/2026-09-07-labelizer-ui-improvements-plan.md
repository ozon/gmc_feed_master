# Labelizer UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Labelizer "Bulk IDs" tab — compact stats header per slot (labeled/total + coverage bar), per-rule "N matched" badges on the input blocks, side-by-side 400px-capped monospace ID textareas with inline counters and clear buttons, 2-column slot grid with an empty-slots summary row, and an unsaved-changes indicator on slot badges.

**Architecture:** All changes are in `frontend/src/features/customLabels/` (`SlotGroup.tsx` renders each slot card; `CustomLabelsUI.tsx` renders the tab and passes preview data). The `useLabelizerPreview` hook and the backend `POST /plugins/custom_labels/preview` endpoint are untouched — only the rendering changes. i18n keys are typed against the `en` locale (`src/i18n/i18next.d.ts` imports `public/locales/en/customLabels.json`), so new keys must exist in `en` before code references them, and removed keys must leave the code first.

**Tech Stack:** React 19, Mantine 9.5.2 (Indicator, Progress, SimpleGrid, CloseButton, Textarea `bottomSection`/`styles` all available), i18next (en/de), Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-07-labelizer-ui-improvements-design.md`

## Global Constraints

- Frontend only; no backend, API, or dependency changes.
- All commands run from `frontend/`.
- Targeted tests: `npx vitest run src/features/customLabels` (full suite: `npx vitest run`). Typecheck: `npm run typecheck` (tsc -b).
- i18n: every key added/removed in `public/locales/en/customLabels.json` must be mirrored in `public/locales/de/customLabels.json` in the same step. Keys still referenced by code must not be removed.
- No comments in code (repo convention).
- Keep the Textarea `label`/`aria-label` logic byte-identical (tests assert the accessible names `Product IDs — <rule>` / `Values for <field> — <rule>`).
- Commit messages follow repo style: `feat(frontend): ...`, `test(frontend): ...`, `docs(frontend): ...`.

---

### Task 1: i18n keys (en + de) — additive only

**Files:**
- Modify: `frontend/public/locales/en/customLabels.json`
- Modify: `frontend/public/locales/de/customLabels.json`

**Interfaces:**
- Produces keys that Tasks 2–4 render: `slotLabeledOf`, `clearValues`, `emptySlots`; reworked `matchedCount`. Does NOT remove any key yet (removals happen in the tasks that stop using them).

- [ ] **Step 1: Edit the en locale**

In `frontend/public/locales/en/customLabels.json`:

Replace (line 19):

```json
  "matchedCount": "{{count}} match",
```

with:

```json
  "matchedCount": "{{count}} matched",
```

Add these three keys directly after `"noStagedProducts"` (line 15):

```json
  "slotLabeledOf": "{{count}} of {{total}} staged products labeled",
  "clearValues": "Clear value list",
  "emptySlots": "No rules yet for:",
```

- [ ] **Step 2: Edit the de locale — same positions, mirrored**

In `frontend/public/locales/de/customLabels.json`:

Replace (line 19):

```json
  "matchedCount": "{{count}} Treffer",
```

with:

```json
  "matchedCount": "{{count}} Treffer",
```

(The German wording stays the same — "Treffer" already reads correctly as "N Treffer". Keep the line unchanged.)

Add these three keys directly after `"noStagedProducts"` (line 15):

```json
  "slotLabeledOf": "{{count}} von {{total}} gestagten Produkten gelabelt",
  "clearValues": "Werteliste leeren",
  "emptySlots": "Noch keine Regeln für:",
```

- [ ] **Step 3: Verify JSON validity and typecheck**

Run: `node -e "JSON.parse(require('fs').readFileSync('public/locales/en/customLabels.json')); JSON.parse(require('fs').readFileSync('public/locales/de/customLabels.json')); console.log('ok')"`
Expected: `ok`

Run: `npm run typecheck`
Expected: exit 0 (additive keys break nothing).

- [ ] **Step 4: Commit**

```bash
git add public/locales/en/customLabels.json public/locales/de/customLabels.json
git commit -m "feat(frontend): labelizer i18n keys for stats header and input controls"
```

---

### Task 2: Slot stats header + per-rule match badges; drop sample links

**Files:**
- Modify: `frontend/src/features/customLabels/SlotGroup.tsx` (full rework below)
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx:155-157` (drop `productsHref`) and `:338` (drop the prop)
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json` (remove now-unused keys)
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx:561-618` (rewrite the live-preview describe)

**Interfaces:**
- Consumes: `SlotGroupProps` (same shape minus `productsHref`), preview fields `stats`/`ruleStats`/`total`/`previewPending`/`previewErrors`/`previewUnavailable` from `usePreview`.
- Produces: `SlotGroup` without `productsHref`; new header strings asserted by tests. Tasks 3–4 build on the file state written here.

- [ ] **Step 1: Rewrite the live-preview tests (fail first)**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, replace the whole `describe('CustomLabelsUI live preview stats', ...)` block (lines 561–618) with:

```tsx
describe('CustomLabelsUI live preview stats', () => {
  const PREVIEW = {
    total: 3,
    rules: {
      r1: { matched: 2, labeled: 2, sample: ['a1', 'a2'] },
      r3: { matched: 1, labeled: 0, sample: ['z1'] },
    },
    slots: {
      custom_label_1: { labeled: 2, coverage: 66.7, rules: ['r1'] },
      custom_label_2: { labeled: 0, coverage: 0, rules: ['r3'] },
    },
  };

  it('renders the labeled/total header, coverage bar, and per-rule match badges', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) return jsonResponse(PREVIEW);
      return jsonResponseFor(url);
    });
    expect(await waitFor(() =>
      expect(screen.getByText(/2 of 3 staged products labeled/i)).toBeInTheDocument(),
      { timeout: 2500 })).toBeTruthy();
    expect(screen.getByText(/0 of 3 staged products labeled/i)).toBeInTheDocument();
    expect(document.querySelectorAll('.mantine-Progress-root').length).toBe(2);
    expect(screen.getByText('2 matched')).toBeInTheDocument();
    expect(screen.getByText('1 matched')).toBeInTheDocument();
    // sample product deep-links are gone
    expect(screen.queryByRole('link', { name: 'a1' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'z1' })).not.toBeInTheDocument();
  });

  it('total=0 shows the never-run hint instead of zero stats', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return jsonResponse({ total: 0, rules: {}, slots: {} });
      }
      return jsonResponseFor(url);
    });
    expect(await waitFor(() =>
      expect(screen.getAllByText(/no staged products yet/i).length).toBeGreaterThan(0),
      { timeout: 2500 })).toBeTruthy();
  });

  it('client page sends no preview request and shows no stats header', async () => {
    const calls: string[] = [];
    renderUI(
      { clientId: 1 },
      '/clients/1/plugins/custom_labels',
      (url) => {
        calls.push(url);
        return jsonResponseFor(url);
      },
    );
    await screen.findByText('Client Only');
    expect(calls.some((u) => u.includes('/preview'))).toBe(false);
    expect(screen.queryByText(/staged products labeled/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the rewritten tests to verify they fail**

Run: `npx vitest run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: FAIL — "2 of 3 staged products labeled" not found (current UI renders "2 products get this label" / coverage text), "2 matched" absent.

- [ ] **Step 3: Rewrite SlotGroup.tsx**

Replace the ENTIRE contents of `frontend/src/features/customLabels/SlotGroup.tsx` with:

```tsx
import {
  Badge, Button, Card, Collapse, Group, Loader, Paper, Progress, Stack, Text, Textarea, Tooltip,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { parseIdList, renderPreview } from './ids';
import type { ScopedSlotRule, SlotRule, Tier } from './scopeMerge';
import type { PreviewRuleStats } from './usePreview';

export type SlotGroupProps = {
  slot: string;
  rules: ScopedSlotRule[];
  values: Record<string, string>;
  inheritedFor: (id: string) => Tier | null;
  isRuleEditable: (rule: ScopedSlotRule) => boolean;
  editableTier: Tier | null;
  onSetSlotIds: (next: Record<string, string>) => void;
  onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
  showLive: boolean;
  stats?: { labeled: number; coverage: number };
  ruleStats?: Record<string, PreviewRuleStats>;
  total?: number;
  previewPending: boolean;
  previewErrors: string[] | null;
  previewUnavailable: boolean;
};

export function SlotGroup({
  slot, rules, values, inheritedFor, isRuleEditable, editableTier, onSetSlotIds, onPatchRule,
  showLive, stats, ruleStats, total, previewPending, previewErrors, previewUnavailable,
}: SlotGroupProps) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  return (
    <Card withBorder p="sm" data-testid={`slot-group-${slot}`}>
      <Stack gap="xs">
        <Group gap="xs" justify="space-between" wrap="wrap">
          <Group gap="xs" wrap="nowrap">
            <Badge variant="light" color="teal">{slot}</Badge>
            <Text size="xs" c="dimmed">{t(`slotExplanations.${slot}` as 'slotExplanations.custom_label_0')}</Text>
          </Group>
          <Text size="xs" c="dimmed">{t('activeRulesCount', { count: rules.length })}</Text>
        </Group>
        {!showLive ? null : previewUnavailable ? (
          <Text size="xs" c="dimmed">{t('previewUnavailable')}</Text>
        ) : previewErrors ? (
          <Stack gap={2}>
            {previewErrors.map((error) => (
              <Text key={error} size="xs" c="dimmed">{error}</Text>
            ))}
          </Stack>
        ) : total === undefined ? (
          previewPending ? <Loader size="xs" /> : null
        ) : total === 0 ? (
          <Text size="xs" c="dimmed">{t('noStagedProducts')}</Text>
        ) : (
          <Stack gap={4}>
            <Group gap="xs" wrap="nowrap">
              {previewPending && <Loader size="xs" />}
              <Text size="xs" c="dimmed">
                {t('slotLabeledOf', { count: stats?.labeled ?? 0, total })}
              </Text>
            </Group>
            <Progress value={Math.min(100, Math.max(0, stats?.coverage ?? 0))} size="sm" />
          </Stack>
        )}
        <Stack gap="md">
          {rules.map((rule) => {
            const allMode = rule.matchMode === 'all';
            const raw = values[rule.id] ?? '';
            const count = parseIdList(raw).size;
            const inheritedFrom = inheritedFor(rule.id);
            const rs = ruleStats?.[rule.id];
            const neverApplied = showLive && rs !== undefined && rs.matched > 0 && rs.labeled === 0;
            return (
              <Stack key={rule.id} gap={4}>
                <Group gap="xs" justify="space-between" wrap="nowrap">
                  <Group gap="xs" wrap="nowrap">
                    <Text size="sm" fw={600}>{rule.name}</Text>
                    {inheritedFrom !== null && (
                      <Badge size="xs" variant="light" color="teal">
                        {t('inheritedFrom', { tier: tCommon(`scope.${inheritedFrom}`) })}
                      </Badge>
                    )}
                    {showLive && rs ? (
                      neverApplied ? (
                        <Tooltip
                          label={`${t('neverApplied')} — ${t('neverAppliedHint')}`}
                          withArrow
                          position="top"
                        >
                          <Badge size="xs" variant="light" color="gray">
                            {t('matchedCount', { count: rs.matched })}
                          </Badge>
                        </Tooltip>
                      ) : (
                        <Badge size="xs" variant="light">
                          {t('matchedCount', { count: rs.matched })}
                        </Badge>
                      )
                    ) : null}
                  </Group>
                  <Text size="xs" c="dimmed">{rule.matchField}</Text>
                </Group>
                <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
                <Collapse expanded={!allMode} keepMounted={false}>
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
                      value={raw}
                      onChange={(e) => onSetSlotIds({ ...values, [rule.id]: e.currentTarget.value })}
                      placeholder={t('idsPlaceholder')}
                    />
                    <Text size="xs" c="dimmed">{t('idCount', { count })}</Text>
                  </Stack>
                </Collapse>
                <Collapse expanded={allMode} keepMounted={false}>
                  <Paper withBorder p="xs" data-testid={`all-mode-${rule.id}`}>
                    <Stack gap={4}>
                      <Text size="sm" c="dimmed">{t('bulk.controlledByRule')}</Text>
                      <Text size="sm" fw={600}>
                        {t('bulk.allProductsGet', { preview: renderPreview(rule.valueTemplate) })}
                      </Text>
                      {isRuleEditable(rule) && (
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
                </Collapse>
              </Stack>
            );
          })}
        </Stack>
      </Stack>
    </Card>
  );
}
```

(Changes vs. the old file: `Anchor`/`Link` imports and sample links removed; the stats text block is replaced by the labeled/total line + `Progress`; per-rule `matchedCount` text + separate `neverApplied` badge become one match Badge (tooltip carries the never-applied explanation); the rest — slot header, textareas, all-mode paper — is unchanged at this point.)

- [ ] **Step 4: Drop productsHref from CustomLabelsUI.tsx**

In `frontend/src/features/customLabels/CustomLabelsUI.tsx`:

Delete lines 155–157:

```tsx
  const productsHref = atFeed && routeContext.clientId && routeContext.feedSourceId
    ? `/clients/${routeContext.clientId}/feeds/${routeContext.feedSourceId}/products`
    : null;
```

Delete line 338:

```tsx
                      productsHref={productsHref}
```

(`Link` stays imported — it is still used by the "manage at client" anchor in the rules tab.)

- [ ] **Step 5: Remove now-unused i18n keys (en + de)**

In BOTH `frontend/public/locales/en/customLabels.json` and `frontend/public/locales/de/customLabels.json`, delete these four keys:

```json
  "openFromFeed": "...",
  "slotLabeled": "...",
  "coveragePct": "...",
  "freshnessHint": "...",
```

(Keep `neverApplied`, `neverAppliedHint`, `matchedCount`, `previewUnavailable`, `noStagedProducts`, `idCount` — all still rendered.)

- [ ] **Step 6: Run tests and typecheck**

Run: `npx vitest run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: PASS (all tests in the file, including the untouched bulk-tab and aria-label tests).

Run: `npm run typecheck`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add src/features/customLabels/SlotGroup.tsx src/features/customLabels/CustomLabelsUI.tsx \
  src/features/customLabels/__tests__/CustomLabelsUI.test.tsx \
  public/locales/en/customLabels.json public/locales/de/customLabels.json
git commit -m "feat(frontend): labelizer slot stats header with coverage bar and per-rule match badges"
```

---

### Task 3: Side-by-side ID inputs, 400px cap, monospace, inline counter, clear button

**Files:**
- Modify: `frontend/src/features/customLabels/SlotGroup.tsx`
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: Task 2's `SlotGroup.tsx` state and the `clearValues` i18n key from Task 1.
- Produces: rules laid out in `SimpleGrid cols={{ base: 1, sm: 2 }}`; Textarea capped at 400px with monospace font; ID count inside the textarea border (`bottomSection`); per-rule `CloseButton` with accessible name `Clear value list — <rule name>`.

- [ ] **Step 1: Write the failing clear-button test**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, inside `describe('CustomLabelsUI bulk tab mode-awareness', ...)`, add after the "values-mode rules relabel the textarea to the match field" test:

```tsx
  it('clear button empties that rule's value list and zeroes the counter', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('button', { name: 'Clear value list — Mid Funnel' }));
    expect(screen.getByLabelText('Product IDs — Mid Funnel')).toHaveValue('');
    expect(screen.getByText('0 unique IDs')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: FAIL — no button with name "Clear value list — Mid Funnel" exists.

- [ ] **Step 3: Implement in SlotGroup.tsx**

3a. Update the import line to add `CloseButton` and `SimpleGrid`:

```tsx
import {
  Badge, Button, Card, CloseButton, Collapse, Group, Loader, Paper, Progress,
  SimpleGrid, Stack, Text, Textarea, Tooltip,
} from '@mantine/core';
```

3b. Replace the outer `<Stack gap="md">` that wraps the rules map (the line `<Stack gap="md">` directly after the stats block, plus its closing `</Stack>` before `</Stack></Card>`) with:

```tsx
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md" verticalSpacing="sm">
```

…matching closing `</SimpleGrid>`.

3c. Inside the rules map, replace the rule header's right side

```tsx
                  <Text size="xs" c="dimmed">{rule.matchField}</Text>
```

with:

```tsx
                  <Group gap={6} wrap="nowrap">
                    <Text size="xs" c="dimmed">{rule.matchField}</Text>
                    {!allMode && raw !== '' && (
                      <CloseButton
                        size="xs"
                        aria-label={`${t('clearValues')} — ${rule.name}`}
                        onClick={() => onSetSlotIds({ ...values, [rule.id]: '' })}
                      />
                    )}
                  </Group>
```

3d. Replace the values-mode `<Textarea ... />` and the ID-count line beneath it

```tsx
                    <Textarea
                      label={...}
                      aria-label={...}
                      minRows={5}
                      autosize
                      value={raw}
                      onChange={(e) => onSetSlotIds({ ...values, [rule.id]: e.currentTarget.value })}
                      placeholder={t('idsPlaceholder')}
                    />
                    <Text size="xs" c="dimmed">{t('idCount', { count })}</Text>
```

with (label/aria-label logic byte-identical, new props: `styles`, `bottomSection`; separate count line removed):

```tsx
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
                      bottomSection={<Text size="xs" c="dimmed">{t('idCount', { count })}</Text>}
                      value={raw}
                      onChange={(e) => onSetSlotIds({ ...values, [rule.id]: e.currentTarget.value })}
                      placeholder={t('idsPlaceholder')}
                    />
```

The wrapping `<Stack gap={4}>` inside the `Collapse` around the Textarea can be dropped (only the Textarea remains) — delete it and its closing tag so the Textarea sits directly inside the Collapse.

- [ ] **Step 4: Run tests and typecheck**

Run: `npx vitest run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: PASS — new clear-button test passes; "3 unique IDs" tests still pass (the counter now renders inside the textarea border); the aria-label test (accessible name `Product IDs — <rule>`) still passes.

Run: `npm run typecheck`
Expected: exit 0.

- [ ] **Step 5: Manual visual check (optional, if dev server available)**

`npm run dev` → open the Labelizer bulk tab at a feed → paste >20 lines of IDs into a textarea: the input must cap at 400px and scroll internally, monospace; two rule inputs sit side-by-side on ≥sm viewports; the count sits inside the input border; an X appears next to the match field when the list is non-empty.

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels/SlotGroup.tsx src/features/customLabels/__tests__/CustomLabelsUI.test.tsx
git commit -m "feat(frontend): labelizer side-by-side value inputs with 400px cap, inline counters, clear buttons"
```

---

### Task 4: Compact slot grid, empty-slot summary, unsaved-changes indicator

**Files:**
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx:244-342` (slot-grid region) and imports
- Modify: `frontend/src/features/customLabels/SlotGroup.tsx` (add `dirty` prop + `Indicator`)
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json` (remove `noRulesYet`)
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx:121-130` (update), plus one new test

**Interfaces:**
- Consumes: `effectiveIds`, `serverIds` (`Record<string, { value: string; inherited: boolean; sourceTier: Tier }>`), `dirtyIds`, `activeRules` in `CustomLabelsUI`; `emptySlots` i18n key from Task 1.
- Produces: `SlotGroup` prop `dirty: boolean` (required); DOM: `[data-testid="slot-grid"]` is a `SimpleGrid` of populated slot cards, `[data-testid="slot-grid-empty"]` summary row with one Badge per empty slot; `.mantine-Indicator-indicator` dot on the slot badge while the slot has unsaved value edits.

- [ ] **Step 1: Update the layout test and add the dirty test (fail first)**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, replace the test at lines 121–130:

```tsx
  it('groups the bulk tab by target slot in registry order', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    const grid = document.querySelector('[data-testid="slot-grid"]') as HTMLElement;
    const groups = grid.querySelectorAll('[data-testid^="slot-group-"]');
    expect(Array.from(groups).map((g) => g.getAttribute('data-testid'))).toEqual([
      'slot-group-custom_label_1', 'slot-group-custom_label_2',
    ]);
    const empty = screen.getByTestId('slot-grid-empty');
    expect(within(empty).getByText('No rules yet for:')).toBeInTheDocument();
    expect(within(empty).getByText('custom_label_0')).toBeInTheDocument();
  });
```

(`within` is already imported in this test file.)

Add to the same `describe('CustomLabelsUI operational page', ...)` block:

```tsx
  it('shows the unsaved indicator on a slot badge only while its values differ from the server', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    expect(document.querySelectorAll('.mantine-Indicator-indicator').length).toBe(0);
    await userEvent.type(screen.getByLabelText('Product IDs — Mid Funnel'), ',d');
    expect(document.querySelectorAll('.mantine-Indicator-indicator').length).toBe(1);
  });
```

- [ ] **Step 2: Run to verify both fail**

Run: `npx vitest run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: FAIL — `slot-grid-empty` testid not found; `.mantine-Indicator-indicator` never appears.

- [ ] **Step 3: Implement in SlotGroup.tsx**

3a. Add `Indicator` to the `@mantine/core` import list.

3b. Add the required prop to `SlotGroupProps` (after `editableTier`):

```tsx
  dirty: boolean;
```

and destructure it (after `editableTier`):

```tsx
  slot, rules, values, inheritedFor, isRuleEditable, editableTier, dirty, onSetSlotIds, onPatchRule,
```

3c. Wrap the slot Badge in the header:

```tsx
            <Indicator color="orange" size={8} offset={-4} position="top-end" disabled={!dirty}>
              <Badge variant="light" color="teal">{slot}</Badge>
            </Indicator>
```

- [ ] **Step 4: Implement in CustomLabelsUI.tsx**

4a. Add `SimpleGrid` to the `@mantine/core` import.

4b. After `const ruleEditable = ...` (line ~245), add:

```tsx
  const populatedSlots = TARGET_SLOTS.filter(
    (slot) => activeRules.some((r) => r.targetSlot === slot),
  );
  const emptySlots = TARGET_SLOTS.filter(
    (slot) => !activeRules.some((r) => r.targetSlot === slot),
  );
```

4c. Replace the whole `<Stack gap="md" data-testid="slot-grid">…</Stack>` block (lines ~304–342, the `TARGET_SLOTS.map` with the `slot-empty` branch) with:

```tsx
              <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" data-testid="slot-grid">
                {populatedSlots.map((slot) => {
                  const slotRules = activeRules.filter((r) => r.targetSlot === slot);
                  const slotDirty = dirtyIds
                    && slotRules.some(
                      (r) => (effectiveIds[r.id] ?? '') !== (serverIds[r.id]?.value ?? ''),
                    );
                  return (
                    <SlotGroup
                      key={slot}
                      slot={slot}
                      rules={slotRules}
                      values={effectiveIds}
                      dirty={slotDirty}
                      inheritedFor={(id) =>
                        serverIds[id]?.inherited === true
                          && (effectiveIds[id] ?? '') === serverIds[id].value
                          ? serverIds[id].sourceTier
                          : null
                      }
                      isRuleEditable={ruleEditable}
                      editableTier={editableTier}
                      onSetSlotIds={setSlotIds}
                      onPatchRule={patchRule}
                      showLive={atFeed}
                      stats={preview.result?.slots[slot]}
                      ruleStats={preview.result?.rules}
                      total={preview.result?.total}
                      previewPending={preview.isPending}
                      previewErrors={preview.errors}
                      previewUnavailable={preview.unavailable}
                    />
                  );
                })}
              </SimpleGrid>
              {emptySlots.length > 0 && (
                <Group gap="xs" wrap="wrap" data-testid="slot-grid-empty">
                  <Text size="sm" c="dimmed">{t('emptySlots')}</Text>
                  {emptySlots.map((slot) => (
                    <Badge key={slot} size="xs" variant="light">{slot}</Badge>
                  ))}
                </Group>
              )}
```

- [ ] **Step 5: Remove the now-unused `noRulesYet` key from BOTH locales**

Delete `"noRulesYet": "no rules yet"` from `en` and `"noRulesYet": "noch keine Regeln"` from `de` (nothing renders it anymore).

- [ ] **Step 6: Run tests and typecheck**

Run: `npx vitest run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: PASS — updated grid test, new dirty test, and all others.

Run: `npm run typecheck`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add src/features/customLabels/CustomLabelsUI.tsx src/features/customLabels/SlotGroup.tsx \
  src/features/customLabels/__tests__/CustomLabelsUI.test.tsx \
  public/locales/en/customLabels.json public/locales/de/customLabels.json
git commit -m "feat(frontend): labelizer compact slot grid, empty-slot summary, unsaved indicator"
```

---

### Task 5: Docs + full verification

**Files:**
- Modify: `frontend/docs/plugin-uis.md:221-231`
- Modify: `frontend/docs/architecture.md:161`

**Interfaces:**
- Consumes: final UI state from Tasks 1–4.
- Produces: docs matching the shipped behavior (AGENTS.md requirement — same change set).

- [ ] **Step 1: Update plugin-uis.md**

Replace the two bullets at `frontend/docs/plugin-uis.md:221-231` ("**Preview:** …" and "**Grouped by slot:** …") with:

```markdown
- **Preview:** the feed-page bulk tab debounce-posts the current DRAFT
  (rules + values, unsaved edits included) to the plugin-local
  `POST /plugins/custom_labels/preview` and renders a compact stats header per
  slot: "X of N staged products labeled" with a coverage progress bar, plus an
  "N matched" badge on each rule input block (the badge tooltip explains
  shadowed "never applied" rules). Distinct "no staged products yet" and
  preview-error states; client/global pages render no stats and send no
  request. Sample product deep-links were removed.
- **Grouped by slot:** the bulk tab renders slot cards in a responsive
  2-column grid (one per `custom_label_0..4` with active rules, registry
  order). Each card header carries the slot badge (orange dot while the slot
  has unsaved value edits), slot explanation, active-rule count, and live
  stats; the slot's rule editors sit side-by-side in a 2-column inner grid —
  400px-capped monospace value-list textareas with inline ID counters and
  per-rule clear buttons. Slots without active rules collapse into a single
  summary row of badges.
```

- [ ] **Step 2: Update architecture.md**

At `frontend/docs/architecture.md:161`, replace the `custom_labels` bullet's middle clause `slot-grouped bulk tab with live match stats (debounced draft preview via \`POST /plugins/custom_labels/preview\`)` with `slot-grouped bulk tab with a compact live-stats header (labeled/total + coverage bar) and per-rule match badges (debounced draft preview via \`POST /plugins/custom_labels/preview\`)`.

- [ ] **Step 3: Full verification**

Run: `npx vitest run`
Expected: entire frontend suite PASS, zero failures.

Run: `npm run typecheck`
Expected: exit 0.

Run: `git diff --check`
Expected: no whitespace errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/docs/plugin-uis.md frontend/docs/architecture.md
git commit -m "docs(frontend): labelizer bulk-tab stats header and compact layout"
```
