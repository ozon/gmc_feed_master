# Labelizer Rule Card Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Labelizer rule card: per-rule net-hit badges in the Coverage Dashboard, a textarea toolbar (clear / format & dedupe / preview toggle), a collapsed-by-default side-by-side product preview with strict line↔row alignment, and removal of the footer "Overridden IDs" section.

**Architecture:** All changes are frontend-only inside `frontend/src/features/customLabels/`. The existing preview data flow is kept (backend `evaluate_rules` already returns per-rule net `labeled` counts; `computeShadowing` already tracks the claiming rule internally). Components keep their boundaries: `CoverageDashboard` (badges), `RuleCard` (pass-through), `RuleValuesEditor` (toolbar + split layout), `ProductPreviewColumn` (windowed rows). Pure logic lives in `ids.ts` (line parsing, formatting) and `shadowing.ts` (owner id/name/priority). Spec: `docs/superpowers/specs/2026-09-08-labelizer-rule-card-refactor-design.md`.

**Tech Stack:** React 19, Mantine v9 (`@mantine/core` 9.5.2, `@mantine/hooks`), `@tabler/icons-react`, i18next (en + de), vitest + React Testing Library.

## Global Constraints

- **No new npm dependencies.** `@tanstack/react-virtual` stays rejected (ADR-0008 §2); the existing custom fixed-row windowing (`windowRange`) IS the virtualization.
- **No backend changes** — no plugin code, no routes, no migrations touched in this plan.
- **Row alignment:** preview row *i* = textarea **line** *i* (split on `\n` only; blank lines render blank rows). Row height is `ROW_HEIGHT = 44`; textarea input `line-height` must equal it with zero vertical padding.
- **Textarea width:** bounded `flex: 0 0 380px` in both collapsed and expanded states; preview column `flex: 1 1 auto`; top/bottom edges flush.
- **Preview collapsed by default**; one shared toggle lifted to `CustomLabelsUI`.
- **i18n:** every user-facing string via the `customLabels` namespace; en (`frontend/public/locales/en/customLabels.json`) and de (`frontend/public/locales/de/customLabels.json`) must stay in parity. Never use i18next's `count` variable for non-pluralized numbers (use `hits`, `more`, `priority`).
- **Tests before implementation** for each behavioral change; run gates from `frontend/`.
- **Commit style:** conventional commits (`feat(frontend): …`, `docs: …`), one commit per task.

---

### Task 1: `parsePreviewLines` + `formatIdList` in `ids.ts`

**Files:**
- Modify: `frontend/src/features/customLabels/ids.ts`
- Test: `frontend/src/features/customLabels/__tests__/ids.test.ts`

**Interfaces:**
- Produces: `parsePreviewLines(raw: string | undefined | null): string[][]` — row *i* = line *i*; each line is its comma-split, trimmed, empty-token-dropped IDs; blank line → `[]`. Consumed by Task 5 (`RuleValuesEditor`, `ProductPreviewColumn`).
- Produces: `formatIdList(raw: string): string` — normalized newline-joined list; consumed by Task 6 (toolbar Format button).
- `parseIdEntries` is NOT touched in this task (deleted in Task 5).

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/features/customLabels/__tests__/ids.test.ts` (and update the import on line 2):

```ts
import {
  compileTemplate, formatIdList, parseIdEntries, parseIdList, parsePreviewLines, renderPreview,
} from '../ids';
```

Add these describes after the existing `parseIdEntries` describe:

```ts
describe('parsePreviewLines', () => {
  it('makes one row per line; blank lines stay blank rows', () => {
    expect(parsePreviewLines('a\n\nb')).toEqual([['a'], [], ['b']]);
  });

  it('comma-splits each line into its IDs, trimmed, empty tokens dropped', () => {
    expect(parsePreviewLines('a, b ,\nc')).toEqual([['a', 'b'], ['c']]);
  });

  it('returns [] for empty or missing input', () => {
    expect(parsePreviewLines('')).toEqual([]);
    expect(parsePreviewLines(undefined)).toEqual([]);
    expect(parsePreviewLines(null)).toEqual([]);
  });
});

describe('formatIdList', () => {
  it('strips empties, splits commas to one per line, dedupes preserving order', () => {
    expect(formatIdList('b, a\n\n a \nc,\n')).toBe('b\na\nc');
  });

  it('returns an empty string for empty input', () => {
    expect(formatIdList('')).toBe('');
    expect(formatIdList('  \n, \n')).toBe('');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- run src/features/customLabels/__tests__/ids.test.ts` (workdir `frontend/`)
Expected: FAIL — "The requested module '../ids' does not provide an export named 'parsePreviewLines'"

- [ ] **Step 3: Implement in `ids.ts`**

Insert after `parseIdList` in `frontend/src/features/customLabels/ids.ts`:

```ts
/** One preview row per textarea LINE: row i = line i (blank lines render
 * blank rows, so line↔row alignment never breaks). A line's comma groups
 * are its IDs; the line's first ID drives its preview-row match display. */
export function parsePreviewLines(raw: string | undefined | null): string[][] {
  if (!raw) return [];
  return raw.split('\n').map((line) =>
    line.split(',').map((part) => part.trim()).filter((part) => part !== ''),
  );
}

/** Normalize a value list: trim, strip empty lines, split comma groups to
 * one ID per line, dedupe preserving first-occurrence order. */
export function formatIdList(raw: string): string {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const ids of parsePreviewLines(raw)) {
    for (const id of ids) {
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(id);
    }
  }
  return out.join('\n');
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- run src/features/customLabels/__tests__/ids.test.ts` (workdir `frontend/`)
Expected: PASS (all ids tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/ids.ts frontend/src/features/customLabels/__tests__/ids.test.ts
git commit -m "feat(frontend): labelizer per-line preview parsing and format helpers"
```

---

### Task 2: Bump `ROW_HEIGHT` to 44px

**Files:**
- Modify: `frontend/src/features/customLabels/productPreview.ts:3`
- Modify: `frontend/src/features/customLabels/RuleValuesEditor.tsx:1-8,64-70`
- Test: `frontend/src/features/customLabels/ProductPreviewColumn.test.tsx:92-98`

**Interfaces:**
- Produces: `ROW_HEIGHT = 44` (was 34) — imported by `RuleValuesEditor` (textarea line-height) from Task 2 on; `ProductPreviewColumn` and `productPreview.test.ts` already import it.
- Consumes: nothing new.

- [ ] **Step 1: Change the constant and the textarea line-height**

In `frontend/src/features/customLabels/productPreview.ts` line 3:

```ts
export const ROW_HEIGHT = 44;
```

In `frontend/src/features/customLabels/RuleValuesEditor.tsx`, change the import (line 8) from:

```ts
import { useSyncedScroll } from './productPreview';
```

to:

```ts
import { ROW_HEIGHT, useSyncedScroll } from './productPreview';
```

and inside the `textarea` const, the `styles` prop becomes:

```ts
      styles={{
        input: {
          lineHeight: `${ROW_HEIGHT}px`,
          fontFamily: 'var(--mantine-font-family-monospace)',
          overflowX: 'auto',
        },
      }}
```

- [ ] **Step 2: Run the windowing test to verify it fails**

Run: `npm run test -- run src/features/customLabels/ProductPreviewColumn.test.tsx` (workdir `frontend/`)
Expected: FAIL — "Unable to find element by [data-testid='preview-row-495']" (the test hardcodes `34 * 500` as scrollTop, which no longer lands at row 500)

- [ ] **Step 3: Fix the windowing test to use the constant**

In `frontend/src/features/customLabels/ProductPreviewColumn.test.tsx`: add to the imports (line 6 area):

```ts
import { ROW_HEIGHT } from './productPreview';
```

and replace the windowing test body line `renderColumn({ entries, matches: null, isFetching: false, scrollTop: 34 * 500 });` with:

```ts
    renderColumn({ entries, matches: null, isFetching: false, scrollTop: ROW_HEIGHT * 500 });
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- run src/features/customLabels/ProductPreviewColumn.test.tsx src/features/customLabels/productPreview.test.ts src/features/customLabels/RuleCard.test.tsx` (workdir `frontend/`)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/productPreview.ts frontend/src/features/customLabels/RuleValuesEditor.tsx frontend/src/features/customLabels/ProductPreviewColumn.test.tsx
git commit -m "feat(frontend): bump labelizer preview row height to 44px"
```

---

### Task 3: Shadow owner info + remove the footer "Overridden IDs" section

**Files:**
- Modify: `frontend/src/features/customLabels/shadowing.ts` (full rewrite below)
- Modify: `frontend/src/features/customLabels/RuleCard.tsx:1-9,11-27,112`
- Delete: `frontend/src/features/customLabels/ShadowList.tsx`
- Modify: `frontend/public/locales/en/customLabels.json` (remove `shadowListTitle`)
- Modify: `frontend/public/locales/de/customLabels.json` (remove `shadowListTitle`)
- Test: `frontend/src/features/customLabels/shadowing.test.ts`, `frontend/src/features/customLabels/RuleCard.test.tsx:90-109`, `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx:818-846`

**Interfaces:**
- Produces: `export type ShadowOwnerInfo = { id: string; name: string; priority: number }` in `shadowing.ts` (`priority` = 1-based position among the slot's ACTIVE rules).
- Produces: `RuleShadowInfo.shadowedBy: Map<string, ShadowOwnerInfo>` (was `Map<string, string>`). `RuleCardProps.shadowedBy` becomes `ReadonlyMap<string, ShadowOwnerInfo>` — consumed by Task 5 (inline `OVERRIDDEN BY #N` badges).
- Removes: `ShadowList` component and the `shadowListTitle` i18n key. The `shadowedBy` tooltip key is kept (reused as the badge tooltip).

- [ ] **Step 1: Update the shadowing tests to the new shape (fails first)**

In `frontend/src/features/customLabels/shadowing.test.ts`, replace the map-value assertions:

```ts
    expect(result.b.shadowedBy.get('2')).toBe('Bleeder');
```

with:

```ts
    expect(result.b.shadowedBy.get('2')).toEqual({ id: 'a', name: 'Bleeder', priority: 1 });
```

In the all-mode test:

```ts
    expect(result.b.shadowedBy.get('9')).toBe('Catch All');
```

with:

```ts
    expect(result.b.shadowedBy.get('9')).toEqual({ id: 'a', name: 'Catch All', priority: 1 });
```

In "values claimed before an all-mode rule stay attributed to their claimer":

```ts
    expect(result.b.shadowedBy.get('7')).toBe('First');
    expect(result.b.shadowedBy.get('8')).toBe('Catch All');
```

with:

```ts
    expect(result.b.shadowedBy.get('7')).toEqual({ id: 'a', name: 'First', priority: 1 });
    expect(result.b.shadowedBy.get('8')).toEqual({ id: 'm', name: 'Catch All', priority: 2 });
```

In "same-named rules still shadow":

```ts
    expect(result.b.shadowedBy.get('1')).toBe('X');
```

with:

```ts
    expect(result.b.shadowedBy.get('1')).toEqual({ id: 'a', name: 'X', priority: 1 });
```

In "a second all-mode rule is shadowed by the first all-mode rule":

```ts
    expect(result.m2.shadowedBy.get('9')).toBe('Catch');
    expect(result.b.shadowedBy.get('9')).toBe('Catch');
```

with:

```ts
    expect(result.m2.shadowedBy.get('9')).toEqual({ id: 'm1', name: 'Catch', priority: 1 });
    expect(result.b.shadowedBy.get('9')).toEqual({ id: 'm1', name: 'Catch', priority: 1 });
```

Add this new test inside the `describe`:

```ts
  it('carries the claiming rule id and its 1-based priority among the slot active rules', () => {
    const rules = [
      rule({ id: 'a', name: 'Bleeder', targetSlot: 'custom_label_0' }),
      rule({ id: 'x', name: 'Inactive', targetSlot: 'custom_label_0', isActive: false }),
      rule({ id: 'b', name: 'Later', targetSlot: 'custom_label_0' }),
    ];
    const result = computeShadowing(rules, { a: '5', b: '5' });
    expect(result.b.shadowedBy.get('5')).toEqual({ id: 'a', name: 'Bleeder', priority: 1 });
  });
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- run src/features/customLabels/shadowing.test.ts` (workdir `frontend/`)
Expected: FAIL — "expected 'Bleeder' to deeply equal { id: 'a', … }"

- [ ] **Step 3: Rewrite `shadowing.ts`**

Replace the full contents of `frontend/src/features/customLabels/shadowing.ts`:

```ts
import { parseIdList } from './ids';
import type { ScopedSlotRule } from './scopeMerge';

export type ShadowOwnerInfo = { id: string; name: string; priority: number };

export type RuleShadowInfo = {
  /** Values present in this rule but ignored — a higher-priority rule claims them. */
  shadowed: Set<string>;
  /** Shadowed value -> the first higher-priority rule that claims it. */
  shadowedBy: Map<string, ShadowOwnerInfo>;
};

/**
 * Syntactic first-match-wins analysis: per slot, walk ACTIVE rules in
 * evaluation order; a value already claimed by an earlier rule is shadowed.
 * An `all`-mode rule shadows every value of all lower-priority rules in the
 * slot. Inactive rules neither claim nor are shadowed. Claims are keyed by
 * rule id (names may duplicate across rules); `priority` is the owner's
 * 1-based position among its slot's active rules — the same #N the UI shows.
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
    const claimedBy = new Map<string, ShadowOwnerInfo>();
    let firstAll: ShadowOwnerInfo | undefined;
    for (const [index, rule] of slotRules.entries()) {
      const info = result[rule.id];
      const allOwner = firstAll;
      if (rule.matchMode === 'all') {
        firstAll ??= { id: rule.id, name: rule.name, priority: index + 1 };
      }
      for (const value of parseIdList(values[rule.id] ?? '')) {
        const owner = claimedBy.get(value) ?? allOwner;
        if (owner !== undefined && owner.id !== rule.id) {
          info.shadowed.add(value);
          info.shadowedBy.set(value, owner);
        } else if (rule.matchMode !== 'all') {
          claimedBy.set(value, { id: rule.id, name: rule.name, priority: index + 1 });
        }
      }
    }
  }
  return result;
}
```

- [ ] **Step 4: Run shadowing tests to verify they pass**

Run: `npm run test -- run src/features/customLabels/shadowing.test.ts` (workdir `frontend/`)
Expected: PASS

- [ ] **Step 5: Remove `ShadowList` from `RuleCard`, update its prop type**

In `frontend/src/features/customLabels/RuleCard.tsx`:

Remove the import line:

```ts
import { ShadowList } from './ShadowList';
```

Add after the `./RuleValuesEditor` import:

```ts
import type { ShadowOwnerInfo } from './shadowing';
```

Change the prop type (line 21):

```ts
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo>;
```

Delete the render line inside the panel (line 112):

```tsx
          <ShadowList shadowedBy={shadowedBy} />
```

Then delete the file:

```bash
git rm frontend/src/features/customLabels/ShadowList.tsx
```

- [ ] **Step 6: Update the affected component tests**

In `frontend/src/features/customLabels/RuleCard.test.tsx`, replace the test "shows a shadowed count badge and lists shadowed values with attribution tooltip" (lines 90-109) with:

```tsx
  it('shows a shadowed count badge; the footer overridden list is gone', async () => {
    renderCard({
      value: '2,3,5',
      shadowedBy: new Map([
        ['2', { id: 'r0', name: 'Bleeder', priority: 1 }],
        ['3', { id: 'r0', name: 'Bleeder', priority: 1 }],
      ]),
    });
    expect(screen.getByText('2 overridden')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(screen.queryByText(/overridden IDs/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('shadow-list')).not.toBeInTheDocument();
  });
```

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, replace lines 841-844 of the shadowing test:

```tsx
    await userEvent.click(screen.getByText('Later')); // expand
    expect(await screen.findByText(/overridden IDs/i)).toBeInTheDocument();
    const value2 = await screen.findByText('2', { exact: true });
    expect(value2).toHaveStyle({ textDecoration: 'line-through' });
```

with:

```tsx
    await userEvent.click(screen.getByText('Later')); // expand
    // footer overridden list is gone; the header badge carries the summary
    expect(screen.queryByText(/overridden IDs/i)).not.toBeInTheDocument();
```

- [ ] **Step 7: Remove the `shadowListTitle` i18n key (en + de)**

In `frontend/public/locales/en/customLabels.json` delete the line:

```json
  "shadowListTitle": "Overridden IDs (already matched by a higher-priority rule)",
```

In `frontend/public/locales/de/customLabels.json` delete the line:

```json
  "shadowListTitle": "Überschriebene IDs (bereits durch eine Regel mit höherer Priorität abgedeckt)",
```

- [ ] **Step 8: Run all affected tests + typecheck**

Run: `npm run test -- run src/features/customLabels` (workdir `frontend/`)
Expected: PASS (shadowing, RuleCard, CustomLabelsUI included)

Run: `npm run typecheck` (workdir `frontend/`)
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/customLabels/shadowing.ts frontend/src/features/customLabels/shadowing.test.ts frontend/src/features/customLabels/RuleCard.tsx frontend/src/features/customLabels/RuleCard.test.tsx frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json
git commit -m "refactor(frontend): shadowing emits owner rule id and priority; remove footer overridden list"
```

---

### Task 4: Coverage Dashboard per-rule net-hit badges

**Files:**
- Modify: `frontend/src/features/customLabels/CoverageDashboard.tsx` (full rewrite below)
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx:308-317`
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json`
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx:619-641`

**Interfaces:**
- Produces: `CoverageDashboardProps` gains `slotRules: ReadonlyArray<{ id: string; name: string }>` (active rules of the selected slot, in evaluation order) and `ruleStats: Readonly<Record<string, PreviewRuleStats>> | undefined`. Badge text = `t('coverage.ruleHits', { priority, name, hits })`, `data-testid="coverage-rule-hit-<ruleId>"`.
- Consumes: `PreviewRuleStats` (`{ matched, labeled, sample }`) from `./usePreview`; `labeled` is the net post-shadowing winner count — no backend change.

- [ ] **Step 1: Extend the dashboard test (fails first)**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, in the test "renders the overall coverage dashboard and per-rule match badges", add after the `coverage-stat-active-rules` assertion:

```tsx
    // per-rule net-hit badges beneath the progress bar (default slot custom_label_1)
    expect(screen.getByTestId('coverage-rule-hit-r1')).toHaveTextContent('#1 Mid Funnel: 2x');
    expect(screen.getByTestId('coverage-rule-hits')).toBeInTheDocument();
```

and after switching to `#3 CUSTOM_LABEL_2` (after the `'1 matched'` assertion):

```tsx
    expect(screen.getByTestId('coverage-rule-hit-r3')).toHaveTextContent('#1 Client Only: 0x');
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx` (workdir `frontend/`)
Expected: FAIL — "Unable to find element by [data-testid='coverage-rule-hit-r1']"

- [ ] **Step 3: Add the i18n keys**

In `frontend/public/locales/en/customLabels.json`, the `coverage` block becomes:

```json
  "coverage": {
    "labeledOf": "{{count}} / {{total}} staged products labeled",
    "totalProducts": "Total products",
    "labeled": "Labeled",
    "unlabeled": "Unlabeled",
    "activeRules": "Active rules",
    "ruleHits": "#{{priority}} {{name}}: {{hits}}x"
  },
```

In `frontend/public/locales/de/customLabels.json`, the `coverage` block becomes:

```json
  "coverage": {
    "labeledOf": "{{count}} / {{total}} gestagte Produkte gelabelt",
    "totalProducts": "Produkte insgesamt",
    "labeled": "Gelabelt",
    "unlabeled": "Nicht gelabelt",
    "activeRules": "Aktive Regeln",
    "ruleHits": "#{{priority}} {{name}}: {{hits}}x"
  },
```

(Note: `hits`, not `count` — `count` would trigger i18next pluralization lookup.)

- [ ] **Step 4: Rewrite `CoverageDashboard.tsx`**

Replace the full contents of `frontend/src/features/customLabels/CoverageDashboard.tsx`:

```tsx
import { Badge, Card, Group, Loader, Progress, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { PreviewRuleStats } from './usePreview';

export type CoverageDashboardProps = {
  total: number | undefined;
  labeledAny: number | undefined;
  activeRules: number;
  pending: boolean;
  errors: string[] | null;
  unavailable: boolean;
  slotRules: ReadonlyArray<{ id: string; name: string }>;
  ruleStats: Readonly<Record<string, PreviewRuleStats>> | undefined;
};

export function CoverageDashboard({
  total, labeledAny, activeRules, pending, errors, unavailable, slotRules, ruleStats,
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
        <Progress.Root size="sm" data-testid="coverage-progress">
          <Progress.Section value={pct} color="green" />
        </Progress.Root>
        {ruleStats !== undefined && slotRules.length > 0 && (
          <Group gap="xs" wrap="wrap" data-testid="coverage-rule-hits">
            {slotRules.map((rule, index) => (
              <Badge
                key={rule.id}
                size="xs"
                variant="light"
                data-testid={`coverage-rule-hit-${rule.id}`}
              >
                {t('coverage.ruleHits', {
                  priority: index + 1,
                  name: rule.name,
                  hits: ruleStats[rule.id]?.labeled ?? 0,
                })}
              </Badge>
            ))}
          </Group>
        )}
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

- [ ] **Step 5: Pass the new props from `CustomLabelsUI`**

In `frontend/src/features/customLabels/CustomLabelsUI.tsx`, the `CoverageDashboard` call (inside `idsPanel`) becomes:

```tsx
      {atFeed && (
        <CoverageDashboard
          total={preview.result?.total}
          labeledAny={preview.result?.labeledAny}
          activeRules={activeRules.length}
          pending={preview.isPending}
          errors={preview.errors}
          unavailable={preview.unavailable}
          slotRules={slotRules.map(({ id, name }) => ({ id, name }))}
          ruleStats={preview.result?.rules}
        />
      )}
```

(`slotRules` — the selected slot's active rules — is already defined at line 280, before `idsPanel`.)

- [ ] **Step 6: Run tests + typecheck**

Run: `npm run test -- run src/features/customLabels` (workdir `frontend/`)
Expected: PASS

Run: `npm run typecheck` (workdir `frontend/`)
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/customLabels/CoverageDashboard.tsx frontend/src/features/customLabels/CustomLabelsUI.tsx frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json
git commit -m "feat(frontend): coverage dashboard per-rule net-hit badges"
```

---

### Task 5: Line-aligned preview rows with inline override badges

**Files:**
- Modify: `frontend/src/features/customLabels/ProductPreviewColumn.tsx` (full rewrite below)
- Modify: `frontend/src/features/customLabels/RuleValuesEditor.tsx` (full rewrite below)
- Modify: `frontend/src/features/customLabels/RuleCard.tsx` (forward `shadowedBy`)
- Modify: `frontend/src/features/customLabels/ids.ts` (delete `parseIdEntries`)
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json`
- Test: rewrite `frontend/src/features/customLabels/ProductPreviewColumn.test.tsx`; modify `frontend/src/features/customLabels/__tests__/ids.test.ts`, `frontend/src/features/customLabels/RuleCard.test.tsx`, `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Produces: `ProductPreviewColumnProps` — `entries: string[]` replaced by `lines: string[][]`; adds `shadowedBy: ReadonlyMap<string, ShadowOwnerInfo> | null`. `PreviewRow` renders an orange `Badge` `t('overriddenBy', { priority })` (data-testid `overridden-badge`) when the line's first ID is shadowed, and a gray `+{{more}} more` badge (`nMoreIds`) when the line holds several IDs.
- Produces: `RuleValuesEditorProps` adds `shadowedBy: ReadonlyMap<string, ShadowOwnerInfo>` (forwarded by `RuleCard`).
- Deletes: `parseIdEntries` from `ids.ts` (replaced by `parsePreviewLines` from Task 1).

- [ ] **Step 1: Rewrite `ProductPreviewColumn.test.tsx` (fails first)**

Replace the full contents of `frontend/src/features/customLabels/ProductPreviewColumn.test.tsx`:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { createRef } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import { ROW_HEIGHT } from './productPreview';
import type { ProductLookupMatch, ProductLookupSample } from '../../api/types';

function match(count: number, sample: Partial<ProductLookupSample> | null): ProductLookupMatch {
  return {
    count,
    sample: sample === null ? null : {
      product_id: 'p1', status: 'active', excluded: false,
      title: 'T', brand: 'B', availability: 'in_stock', ...sample,
    },
  };
}

function owner(priority: number, name = 'Bleeder', id = 'r0') {
  return { id, name, priority };
}

function renderColumn(over: Partial<Parameters<typeof ProductPreviewColumn>[0]> = {}) {
  const viewportRef = createRef<HTMLDivElement>();
  render(
    <ProductPreviewColumn
      field="id"
      lines={[['a1'], ['zz'], ['a1']]}
      matches={new Map([
        ['a1', match(1, { title: 'Alpha', brand: 'Acme', availability: 'in_stock' })],
        ['zz', match(0, null)],
      ])}
      isFetching={false}
      isError={false}
      extraFields={['price']}
      shadowedBy={null}
      scrollTop={0}
      viewportRef={viewportRef}
      {...over}
    />,
  );
  return { viewportRef };
}

beforeAll(async () => {
  await i18n.loadNamespaces(['customLabels']);
});

describe('ProductPreviewColumn', () => {
  it('renders one row per line in order, aligned by index', () => {
    renderColumn();
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('preview-row-1')).toHaveTextContent('ID not found in feed');
    // duplicated IDs on separate lines render duplicated rows
    expect(screen.getByTestId('preview-row-2')).toHaveTextContent('Alpha');
  });

  it('renders blank rows for blank textarea lines', () => {
    renderColumn({ lines: [['a1'], [], ['zz']] });
    expect(screen.getByTestId('preview-row-1')).toHaveTextContent('—');
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('preview-row-2')).toHaveTextContent('ID not found in feed');
  });

  it('shows the first ID match plus a +N badge for multi-ID lines', () => {
    renderColumn({ lines: [['a1', 'zz', 'q1']] });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('+2 more');
    // zz is not the line's first ID — its dead-ID badge stays hidden
    expect(screen.getByTestId('preview-row-0')).not.toHaveTextContent('ID not found in feed');
  });

  it('renders an inline overridden-by badge with the claiming rule priority', () => {
    renderColumn({ shadowedBy: new Map([['a1', owner(1)]]) });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Overridden by #1');
    expect(screen.getByTestId('preview-row-1')).not.toHaveTextContent('Overridden by');
  });

  it('renders availability and status badges on the sample', () => {
    renderColumn();
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('in_stock');
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Acme');
  });

  it('shows a count badge when one value matches several products', () => {
    renderColumn({
      lines: [['a1']],
      matches: new Map([['a1', match(7, { title: 'First' })]]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('7 products');
  });

  it('renders extra fields inline', () => {
    renderColumn({
      lines: [['a1']],
      matches: new Map([['a1', match(1, { price: '9.99 EUR' })]]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('9.99 EUR');
  });

  it('dims removed and excluded samples with a status badge', () => {
    renderColumn({
      lines: [['r1'], ['e1']],
      matches: new Map([
        ['r1', match(1, { status: 'removed', title: 'Gone' })],
        ['e1', match(1, { excluded: true, title: 'Hidden' })],
      ]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('removed');
    expect(screen.getByTestId('preview-row-1')).toHaveTextContent('excluded');
  });

  it('uses the no-match label for non-id fields', () => {
    renderColumn({ field: 'brand', lines: [['zz']] });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('No match in feed');
  });

  it('windows rows: renders only the slice for the given scrollTop', () => {
    const lines = Array.from({ length: 1000 }, (_, i) => [`v${i}`]);
    renderColumn({ lines, matches: null, isFetching: false, scrollTop: ROW_HEIGHT * 500 });
    expect(screen.getByTestId('preview-row-495')).toBeInTheDocument();
    expect(screen.queryByTestId('preview-row-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('preview-row-600')).not.toBeInTheDocument();
  });

  it('shows the empty hint inside the always-mounted viewport for an empty list', () => {
    renderColumn({ lines: [] });
    expect(screen.getByTestId('preview-empty')).toBeInTheDocument();
    // the viewport stays mounted when empty so the scroll-sync ref never detaches
    expect(screen.getByTestId('product-preview-viewport')).toBeInTheDocument();
  });

  it('shows the error line when the lookup failed', () => {
    renderColumn({ isError: true, matches: null, lines: [['a1']] });
    expect(screen.getByTestId('preview-error')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- run src/features/customLabels/ProductPreviewColumn.test.tsx` (workdir `frontend/`)
Expected: FAIL — render throws, `lines` is not a known prop / `entries` is required

- [ ] **Step 3: Add the i18n keys**

In `frontend/public/locales/en/customLabels.json`, after `"noMatchInFeed": "No match in feed",` add:

```json
  "overriddenBy": "Overridden by #{{priority}}",
  "nMoreIds": "+{{more}} more",
```

In `frontend/public/locales/de/customLabels.json`, after `"noMatchInFeed": "Kein Treffer im Feed",` add:

```json
  "overriddenBy": "Überschrieben durch #{{priority}}",
  "nMoreIds": "+{{more}} weitere",
```

- [ ] **Step 4: Rewrite `ProductPreviewColumn.tsx`**

Replace the full contents of `frontend/src/features/customLabels/ProductPreviewColumn.tsx`:

```tsx
import { Badge, Box, Group, Skeleton, Stack, Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { RefObject } from 'react';
import type { ProductLookupMatch } from '../../api/types';
import { ROW_HEIGHT, VIEWPORT_ROWS, availabilityColor, windowRange } from './productPreview';
import type { ShadowOwnerInfo } from './shadowing';

export type ProductPreviewColumnProps = {
  field: string;
  /** One row per textarea line; line i = its comma-split IDs. */
  lines: string[][];
  matches: ReadonlyMap<string, ProductLookupMatch> | null;
  isFetching: boolean;
  isError: boolean;
  extraFields: string[];
  /** Value -> claiming rule (this rule's shadowedBy map). */
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo> | null;
  scrollTop: number;
  viewportRef: RefObject<HTMLDivElement | null>;
};

export function ProductPreviewColumn({
  field, lines, matches, isFetching, isError, extraFields, shadowedBy, scrollTop, viewportRef,
}: ProductPreviewColumnProps) {
  const { t } = useTranslation('customLabels');
  const total = lines.length;
  const [start, end] = windowRange(scrollTop, total);

  return (
    <Stack gap={4} data-testid="product-preview-column">
      {isError ? (
        <Text size="xs" c="red" data-testid="preview-error">{t('previewError')}</Text>
      ) : null}
      <Box
        ref={viewportRef}
        data-testid="product-preview-viewport"
        style={{
          height: VIEWPORT_ROWS * ROW_HEIGHT,
          overflowY: 'auto',
          border: 'calc(0.0625rem * var(--mantine-scale)) solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-sm)',
        }}
      >
        {total === 0 ? (
          <Text size="xs" c="dimmed" px="xs" data-testid="preview-empty">{t('previewEmpty')}</Text>
        ) : (
          <div style={{ height: total * ROW_HEIGHT, position: 'relative' }}>
            {lines.slice(start, end).map((ids, offset) => {
              const index = start + offset;
              const match = ids.length > 0 ? matches?.get(ids[0]) ?? null : null;
              return (
                <Group
                  key={`${index}-${ids.join(',')}`}
                  gap="xs"
                  wrap="nowrap"
                  px="xs"
                  style={{
                    position: 'absolute',
                    top: index * ROW_HEIGHT,
                    height: ROW_HEIGHT,
                    left: 0,
                    right: 0,
                    alignItems: 'center',
                  }}
                  data-testid={`preview-row-${index}`}
                >
                  <PreviewRow
                    field={field}
                    ids={ids}
                    match={match}
                    isFetching={isFetching}
                    extraFields={extraFields}
                    shadowedBy={shadowedBy}
                  />
                </Group>
              );
            })}
          </div>
        )}
      </Box>
    </Stack>
  );
}

function PreviewRow({
  field, ids, match, isFetching, extraFields, shadowedBy,
}: {
  field: string;
  ids: string[];
  match: ProductLookupMatch | null;
  isFetching: boolean;
  extraFields: string[];
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo> | null;
}) {
  const { t } = useTranslation('customLabels');
  if (ids.length === 0) {
    return <Text size="xs" c="dimmed">—</Text>;
  }
  const owner = shadowedBy?.get(ids[0]) ?? null;
  return (
    <Group gap="xs" wrap="nowrap" w="100%" style={{ minHeight: 0 }}>
      {owner !== null && (
        <Tooltip label={t('shadowedBy', { name: owner.name })} withArrow position="top">
          <Badge size="xs" variant="light" color="orange" data-testid="overridden-badge">
            {t('overriddenBy', { priority: owner.priority })}
          </Badge>
        </Tooltip>
      )}
      {ids.length > 1 && (
        <Badge size="xs" variant="light" color="gray" data-testid="more-ids-badge">
          {t('nMoreIds', { more: ids.length - 1 })}
        </Badge>
      )}
      <MatchBody field={field} value={ids[0]} match={match} isFetching={isFetching} extraFields={extraFields} />
    </Group>
  );
}

function MatchBody({
  field, value, match, isFetching, extraFields,
}: {
  field: string;
  value: string;
  match: ProductLookupMatch | null;
  isFetching: boolean;
  extraFields: string[];
}) {
  const { t } = useTranslation('customLabels');
  if (match === null && isFetching) {
    return (
      <Group gap="xs" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
        <Skeleton height={14} width="45%" />
        <Skeleton height={14} width="20%" />
      </Group>
    );
  }
  if (match === null || match.count === 0) {
    return (
      <Badge size="xs" variant="light" color="red">
        {field === 'id' ? t('idNotFoundInFeed') : t('noMatchInFeed')}
      </Badge>
    );
  }
  const sample = match.sample;
  if (sample === null) return null;
  const title = sample.title === null ? value : sample.title;
  return (
    <>
      {match.count > 1 && (
        <Badge size="xs" variant="light" color="gray">
          {t('nProducts', { count: match.count })}
        </Badge>
      )}
      <Tooltip label={title} withArrow position="top" openDelay={300}>
        <Text size="xs" truncate style={{ flex: 1, minWidth: 0 }}>{title}</Text>
      </Tooltip>
      <Text size="xs" c="dimmed" truncate maw={120}>
        {sample.brand ?? '—'}
      </Text>
      <Badge size="xs" variant="light" color={availabilityColor(sample.availability)}>
        {sample.availability ?? '—'}
      </Badge>
      {extraFields.map((fieldName) => (
        <Text key={fieldName} size="xs" c="dimmed" truncate maw={160}>
          {sample[fieldName] == null ? '' : String(sample[fieldName])}
        </Text>
      ))}
      {sample.status === 'removed' && (
        <Badge size="xs" variant="light" color="gray">{t('stateRemoved')}</Badge>
      )}
      {sample.excluded && (
        <Badge size="xs" variant="light" color="gray">{t('stateExcluded')}</Badge>
      )}
    </>
  );
}
```

- [ ] **Step 5: Run the column tests to verify they pass**

Run: `npm run test -- run src/features/customLabels/ProductPreviewColumn.test.tsx` (workdir `frontend/`)
Expected: PASS

- [ ] **Step 6: Delete `parseIdEntries` and its tests**

In `frontend/src/features/customLabels/ids.ts` delete:

```ts
/** Ordered, trimmed, empty-dropped entries WITHOUT dedupe — row i of the
 * product preview aligns with entry i. */
export function parseIdEntries(raw: string | undefined | null): string[] {
  if (!raw) return [];
  const entries: string[] = [];
  for (const part of raw.split(/[\n,]+/)) {
    const trimmed = part.trim();
    if (trimmed) entries.push(trimmed);
  }
  return entries;
}
```

In `frontend/src/features/customLabels/__tests__/ids.test.ts`: delete the whole `describe('parseIdEntries', …)` block and make the import (line 2) exactly:

```ts
import {
  compileTemplate, formatIdList, parseIdList, parsePreviewLines, renderPreview,
} from '../ids';
```

- [ ] **Step 7: Switch `RuleValuesEditor` to line parsing and forward `shadowedBy`**

Replace the full contents of `frontend/src/features/customLabels/RuleValuesEditor.tsx` (still Grid-based; toolbar and toggle come in Tasks 6-7):

```tsx
import { useCallback, useMemo, useRef, useState } from 'react';
import { CloseButton, Grid, Group, MultiSelect, Stack, Text, Textarea } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { useFeedSourceFields, useProductLookup } from '../../api/hooks';
import { parseIdList, parsePreviewLines } from './ids';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import { ROW_HEIGHT, useSyncedScroll } from './productPreview';
import type { ShadowOwnerInfo } from './shadowing';
import type { ScopedSlotRule } from './scopeMerge';

const PREVIEW_DEFAULT_FIELDS = new Set(['title', 'brand', 'availability']);

export type RuleValuesEditorProps = {
  rule: ScopedSlotRule;
  value: string;
  feedSourceId: number | undefined;
  extraFields: string[];
  onExtraFieldsChange: (fields: string[]) => void;
  onSetIds: (value: string) => void;
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo>;
};

export function RuleValuesEditor({
  rule, value, feedSourceId, extraFields, onExtraFieldsChange, onSetIds, shadowedBy,
}: RuleValuesEditorProps) {
  const { t } = useTranslation('customLabels');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const onScrollTopChange = useCallback((top: number) => setScrollTop(top), []);
  useSyncedScroll(textareaRef, previewRef, onScrollTopChange, feedSourceId);

  const lines = useMemo(() => parsePreviewLines(value), [value]);
  const lookupValues = useMemo(() => Array.from(new Set(lines.flat())), [lines]);
  const [debouncedValues] = useDebouncedValue(lookupValues, 300);
  const lookup = useProductLookup(feedSourceId, rule.matchField, debouncedValues, extraFields);
  const matches = useMemo(
    () => (lookup.data?.matches ? new Map(Object.entries(lookup.data.matches)) : null),
    [lookup.data],
  );

  const fieldsQuery = useFeedSourceFields(String(feedSourceId ?? ''));
  const fieldOptions = useMemo(
    () => (fieldsQuery.data?.fields ?? []).filter((f) => !PREVIEW_DEFAULT_FIELDS.has(f)),
    [fieldsQuery.data],
  );

  const count = parseIdList(value).size;
  const label = rule.matchField === 'id'
    ? t('bulk.productIds')
    : t('bulk.valuesFor', { field: rule.matchField });
  const ariaLabel = rule.matchField === 'id'
    ? `${t('bulk.productIds')} — ${rule.name}`
    : `${t('bulk.valuesFor', { field: rule.matchField })} — ${rule.name}`;

  const textarea = (
    <Textarea
      label={label}
      aria-label={ariaLabel}
      ref={textareaRef}
      minRows={10}
      maxRows={10}
      autosize
      wrap="off"
      styles={{
        input: {
          lineHeight: `${ROW_HEIGHT}px`,
          fontFamily: 'var(--mantine-font-family-monospace)',
          overflowX: 'auto',
        },
      }}
      value={value}
      onChange={(e) => onSetIds(e.currentTarget.value)}
      placeholder={t('idsPlaceholder')}
    />
  );

  const footer = (
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
  );

  if (feedSourceId === undefined) {
    return (
      <Stack gap={4}>
        {textarea}
        {footer}
      </Stack>
    );
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="wrap">
        <Text size="sm" fw={600}>{t('previewTitle')}</Text>
        <MultiSelect
          size="xs"
          w={260}
          clearable
          searchable
          aria-label={t('previewFieldsLabel')}
          data={fieldOptions}
          value={extraFields}
          onChange={(v) => onExtraFieldsChange(v ?? [])}
          placeholder={t('previewFieldsLabel')}
          data-testid={`preview-fields-${rule.id}`}
        />
      </Group>
      <Grid columns={20} gap="xs">
        <Grid.Col span={7}>{textarea}</Grid.Col>
        <Grid.Col span={13}>
          <ProductPreviewColumn
            field={rule.matchField}
            lines={lines}
            matches={matches}
            isFetching={lookup.isFetching}
            isError={lookup.isError}
            extraFields={extraFields}
            shadowedBy={shadowedBy}
            scrollTop={scrollTop}
            viewportRef={previewRef}
          />
        </Grid.Col>
      </Grid>
      {footer}
    </Stack>
  );
}
```

- [ ] **Step 8: Forward `shadowedBy` from `RuleCard`**

In `frontend/src/features/customLabels/RuleCard.tsx`, the `<RuleValuesEditor …>` call becomes:

```tsx
            <RuleValuesEditor
              rule={rule}
              value={value}
              feedSourceId={feedSourceId}
              extraFields={extraFields}
              onExtraFieldsChange={onExtraFieldsChange}
              onSetIds={onSetIds}
              shadowedBy={shadowedBy}
            />
```

- [ ] **Step 9: Update the remaining tests**

In `frontend/src/features/customLabels/RuleCard.test.tsx`, in "with a feed source renders the split editor and preview rows", change the rendered value so each ID is on its own line:

```tsx
    renderCard({
      feedSourceId: 5,
      value: 'a1\nzz',
    });
```

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`:

1. In "at feed tier renders the split editor with preview rows from the lookup endpoint", add a data override so the two matched values are on separate lines (the shared `DATA` has `r1: 'a,b,c'` — one line, first-ID-only rendering would hide Bravo). The full test body becomes:

```tsx
  it('at feed tier renders the split editor with preview rows from the lookup endpoint', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.includes('/products/lookup')) return jsonResponse({
        matches: {
          a: { count: 1, sample: { product_id: 'a', status: 'active', excluded: false, title: 'Alpha', brand: 'Acme', availability: 'in_stock' } },
          b: { count: 1, sample: { product_id: 'b', status: 'active', excluded: false, title: 'Bravo', brand: 'Beta', availability: 'out_of_stock' } },
        },
      });
      if (url.startsWith('/plugins/custom_labels/data')) {
        return jsonResponse({ slotIds: { r1: 'a\nb', r3: 'z' } });
      }
      return jsonResponseFor(url);
    });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(await screen.findByText('Matched products')).toBeInTheDocument();
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(await screen.findByText('Bravo')).toBeInTheDocument();
  });
```

2. In the "CustomLabelsUI shadowing" test, append after the footer-gone assertion (preview is always visible at this stage):

```tsx
    // inline badge in the preview: line "2,3"'s first ID (2) is claimed by #1
    expect(await screen.findByText('Overridden by #1')).toBeInTheDocument();
```

- [ ] **Step 10: Run all customLabels tests + typecheck**

Run: `npm run test -- run src/features/customLabels` (workdir `frontend/`)
Expected: PASS

Run: `npm run typecheck` (workdir `frontend/`)
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add frontend/src/features/customLabels frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json
git commit -m "feat(frontend): line-aligned preview rows with inline override badges"
```

---

### Task 6: Value-list toolbar (clear + format & dedupe)

**Files:**
- Modify: `frontend/src/features/customLabels/RuleValuesEditor.tsx` (full rewrite below)
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json`
- Test: `frontend/src/features/customLabels/RuleCard.test.tsx`, `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx:682`

**Interfaces:**
- Produces: toolbar `Group` above the textarea with two tooltip'd `ActionIcon`s: `data-testid="clear-ids-<ruleId>"` (aria-label `"<clearValues> — <rule name>"`, disabled when `value === ''`, calls `onSetIds('')`) and `data-testid="format-ids-<ruleId>"` (aria-label `"<formatDedupe> — <rule name>"`, calls `onSetIds(formatIdList(value))`).
- Removes: the footer `CloseButton` and the "Matched products" (`previewTitle`) header row; the `MultiSelect` moves into the toolbar's right side.
- The eye/toggle button is NOT in this task (Task 7).

- [ ] **Step 1: Write the failing toolbar test**

Add to `frontend/src/features/customLabels/RuleCard.test.tsx` (after the "expanding reveals the textarea" test):

```tsx
  it('toolbar clears and formats the value list; both disable when empty', async () => {
    const { onSetIds } = renderCard({ value: 'b, a\n\n a \nc,\n' });
    await userEvent.click(screen.getByText('Mid Funnel'));
    const textarea = await screen.findByRole('textbox', { name: /product ids — mid funnel/i });
    expect(textarea).toHaveValue('b, a\n\n a \nc,\n');
    await userEvent.click(
      screen.getByRole('button', { name: /format & remove duplicates — mid funnel/i }),
    );
    expect(onSetIds).toHaveBeenLastCalledWith('b\na\nc');
    expect(textarea).toHaveValue('b\na\nc');
    await userEvent.click(screen.getByRole('button', { name: /clear value list — mid funnel/i }));
    expect(onSetIds).toHaveBeenLastCalledWith('');
    expect(textarea).toHaveValue('');
    expect(
      screen.getByRole('button', { name: /format & remove duplicates — mid funnel/i }),
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: /clear value list — mid funnel/i }),
    ).toBeDisabled();
  });
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- run src/features/customLabels/RuleCard.test.tsx` (workdir `frontend/`)
Expected: FAIL — "Unable to find an accessible element with the role 'button' and name /format & remove duplicates/"

- [ ] **Step 3: Add i18n keys, remove `previewTitle`**

In `frontend/public/locales/en/customLabels.json`: after `"clearValues": "Clear value list",` add:

```json
  "formatDedupe": "Format & remove duplicates",
```

and delete the line `"previewTitle": "Matched products",`.

In `frontend/public/locales/de/customLabels.json`: after `"clearValues": "Werteliste leeren",` add:

```json
  "formatDedupe": "Formatieren & Duplikate entfernen",
```

and delete the line `"previewTitle": "Passende Produkte",`.

- [ ] **Step 4: Rewrite `RuleValuesEditor.tsx` with the toolbar**

Replace the full contents of `frontend/src/features/customLabels/RuleValuesEditor.tsx`:

```tsx
import { useCallback, useMemo, useRef, useState } from 'react';
import {
  ActionIcon, Grid, Group, MultiSelect, Stack, Text, Textarea, Tooltip,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { IconTrash, IconWand } from '@tabler/icons-react';
import { useFeedSourceFields, useProductLookup } from '../../api/hooks';
import { formatIdList, parseIdList, parsePreviewLines } from './ids';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import { ROW_HEIGHT, useSyncedScroll } from './productPreview';
import type { ShadowOwnerInfo } from './shadowing';
import type { ScopedSlotRule } from './scopeMerge';

const PREVIEW_DEFAULT_FIELDS = new Set(['title', 'brand', 'availability']);

export type RuleValuesEditorProps = {
  rule: ScopedSlotRule;
  value: string;
  feedSourceId: number | undefined;
  extraFields: string[];
  onExtraFieldsChange: (fields: string[]) => void;
  onSetIds: (value: string) => void;
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo>;
};

export function RuleValuesEditor({
  rule, value, feedSourceId, extraFields, onExtraFieldsChange, onSetIds, shadowedBy,
}: RuleValuesEditorProps) {
  const { t } = useTranslation('customLabels');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const onScrollTopChange = useCallback((top: number) => setScrollTop(top), []);
  useSyncedScroll(textareaRef, previewRef, onScrollTopChange, feedSourceId);

  const lines = useMemo(() => parsePreviewLines(value), [value]);
  const lookupValues = useMemo(() => Array.from(new Set(lines.flat())), [lines]);
  const [debouncedValues] = useDebouncedValue(lookupValues, 300);
  const lookup = useProductLookup(feedSourceId, rule.matchField, debouncedValues, extraFields);
  const matches = useMemo(
    () => (lookup.data?.matches ? new Map(Object.entries(lookup.data.matches)) : null),
    [lookup.data],
  );

  const fieldsQuery = useFeedSourceFields(String(feedSourceId ?? ''));
  const fieldOptions = useMemo(
    () => (fieldsQuery.data?.fields ?? []).filter((f) => !PREVIEW_DEFAULT_FIELDS.has(f)),
    [fieldsQuery.data],
  );

  const count = parseIdList(value).size;
  const label = rule.matchField === 'id'
    ? t('bulk.productIds')
    : t('bulk.valuesFor', { field: rule.matchField });
  const ariaLabel = rule.matchField === 'id'
    ? `${t('bulk.productIds')} — ${rule.name}`
    : `${t('bulk.valuesFor', { field: rule.matchField })} — ${rule.name}`;

  const textarea = (
    <Textarea
      label={label}
      aria-label={ariaLabel}
      ref={textareaRef}
      minRows={10}
      maxRows={10}
      autosize
      wrap="off"
      styles={{
        input: {
          lineHeight: `${ROW_HEIGHT}px`,
          fontFamily: 'var(--mantine-font-family-monospace)',
          overflowX: 'auto',
        },
      }}
      value={value}
      onChange={(e) => onSetIds(e.currentTarget.value)}
      placeholder={t('idsPlaceholder')}
    />
  );

  const toolbar = (
    <Group justify="space-between" wrap="nowrap" gap="xs">
      <Group gap={4} wrap="nowrap">
        <Tooltip label={t('clearValues')} withArrow position="top" openDelay={300}>
          <ActionIcon
            variant="default"
            size="sm"
            aria-label={`${t('clearValues')} — ${rule.name}`}
            disabled={value === ''}
            onClick={() => onSetIds('')}
            data-testid={`clear-ids-${rule.id}`}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t('formatDedupe')} withArrow position="top" openDelay={300}>
          <ActionIcon
            variant="default"
            size="sm"
            aria-label={`${t('formatDedupe')} — ${rule.name}`}
            disabled={value === ''}
            onClick={() => onSetIds(formatIdList(value))}
            data-testid={`format-ids-${rule.id}`}
          >
            <IconWand size={16} />
          </ActionIcon>
        </Tooltip>
      </Group>
      {feedSourceId !== undefined && (
        <MultiSelect
          size="xs"
          w={220}
          clearable
          searchable
          aria-label={t('previewFieldsLabel')}
          data={fieldOptions}
          value={extraFields}
          onChange={(v) => onExtraFieldsChange(v ?? [])}
          placeholder={t('previewFieldsLabel')}
          data-testid={`preview-fields-${rule.id}`}
        />
      )}
    </Group>
  );

  const footer = (
    <Group gap="xs" justify="space-between" wrap="nowrap">
      <Text size="xs" c="dimmed" data-testid={`id-count-${rule.id}`}>
        {t('idCount', { count })}
      </Text>
      <Text size="xs" c="dimmed">{rule.matchField}</Text>
    </Group>
  );

  if (feedSourceId === undefined) {
    return (
      <Stack gap={4}>
        {toolbar}
        {textarea}
        {footer}
      </Stack>
    );
  }

  return (
    <Stack gap="xs">
      {toolbar}
      <Grid columns={20} gap="xs">
        <Grid.Col span={7}>{textarea}</Grid.Col>
        <Grid.Col span={13}>
          <ProductPreviewColumn
            field={rule.matchField}
            lines={lines}
            matches={matches}
            isFetching={lookup.isFetching}
            isError={lookup.isError}
            extraFields={extraFields}
            shadowedBy={shadowedBy}
            scrollTop={scrollTop}
            viewportRef={previewRef}
          />
        </Grid.Col>
      </Grid>
      {footer}
    </Stack>
  );
}
```

- [ ] **Step 5: Update the CustomLabelsUI split-editor test**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, in "at feed tier renders the split editor with preview rows from the lookup endpoint", delete the line:

```tsx
    expect(await screen.findByText('Matched products')).toBeInTheDocument();
```

- [ ] **Step 6: Run all customLabels tests + typecheck**

Run: `npm run test -- run src/features/customLabels` (workdir `frontend/`)
Expected: PASS

Run: `npm run typecheck` (workdir `frontend/`)
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/customLabels/RuleValuesEditor.tsx frontend/src/features/customLabels/RuleCard.test.tsx frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json
git commit -m "feat(frontend): labelizer value-list toolbar with clear and format actions"
```

---

### Task 7: Toggleable side-by-side preview with fixed-width editor

**Files:**
- Modify: `frontend/src/features/customLabels/RuleValuesEditor.tsx` (full rewrite below)
- Modify: `frontend/src/features/customLabels/ProductPreviewColumn.tsx` (error line moves inside the viewport)
- Modify: `frontend/src/features/customLabels/RuleCard.tsx` (forward `previewOpen` / `onTogglePreview`)
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx:169-173,318-345`
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json`
- Test: `frontend/src/features/customLabels/RuleCard.test.tsx`, `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Produces: `RuleCardProps` and `RuleValuesEditorProps` gain `previewOpen: boolean` and `onTogglePreview: () => void`. `CustomLabelsUI` owns `useDisclosure(false)` — one shared toggle for all cards, collapsed by default.
- Produces: toolbar eye button `data-testid="toggle-preview-<ruleId>"`, aria-label `"<togglePreview> — <rule name>"`, only rendered when `feedSourceId !== undefined`. `MultiSelect` visible only while the preview is open.
- Produces: fixed-width split: textarea wrapper `flex: 0 0 380px` (`Box w={380}`), preview wrapper `flex: 1 1 auto; minWidth: 0`, inside a plain flex `Box` with `alignItems: 'stretch'`. The textarea keeps `aria-label` but drops its visible `label` prop (the label text moves into the toolbar); input gets zero vertical padding so line *i*'s top = `i * ROW_HEIGHT` exactly.
- `useSyncedScroll`'s `rebindKey` becomes `` `${feedSourceId}-${previewOpen}` `` so listeners re-attach when the preview mounts.

- [ ] **Step 1: Update the tests (fails first)**

In `frontend/src/features/customLabels/RuleCard.test.tsx`:

1. Wire the toggle into the harness `Harness` (add state):

```tsx
  function Harness() {
    const [value, setValue] = useState(initialValue);
    const [previewOpen, setPreviewOpen] = useState(false);
    return (
      <QueryClientProvider client={client}>
        <Accordion multiple>
          <RuleCard
            rule={RULE}
            priority={1}
            dirty={false}
            inheritedFrom={null}
            editable={false}
            showLive={false}
            shadowedBy={new Map()}
            feedSourceId={undefined}
            extraFields={[]}
            onExtraFieldsChange={() => {}}
            onSetIds={(next) => {
              onSetIds(next);
              setValue(next);
            }}
            onPatchRule={() => {}}
            {...over}
            value={value}
            previewOpen={previewOpen}
            onTogglePreview={() => setPreviewOpen((o) => !o)}
          />
        </Accordion>
      </QueryClientProvider>
    );
  }
```

2. Replace "with a feed source renders the split editor and preview rows" with:

```tsx
  it('with a feed source the preview is collapsed by default and opens via the toolbar toggle', async () => {
    stubFetch((url) => {
      if (url.includes('/products/lookup')) {
        return jsonResponse({
          matches: {
            a1: {
              count: 1,
              sample: {
                product_id: 'a1', status: 'active', excluded: false,
                title: 'Alpha', brand: 'Acme', availability: 'in_stock',
              },
            },
          },
        });
      }
      return jsonResponse({});
    });
    renderCard({
      feedSourceId: 5,
      value: 'a1\nzz',
    });
    await userEvent.click(screen.getByText('Mid Funnel'));
    // collapsed by default
    expect(screen.queryByTestId('product-preview-viewport')).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: /show\/hide product preview — mid funnel/i }),
    );
    const viewport = await screen.findByTestId('product-preview-viewport');
    expect(viewport).toBeInTheDocument();
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(await screen.findByText('ID not found in feed')).toBeInTheDocument();
  });
```

3. In "expanding reveals the textarea with the ID counter below it (no overlap)", append:

```tsx
    // no preview toggle without feed context
    expect(screen.queryByRole('button', { name: /product preview/i })).not.toBeInTheDocument();
```

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`:

1. Replace "at feed tier renders the split editor with preview rows from the lookup endpoint" with:

```tsx
  it('at feed tier the preview is collapsed by default and opens via the shared toolbar toggle', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.includes('/products/lookup')) return jsonResponse({
        matches: {
          a: { count: 1, sample: { product_id: 'a', status: 'active', excluded: false, title: 'Alpha', brand: 'Acme', availability: 'in_stock' } },
          b: { count: 1, sample: { product_id: 'b', status: 'active', excluded: false, title: 'Bravo', brand: 'Beta', availability: 'out_of_stock' } },
        },
      });
      if (url.startsWith('/plugins/custom_labels/data')) {
        return jsonResponse({ slotIds: { r1: 'a\nb', r3: 'z' } });
      }
      return jsonResponseFor(url);
    });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(screen.queryByTestId('product-preview-viewport')).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: /show\/hide product preview — mid funnel/i }),
    );
    expect(await screen.findByTestId('product-preview-viewport')).toBeInTheDocument();
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Bravo')).toBeInTheDocument();
  });

  it('the preview toggle is shared across rule cards', async () => {
    const twoInOneSlot = {
      slotRules: [
        { id: 'r1', name: 'Mid Funnel', isActive: true, targetSlot: 'custom_label_1',
          matchField: 'id', valueTemplate: 'x', fallbackTemplate: '' },
        { id: 'r4', name: 'Second', isActive: true, targetSlot: 'custom_label_1',
          matchField: 'id', valueTemplate: 'y', fallbackTemplate: '' },
      ],
    };
    const handler = (url: string) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(twoInOneSlot);
      if (url.startsWith('/plugins/custom_labels/data')) {
        return jsonResponse({ slotIds: { r1: 'a', r4: 'b' } });
      }
      if (url.includes('/products/lookup')) return jsonResponse({ matches: {} });
      return jsonResponseFor(url);
    };
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', handler);
    await screen.findByText('Mid Funnel');
    await screen.findByText('Second');
    await userEvent.click(screen.getByText('Mid Funnel'));
    await userEvent.click(screen.getByText('Second'));
    expect(screen.queryAllByTestId('product-preview-viewport')).toHaveLength(0);
    await userEvent.click(
      screen.getByRole('button', { name: /show\/hide product preview — mid funnel/i }),
    );
    expect(screen.getAllByTestId('product-preview-viewport')).toHaveLength(2);
  });
```

2. In "at client tier the preview column is absent (no feed context)", append:

```tsx
    // no preview toggle without feed context
    expect(screen.queryByRole('button', { name: /product preview/i })).not.toBeInTheDocument();
```

3. In the "CustomLabelsUI shadowing" test, insert the toggle click before the inline-badge assertion:

```tsx
    await userEvent.click(screen.getByRole('button', { name: /show\/hide product preview — later/i }));
    expect(await screen.findByText('Overridden by #1')).toBeInTheDocument();
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- run src/features/customLabels` (workdir `frontend/`)
Expected: FAIL — "Unable to find an accessible element with the role 'button' and name /show\/hide product preview/" (and type errors for the new props)

- [ ] **Step 3: Add the `togglePreview` i18n key**

In `frontend/public/locales/en/customLabels.json`, after `"formatDedupe": "Format & remove duplicates",` add:

```json
  "togglePreview": "Show/hide product preview",
```

In `frontend/public/locales/de/customLabels.json`, after `"formatDedupe": "Formatieren & Duplikate entfernen",` add:

```json
  "togglePreview": "Produktvorschau ein-/ausblenden",
```

- [ ] **Step 4: Rewrite `RuleValuesEditor.tsx` (final layout)**

Replace the full contents of `frontend/src/features/customLabels/RuleValuesEditor.tsx`:

```tsx
import { useCallback, useMemo, useRef, useState } from 'react';
import {
  ActionIcon, Box, Group, MultiSelect, Stack, Text, Textarea, Tooltip,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { IconEye, IconEyeOff, IconTrash, IconWand } from '@tabler/icons-react';
import { useFeedSourceFields, useProductLookup } from '../../api/hooks';
import { formatIdList, parseIdList, parsePreviewLines } from './ids';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import { ROW_HEIGHT, useSyncedScroll } from './productPreview';
import type { ShadowOwnerInfo } from './shadowing';
import type { ScopedSlotRule } from './scopeMerge';

const PREVIEW_DEFAULT_FIELDS = new Set(['title', 'brand', 'availability']);

export type RuleValuesEditorProps = {
  rule: ScopedSlotRule;
  value: string;
  feedSourceId: number | undefined;
  extraFields: string[];
  onExtraFieldsChange: (fields: string[]) => void;
  onSetIds: (value: string) => void;
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo>;
  previewOpen: boolean;
  onTogglePreview: () => void;
};

export function RuleValuesEditor({
  rule, value, feedSourceId, extraFields, onExtraFieldsChange, onSetIds, shadowedBy,
  previewOpen, onTogglePreview,
}: RuleValuesEditorProps) {
  const { t } = useTranslation('customLabels');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const onScrollTopChange = useCallback((top: number) => setScrollTop(top), []);
  useSyncedScroll(
    textareaRef, previewRef, onScrollTopChange, `${feedSourceId}-${previewOpen}`,
  );

  const lines = useMemo(() => parsePreviewLines(value), [value]);
  const lookupValues = useMemo(() => Array.from(new Set(lines.flat())), [lines]);
  const [debouncedValues] = useDebouncedValue(lookupValues, 300);
  const lookup = useProductLookup(feedSourceId, rule.matchField, debouncedValues, extraFields);
  const matches = useMemo(
    () => (lookup.data?.matches ? new Map(Object.entries(lookup.data.matches)) : null),
    [lookup.data],
  );

  const fieldsQuery = useFeedSourceFields(String(feedSourceId ?? ''));
  const fieldOptions = useMemo(
    () => (fieldsQuery.data?.fields ?? []).filter((f) => !PREVIEW_DEFAULT_FIELDS.has(f)),
    [fieldsQuery.data],
  );

  const count = parseIdList(value).size;
  const label = rule.matchField === 'id'
    ? t('bulk.productIds')
    : t('bulk.valuesFor', { field: rule.matchField });
  const ariaLabel = rule.matchField === 'id'
    ? `${t('bulk.productIds')} — ${rule.name}`
    : `${t('bulk.valuesFor', { field: rule.matchField })} — ${rule.name}`;

  const atFeed = feedSourceId !== undefined;

  const textarea = (
    <Textarea
      aria-label={ariaLabel}
      ref={textareaRef}
      minRows={10}
      maxRows={10}
      autosize
      wrap="off"
      styles={{
        input: {
          lineHeight: `${ROW_HEIGHT}px`,
          fontFamily: 'var(--mantine-font-family-monospace)',
          overflowX: 'auto',
          paddingTop: 0,
          paddingBottom: 0,
        },
      }}
      value={value}
      onChange={(e) => onSetIds(e.currentTarget.value)}
      placeholder={t('idsPlaceholder')}
    />
  );

  const toolbar = (
    <Group justify="space-between" wrap="nowrap" gap="xs">
      <Group gap="xs" wrap="nowrap">
        <Text size="xs" c="dimmed">{label}</Text>
        <Group gap={4} wrap="nowrap">
          <Tooltip label={t('clearValues')} withArrow position="top" openDelay={300}>
            <ActionIcon
              variant="default"
              size="sm"
              aria-label={`${t('clearValues')} — ${rule.name}`}
              disabled={value === ''}
              onClick={() => onSetIds('')}
              data-testid={`clear-ids-${rule.id}`}
            >
              <IconTrash size={16} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={t('formatDedupe')} withArrow position="top" openDelay={300}>
            <ActionIcon
              variant="default"
              size="sm"
              aria-label={`${t('formatDedupe')} — ${rule.name}`}
              disabled={value === ''}
              onClick={() => onSetIds(formatIdList(value))}
              data-testid={`format-ids-${rule.id}`}
            >
              <IconWand size={16} />
            </ActionIcon>
          </Tooltip>
          {atFeed && (
            <Tooltip label={t('togglePreview')} withArrow position="top" openDelay={300}>
              <ActionIcon
                variant={previewOpen ? 'filled' : 'default'}
                size="sm"
                aria-label={`${t('togglePreview')} — ${rule.name}`}
                onClick={onTogglePreview}
                data-testid={`toggle-preview-${rule.id}`}
              >
                {previewOpen ? <IconEyeOff size={16} /> : <IconEye size={16} />}
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      </Group>
      {atFeed && previewOpen && (
        <MultiSelect
          size="xs"
          w={220}
          clearable
          searchable
          aria-label={t('previewFieldsLabel')}
          data={fieldOptions}
          value={extraFields}
          onChange={(v) => onExtraFieldsChange(v ?? [])}
          placeholder={t('previewFieldsLabel')}
          data-testid={`preview-fields-${rule.id}`}
        />
      )}
    </Group>
  );

  const footer = (
    <Group gap="xs" justify="space-between" wrap="nowrap">
      <Text size="xs" c="dimmed" data-testid={`id-count-${rule.id}`}>
        {t('idCount', { count })}
      </Text>
      <Text size="xs" c="dimmed">{rule.matchField}</Text>
    </Group>
  );

  if (!atFeed) {
    return (
      <Stack gap={4}>
        {toolbar}
        {textarea}
        {footer}
      </Stack>
    );
  }

  return (
    <Stack gap="xs">
      {toolbar}
      <Box
        style={{
          display: 'flex',
          gap: 'var(--mantine-spacing-xs)',
          alignItems: 'stretch',
        }}
      >
        <Box w={380} style={{ flex: '0 0 380px' }}>{textarea}</Box>
        {previewOpen && (
          <Box style={{ flex: '1 1 auto', minWidth: 0 }}>
            <ProductPreviewColumn
              field={rule.matchField}
              lines={lines}
              matches={matches}
              isFetching={lookup.isFetching}
              isError={lookup.isError}
              extraFields={extraFields}
              shadowedBy={shadowedBy}
              scrollTop={scrollTop}
              viewportRef={previewRef}
            />
          </Box>
        )}
      </Box>
      {footer}
    </Stack>
  );
}
```

- [ ] **Step 5: Move the preview error line inside the viewport**

In `frontend/src/features/customLabels/ProductPreviewColumn.tsx`, so the outer column height stays constant (flush top/bottom with the textarea) even when the lookup fails, replace the `Stack` body's error banner + viewport content:

```tsx
  return (
    <Stack gap={4} data-testid="product-preview-column">
      <Box
        ref={viewportRef}
        data-testid="product-preview-viewport"
        style={{
          height: VIEWPORT_ROWS * ROW_HEIGHT,
          overflowY: 'auto',
          border: 'calc(0.0625rem * var(--mantine-scale)) solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-sm)',
        }}
      >
        {isError ? (
          <Text size="xs" c="red" px="xs" data-testid="preview-error">{t('previewError')}</Text>
        ) : total === 0 ? (
          <Text size="xs" c="dimmed" px="xs" data-testid="preview-empty">{t('previewEmpty')}</Text>
        ) : (
          <div style={{ height: total * ROW_HEIGHT, position: 'relative' }}>
            {lines.slice(start, end).map((ids, offset) => {
              const index = start + offset;
              const match = ids.length > 0 ? matches?.get(ids[0]) ?? null : null;
              return (
                <Group
                  key={`${index}-${ids.join(',')}`}
                  gap="xs"
                  wrap="nowrap"
                  px="xs"
                  style={{
                    position: 'absolute',
                    top: index * ROW_HEIGHT,
                    height: ROW_HEIGHT,
                    left: 0,
                    right: 0,
                    alignItems: 'center',
                  }}
                  data-testid={`preview-row-${index}`}
                >
                  <PreviewRow
                    field={field}
                    ids={ids}
                    match={match}
                    isFetching={isFetching}
                    extraFields={extraFields}
                    shadowedBy={shadowedBy}
                  />
                </Group>
              );
            })}
          </div>
        )}
      </Box>
    </Stack>
  );
```

- [ ] **Step 6: Forward the toggle props through `RuleCard`**

In `frontend/src/features/customLabels/RuleCard.tsx`:

Add to `RuleCardProps` (after `onPatchRule`):

```ts
  previewOpen: boolean;
  onTogglePreview: () => void;
```

Extend the destructured parameter list to include `previewOpen, onTogglePreview`, and the `<RuleValuesEditor …>` call becomes:

```tsx
            <RuleValuesEditor
              rule={rule}
              value={value}
              feedSourceId={feedSourceId}
              extraFields={extraFields}
              onExtraFieldsChange={onExtraFieldsChange}
              onSetIds={onSetIds}
              shadowedBy={shadowedBy}
              previewOpen={previewOpen}
              onTogglePreview={onTogglePreview}
            />
```

- [ ] **Step 7: Own the toggle state in `CustomLabelsUI`**

In `frontend/src/features/customLabels/CustomLabelsUI.tsx`:

After the `const [previewFields, setPreviewFields] = useState<Record<string, string[]>>({});` line add:

```tsx
  const [previewOpen, { toggle: togglePreview }] = useDisclosure(false);
```

In the `idsPanel` `<RuleCard …>` map, add the two props:

```tsx
            previewOpen={previewOpen}
            onTogglePreview={togglePreview}
```

- [ ] **Step 8: Run all customLabels tests + typecheck**

Run: `npm run test -- run src/features/customLabels` (workdir `frontend/`)
Expected: PASS

Run: `npm run typecheck` (workdir `frontend/`)
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/customLabels frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json
git commit -m "feat(frontend): toggleable side-by-side preview with fixed-width value editor"
```

---

### Task 8: ADR-0008 update + full verification gates

**Files:**
- Modify: `docs/decisions/0008-labelizer-product-preview-and-batch-lookup.md`

**Interfaces:**
- Consumes: everything from Tasks 1-7. No code changes.

- [ ] **Step 1: Update ADR-0008**

In `docs/decisions/0008-labelizer-product-preview-and-batch-lookup.md`:

1. Replace decision **2** (the "Synchronized, windowed preview column" block, lines 24-33) with:

```
2. **Synchronized, windowed, toggleable preview column** — at feed tier each expanded
   rule card renders a compact toolbar (clear, format & dedupe, preview toggle,
   extra fields) above a fixed-width flex row: the value textarea is bounded to
   380px (`flex: 0 0 380px`) in both states, and the preview column (`flex: 1`)
   is **collapsed by default** — one shared toggle lifted to `CustomLabelsUI`
   flips it for every card. Preview row *i* mirrors textarea **line** *i*
   (split on `\n` only; blank lines render blank rows so alignment never breaks;
   a multi-ID line shows its first ID's match plus a `+N more` badge, and the
   Format toolbar action normalizes commas to one ID per line). Rows are 44px
   (`ROW_HEIGHT` in `productPreview.ts`); the textarea input uses zero vertical
   padding with `line-height: 44px`, so line *i*'s top is exactly `i × 44` —
   flush with the absolutely-positioned preview rows and free of the constant
   top offset the first iteration carried. Fixed-row windowing is custom
   (~30 lines: scrollTop → slice) — **no new dependency**;
   `@tanstack/react-virtual` was re-rejected for a 1-D fixed-row list where
   textarea↔list scroll sync is custom code either way. Scroll sync is
   bidirectional `scrollTop` copying with a rAF-released guard flag and a
   rebind key (feed source + preview visibility) so listeners re-attach when
   the synced elements remount. Lookups are 300 ms-debounced,
   TanStack-Query-cached (keyed by sorted value set + fields;
   `keepPreviousData`), skeleton rows shown while fetching so newly typed
   values never flash as dead.
```

2. After decision **4**, add:

```
5. **Shadow attribution moved inline (2026-09-08 rule-card refactor)** — the
   card-footer "Overridden IDs" struck-through list is removed; shadowing is
   communicated by the header `N overridden` badge plus an inline orange
   `OVERRIDDEN BY #N` badge on the affected preview row (tooltip: claiming
   rule name). `computeShadowing` now emits the claiming rule's id, name, and
   1-based slot priority.
6. **Coverage dashboard rule breakdown (2026-09-08 rule-card refactor)** —
   beneath the dashboard progress bar, a wrapping group of `#N name: Mx`
   badges shows each active rule of the selected slot with its **net**
   assigned product count — the preview endpoint's per-rule `labeled` stat
   (winners only, post-shadowing; `matched` remains the pre-shadowing count
   shown in card headers).
```

3. Replace the "Row alignment is by parsed-entry index…" consequence bullet with:

```
- Row alignment is by textarea line index: row *i* = line *i*; comma-separated
  one-liners stay on one row (first-ID match + `+N more`), and the Format
  toolbar action normalizes to one ID per line.
```

4. In the last consequence bullet, change "the row height (34px)" to "the row height (44px)".

- [ ] **Step 2: Check for stale references**

Run: `grep -rn "34px\|35/65\|spans 7/13\|Overridden IDs\|parseIdEntries\|previewTitle\|shadowListTitle" frontend/src frontend/public docs/decisions` (from repo root)
Expected: no hits. (Scoped to live code and the ADR: historical specs/plans under `docs/superpowers/` intentionally keep their original text as records.)

- [ ] **Step 3: Run the full verification gates**

Run from `frontend/`:

```bash
npm run test -- run
npm run typecheck
npm run build
```

Expected: all PASS — full vitest suite green, `tsc -b` clean, production build succeeds.

- [ ] **Step 4: Commit**

```bash
git add docs/decisions/0008-labelizer-product-preview-and-batch-lookup.md
git commit -m "docs: update ADR-0008 for the labelizer rule card refactor"
```

---

## Self-Review Notes

- Spec §1 (dashboard) → Task 4; §2 (toolbar) → Tasks 6+7; §3 (layout/width) → Task 7; §4 (rows/badges/sync) → Tasks 2+5+7; §5 (footer cleanup) → Task 3; §6 (i18n) → spread across tasks 3-7 (en+de parity each time); §7 (tests) → every task; §8 (ADR) → Task 8.
- Type consistency verified: `ShadowOwnerInfo` (Task 3) flows `CustomLabelsUI` → `RuleCard` → `RuleValuesEditor` → `ProductPreviewColumn` (Tasks 5+7); `parsePreviewLines`/`formatIdList` (Task 1) consumed in Tasks 5/6/7; `ROW_HEIGHT` (Task 2) consumed by all layout code; `previewOpen`/`onTogglePreview` (Task 7) threaded through all three layers.
- i18n keys avoid i18next's pluralizing `count` variable for numeric interpolations (`hits`, `more`, `priority`).
