# Findings & Quality Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deepen the quality-findings UX (grouping, rule guidance, drill-down, table ergonomics) and unify the quality surfaces behind one shared findings module, with a tiny `/dashboard/summary` addition for feed-card badges.

**Architecture:** New `frontend/src/features/monitoring/findings/` domain module owns severity, the rule catalog, grouping helpers, shared badges/labels, the explorer and the charts. `MonitoringFindingsPage` composes them; `FindingsTable` is reused by the explorer and dry-run. One backend change: per-feed quality counts in `/dashboard/summary` (no migration, no new endpoint).

**Tech Stack:** React 19, Mantine 9.5.2, `@tanstack/react-table` 9.2.3 (client-side sort/pagination), TanStack Query, i18next; FastAPI + SQLAlchemy async.

**Spec:** `docs/superpowers/specs/2026-09-16-findings-quality-ux-design.md`

## Global Constraints

- Frontend commands run from `frontend/`: `npm run typecheck`, `npm run test` (vitest), `npm run build`.
- Backend commands run from `backend/`: `uv run ruff check . ../plugins` (exit-0), `uv run mypy .` (exit-0), `uv run pytest ...`, `uv run alembic check`.
- No new dependencies, no schema changes, no migrations.
- Server state lives only in TanStack Query; UI state is React built-ins.
- i18n parity: every new key is added to **both** `en` and `de`.
- Reserved plugin routes are untouched.
- Do not mutate `original_product`.
- Backend logger calls use lazy `%s` interpolation, never f-strings.
- Frontend tests use `stubFetch` from `src/test/fetch.ts`; backend tests use the `isolated_database_url`/`app_factory` fixtures.

---

### Task 1: Severity + rule catalog module and i18n catalog

**Files:**
- Create: `frontend/src/features/monitoring/findings/severity.ts`
- Create: `frontend/src/features/monitoring/findings/ruleCatalog.ts`
- Create: `frontend/src/features/monitoring/findings/severity.test.ts`
- Create: `frontend/src/features/monitoring/findings/ruleCatalog.test.ts`
- Modify: `frontend/public/locales/en/monitoring.json`
- Modify: `frontend/public/locales/de/monitoring.json`

**Interfaces:**
- Produces:
  - `SEVERITIES: readonly ['critical', 'warning', 'info']`, `Severity`, `severityColor(severity: string): string`, `severityRank(severity: string): number`
  - `RULE_CODES: readonly string[]`, `RULE_CATALOG: Record<string, RuleInfo>`, `UNKNOWN_RULE: RuleInfo`, `ruleInfo(code: string): RuleInfo`, `ruleTitle(code: string, t: TFunction): string`
  - i18n keys `rules.<code>.{title,description,remediation}` (13 codes) + `rules.unknown.{title,description,remediation}`

- [ ] **Step 1: Write `severity.ts`**

```ts
export const SEVERITIES = ['critical', 'warning', 'info'] as const;

export type Severity = (typeof SEVERITIES)[number];

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  warning: 'yellow',
  info: 'blue',
};

const SEVERITY_RANK: Record<string, number> = {
  critical: 0,
  warning: 1,
  info: 2,
};

export function severityColor(severity: string): string {
  return SEVERITY_COLOR[severity] ?? 'gray';
}

export function severityRank(severity: string): number {
  return SEVERITY_RANK[severity] ?? 99;
}
```

- [ ] **Step 2: Write `ruleCatalog.ts`**

```ts
import type { TFunction } from 'i18next';

export type RuleInfo = {
  titleKey: string;
  descriptionKey: string;
  remediationKey: string;
};

export const RULE_CODES = [
  'baseline_required',
  'brand_required',
  'gtin_mpn',
  'enum_values',
  'conditional_required',
  'date_format',
  'length_limits',
  'cardinality',
  'currency_consistency',
  'image_requirements',
  'variant_consistency',
  'volume_drop',
  'ai_policy_check',
] as const;

export const RULE_CATALOG: Record<string, RuleInfo> = Object.fromEntries(
  RULE_CODES.map((code) => [
    code,
    {
      titleKey: `rules.${code}.title`,
      descriptionKey: `rules.${code}.description`,
      remediationKey: `rules.${code}.remediation`,
    },
  ]),
);

export const UNKNOWN_RULE: RuleInfo = {
  titleKey: 'rules.unknown.title',
  descriptionKey: 'rules.unknown.description',
  remediationKey: 'rules.unknown.remediation',
};

export function ruleInfo(code: string): RuleInfo {
  return RULE_CATALOG[code] ?? UNKNOWN_RULE;
}

export function ruleTitle(code: string, t: TFunction): string {
  return t(ruleInfo(code).titleKey, { code });
}
```

- [ ] **Step 3: Add the catalog to the monitoring locales**

In `frontend/public/locales/en/monitoring.json`, add a top-level `"rules"` object (sibling of `"findings"`):

```json
"rules": {
  "unknown": {
    "title": "Unrecognized rule: {{code}}",
    "description": "No description is available for this rule.",
    "remediation": "Review the finding details and the GMC attribute requirements."
  },
  "baseline_required": {
    "title": "Missing required attribute",
    "description": "A required Google Merchant Center attribute is empty.",
    "remediation": "Fill the attribute in the source feed or via field mapping."
  },
  "brand_required": {
    "title": "Missing brand",
    "description": "The brand attribute is missing and the category is not exempt.",
    "remediation": "Provide a brand value or map it from a source field."
  },
  "gtin_mpn": {
    "title": "Identifier problem",
    "description": "The GTIN is missing without MPN and brand, or its checksum is invalid.",
    "remediation": "Add a valid GTIN, or provide both MPN and brand."
  },
  "enum_values": {
    "title": "Invalid value",
    "description": "The value is not one of the enum values allowed for this attribute.",
    "remediation": "Map the source value to an allowed value."
  },
  "conditional_required": {
    "title": "Missing dependent attribute",
    "description": "An attribute is required because another attribute is set.",
    "remediation": "Set the dependent attribute, or clear the attribute that requires it."
  },
  "date_format": {
    "title": "Invalid date",
    "description": "The date is not ISO-8601 or has no timezone.",
    "remediation": "Use an ISO-8601 timestamp with a timezone offset."
  },
  "length_limits": {
    "title": "Length out of range",
    "description": "The value exceeds or falls below the length allowed for this attribute.",
    "remediation": "Adjust the value to fit the GMC length limit."
  },
  "cardinality": {
    "title": "Wrong number of values",
    "description": "The attribute has more or fewer values than its kind allows.",
    "remediation": "Adjust the repeated values to the allowed cardinality."
  },
  "currency_consistency": {
    "title": "Currency mismatch",
    "description": "A price uses a currency other than the feed source currency.",
    "remediation": "Use the feed source currency or fix the price currency."
  },
  "image_requirements": {
    "title": "Image requirement",
    "description": "The image is missing, unsupported, or below the minimum size.",
    "remediation": "Provide a reachable image of at least 500x500 px in a supported format."
  },
  "variant_consistency": {
    "title": "Variant inconsistency",
    "description": "Variants in a group disagree on shared attributes.",
    "remediation": "Align the shared attributes across the variant group."
  },
  "volume_drop": {
    "title": "Catalog volume drop",
    "description": "The product count dropped sharply versus the previous run.",
    "remediation": "Check the source feed for truncation or fetch errors before publishing."
  },
  "ai_policy_check": {
    "title": "AI policy suggestion",
    "description": "The AI policy check flagged this product for review.",
    "remediation": "Review the AI suggestion and adjust the product data if needed."
  }
},
```

In `frontend/public/locales/de/monitoring.json`, add:

```json
"rules": {
  "unknown": {
    "title": "Unbekannte Regel: {{code}}",
    "description": "Für diese Regel liegt keine Beschreibung vor.",
    "remediation": "Prüfen Sie die Befunddetails und die GMC-Attributanforderungen."
  },
  "baseline_required": {
    "title": "Pflichtattribut fehlt",
    "description": "Ein erforderliches Google-Merchant-Center-Attribut ist leer.",
    "remediation": "Füllen Sie das Attribut in der Quellfeed oder über das Feldmapping."
  },
  "brand_required": {
    "title": "Marke fehlt",
    "description": "Das Attribut brand fehlt und die Kategorie ist nicht ausgenommen.",
    "remediation": "Geben Sie eine Marke an oder mappen Sie sie aus einem Quellfeld."
  },
  "gtin_mpn": {
    "title": "Identifikatorproblem",
    "description": "Die GTIN fehlt ohne MPN und Marke, oder ihre Prüfsumme ist ungültig.",
    "remediation": "Fügen Sie eine gültige GTIN hinzu oder geben Sie MPN und Marke an."
  },
  "enum_values": {
    "title": "Ungültiger Wert",
    "description": "Der Wert ist keiner der für dieses Attribut erlaubten Enum-Werte.",
    "remediation": "Mappen Sie den Quellwert auf einen erlaubten Wert."
  },
  "conditional_required": {
    "title": "Abhängiges Attribut fehlt",
    "description": "Ein Attribut ist erforderlich, weil ein anderes Attribut gesetzt ist.",
    "remediation": "Setzen Sie das abhängige Attribut oder entfernen Sie das auslösende Attribut."
  },
  "date_format": {
    "title": "Ungültiges Datum",
    "description": "Das Datum ist nicht ISO-8601 oder hat keine Zeitzone.",
    "remediation": "Verwenden Sie einen ISO-8601-Zeitstempel mit Zeitzonenversatz."
  },
  "length_limits": {
    "title": "Länge außerhalb des Bereichs",
    "description": "Der Wert überschreitet oder unterschreitet die für dieses Attribut erlaubte Länge.",
    "remediation": "Passen Sie den Wert an das GMC-Längenlimit an."
  },
  "cardinality": {
    "title": "Falsche Anzahl von Werten",
    "description": "Das Attribut hat mehr oder weniger Werte, als sein Typ erlaubt.",
    "remediation": "Passen Sie die wiederholten Werte an die erlaubte Kardinalität an."
  },
  "currency_consistency": {
    "title": "Währungsabweichung",
    "description": "Ein Preis verwendet eine andere Währung als die Feedquelle.",
    "remediation": "Verwenden Sie die Währung der Feedquelle oder korrigieren Sie den Preis."
  },
  "image_requirements": {
    "title": "Bildanforderung",
    "description": "Das Bild fehlt, wird nicht unterstützt oder ist zu klein.",
    "remediation": "Stellen Sie ein erreichbares Bild mit mindestens 500x500 px in einem unterstützten Format bereit."
  },
  "variant_consistency": {
    "title": "Varianteninkonsistenz",
    "description": "Varianten einer Gruppe unterscheiden sich bei gemeinsamen Attributen.",
    "remediation": "Vereinheitlichen Sie die gemeinsamen Attribute innerhalb der Variantengruppe."
  },
  "volume_drop": {
    "title": "Katalogvolumen eingebrochen",
    "description": "Die Produktanzahl ist gegenüber dem vorherigen Lauf stark gesunken.",
    "remediation": "Prüfen Sie die Quellfeed auf Kürzungen oder Abruffehler vor der Veröffentlichung."
  },
  "ai_policy_check": {
    "title": "KI-Richtlinienhinweis",
    "description": "Die KI-Richtlinienprüfung hat dieses Produkt zur Überprüfung markiert.",
    "remediation": "Prüfen Sie den KI-Hinweis und passen Sie die Produktdaten bei Bedarf an."
  }
},
```

- [ ] **Step 4: Write `severity.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import { SEVERITIES, severityColor, severityRank } from './severity';

describe('severity', () => {
  it('orders severities critical, warning, info', () => {
    expect(SEVERITIES).toEqual(['critical', 'warning', 'info']);
  });

  it('maps severities to Mantine colors', () => {
    expect(severityColor('critical')).toBe('red');
    expect(severityColor('warning')).toBe('yellow');
    expect(severityColor('info')).toBe('blue');
    expect(severityColor('nonsense')).toBe('gray');
  });

  it('ranks critical first and unknown last', () => {
    expect(severityRank('critical')).toBeLessThan(severityRank('warning'));
    expect(severityRank('warning')).toBeLessThan(severityRank('info'));
    expect(severityRank('nonsense')).toBe(99);
  });
});
```

- [ ] **Step 5: Write `ruleCatalog.test.ts` (backend guard)**

```ts
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { RULE_CATALOG, RULE_CODES, ruleInfo, UNKNOWN_RULE } from './ruleCatalog';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..');

const BACKEND_RULE_FILES = ['backend/app/qc/rules.py', 'backend/app/qc/ai_rules.py'];

function backendRuleIds(): string[] {
  const ids = new Set<string>();
  for (const relative of BACKEND_RULE_FILES) {
    const source = readFileSync(resolve(repoRoot, relative), 'utf8');
    for (const match of source.matchAll(/rule_id\s*=\s*"([^"]+)"/g)) ids.add(match[1]);
  }
  return [...ids].sort();
}

describe('ruleCatalog', () => {
  it('covers every backend rule_id', () => {
    const ids = backendRuleIds();
    expect(ids.length).toBeGreaterThan(0);
    for (const id of ids) {
      expect(RULE_CATALOG[id], `missing catalog entry for ${id}`).toBeDefined();
    }
  });

  it('lists exactly the known codes', () => {
    expect([...RULE_CODES].sort()).toEqual(Object.keys(RULE_CATALOG).sort());
  });

  it('falls back to the unknown rule', () => {
    expect(ruleInfo('does_not_exist')).toBe(UNKNOWN_RULE);
  });
});
```

- [ ] **Step 6: Run the tests**

Run: `npm run test -- src/features/monitoring/findings`
Expected: PASS (4 test files-worth of assertions; the backend guard reads the real rule files).

- [ ] **Step 7: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/features/monitoring/findings frontend/public/locales/en/monitoring.json frontend/public/locales/de/monitoring.json
git commit -m "feat(findings): severity + rule catalog module with i18n"
```

---

### Task 2: Grouping and filtering helpers

**Files:**
- Create: `frontend/src/features/monitoring/findings/groupFindings.ts`
- Create: `frontend/src/features/monitoring/findings/groupFindings.test.ts`

**Interfaces:**
- Consumes: `QualityFinding` from `../../../api/types`; `severityRank` from `./severity`.
- Produces:
  - `FEED_LEVEL_KEY = '__feed__'`
  - `SeverityCounts = { critical: number; warning: number; info: number }`
  - `FindingGroup = { key: string; findings: QualityFinding[]; counts: SeverityCounts }`
  - `countBySeverity(findings: QualityFinding[]): SeverityCounts`
  - `groupByRule(findings: QualityFinding[]): FindingGroup[]`
  - `groupByAttribute(findings: QualityFinding[]): FindingGroup[]`
  - `filterFindings(findings: QualityFinding[], filter: FindingsFilter): QualityFinding[]`

- [ ] **Step 1: Write `groupFindings.ts`**

```ts
import type { QualityFinding } from '../../../api/types';
import { severityRank } from './severity';

export const FEED_LEVEL_KEY = '__feed__';

export type SeverityCounts = { critical: number; warning: number; info: number };

export type FindingGroup = {
  key: string;
  findings: QualityFinding[];
  counts: SeverityCounts;
};

export function countBySeverity(findings: QualityFinding[]): SeverityCounts {
  const counts: SeverityCounts = { critical: 0, warning: 0, info: 0 };
  for (const finding of findings) {
    if (finding.severity in counts) counts[finding.severity as keyof SeverityCounts] += 1;
  }
  return counts;
}

function sortGroups(groups: FindingGroup[]): FindingGroup[] {
  return [...groups].sort((a, b) => {
    const rankA = Math.min(...a.findings.map((f) => severityRank(f.severity)));
    const rankB = Math.min(...b.findings.map((f) => severityRank(f.severity)));
    if (rankA !== rankB) return rankA - rankB;
    if (a.findings.length !== b.findings.length) return b.findings.length - a.findings.length;
    return a.key.localeCompare(b.key);
  });
}

function groupBy(
  findings: QualityFinding[],
  keyOf: (finding: QualityFinding) => string,
): FindingGroup[] {
  const buckets = new Map<string, QualityFinding[]>();
  for (const finding of findings) {
    const key = keyOf(finding);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(finding);
    else buckets.set(key, [finding]);
  }
  return sortGroups(
    [...buckets.entries()].map(([key, groupFindings]) => ({
      key,
      findings: groupFindings,
      counts: countBySeverity(groupFindings),
    })),
  );
}

export function groupByRule(findings: QualityFinding[]): FindingGroup[] {
  return groupBy(findings, (finding) => finding.code);
}

export function groupByAttribute(findings: QualityFinding[]): FindingGroup[] {
  return groupBy(findings, (finding) => finding.field ?? FEED_LEVEL_KEY);
}

export type FindingsFilter = {
  severities?: string[];
  rules?: string[];
  search?: string;
};

export function filterFindings(
  findings: QualityFinding[],
  { severities = [], rules = [], search = '' }: FindingsFilter,
): QualityFinding[] {
  const needle = search.trim().toLowerCase();
  return findings.filter((finding) => {
    if (severities.length > 0 && !severities.includes(finding.severity)) return false;
    if (rules.length > 0 && !rules.includes(finding.code)) return false;
    if (needle) {
      const haystack = `${finding.message} ${finding.product_id} ${finding.field ?? ''}`.toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}
```

- [ ] **Step 2: Write `groupFindings.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import type { QualityFinding } from '../../../api/types';
import {
  countBySeverity,
  filterFindings,
  FEED_LEVEL_KEY,
  groupByAttribute,
  groupByRule,
} from './groupFindings';

function finding(overrides: Partial<QualityFinding>): QualityFinding {
  return {
    severity: 'warning',
    code: 'brand_required',
    field: 'brand',
    message: 'missing brand',
    product_id: 'p1',
    details: {},
    ...overrides,
  };
}

const findings: QualityFinding[] = [
  finding({ severity: 'critical', code: 'gtin_mpn', field: 'gtin', product_id: 'p1', message: 'bad gtin' }),
  finding({ severity: 'warning', code: 'gtin_mpn', field: 'gtin', product_id: 'p2', message: 'no gtin' }),
  finding({ severity: 'info', code: 'image_requirements', field: null, product_id: '', message: 'image small' }),
];

describe('countBySeverity', () => {
  it('counts each severity', () => {
    expect(countBySeverity(findings)).toEqual({ critical: 1, warning: 1, info: 1 });
  });
});

describe('groupByRule', () => {
  it('groups by code and orders the critical group first', () => {
    const groups = groupByRule(findings);
    expect(groups.map((g) => g.key)).toEqual(['gtin_mpn', 'image_requirements']);
    expect(groups[0].findings).toHaveLength(2);
    expect(groups[0].counts).toEqual({ critical: 1, warning: 1, info: 0 });
  });
});

describe('groupByAttribute', () => {
  it('buckets findings without a field into the feed-level group', () => {
    const groups = groupByAttribute(findings);
    const feedLevel = groups.find((g) => g.key === FEED_LEVEL_KEY);
    expect(feedLevel?.findings).toHaveLength(1);
    expect(groups.some((g) => g.key === 'gtin')).toBe(true);
  });
});

describe('filterFindings', () => {
  it('filters by severity, rule and free text', () => {
    expect(filterFindings(findings, { severities: ['critical'] })).toHaveLength(1);
    expect(filterFindings(findings, { rules: ['gtin_mpn'] })).toHaveLength(2);
    expect(filterFindings(findings, { search: 'p2' })).toHaveLength(1);
    expect(filterFindings(findings, { search: 'IMAGE' })).toHaveLength(1);
    expect(filterFindings(findings, { search: 'nothing-here' })).toHaveLength(0);
  });
});
```

- [ ] **Step 3: Run the tests**

Run: `npm run test -- src/features/monitoring/findings/groupFindings.test.ts`
Expected: PASS

- [ ] **Step 4: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/features/monitoring/findings/groupFindings.ts frontend/src/features/monitoring/findings/groupFindings.test.ts
git commit -m "feat(findings): grouping and filtering helpers"
```

---

### Task 3: Shared primitives and FindingsTable update

**Files:**
- Create: `frontend/src/features/monitoring/findings/SeverityBadge.tsx`
- Create: `frontend/src/features/monitoring/findings/RuleLabel.tsx`
- Create: `frontend/src/features/monitoring/findings/FindingsSummary.tsx`
- Create: `frontend/src/features/monitoring/findings/SeverityBadge.test.tsx`
- Create: `frontend/src/features/monitoring/findings/RuleLabel.test.tsx`
- Modify: `frontend/src/features/monitoring/FindingsTable.tsx` (use the shared primitives)
- Modify: `frontend/src/features/monitoring/MonitoringFindingsPage.tsx` (import `FindingsSummary`)
- Delete: `frontend/src/features/monitoring/QualitySummaryCards.tsx`

**Interfaces:**
- Consumes: `severityColor`, `SEVERITIES`, `ruleInfo`, `ruleTitle`.
- Produces: `SeverityBadge({ severity })`, `RuleLabel({ code })`, `FindingsSummary({ counts, delta, hasPrevious, productCount })`.

- [ ] **Step 1: Write `SeverityBadge.tsx`**

```tsx
import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { severityColor } from './severity';

export function SeverityBadge({ severity }: { severity: string }) {
  const { t } = useTranslation('monitoring');
  return (
    <Badge color={severityColor(severity)} data-testid={`severity-badge-${severity}`}>
      {t(`severity.${severity}`, { defaultValue: severity })}
    </Badge>
  );
}
```

- [ ] **Step 2: Write `RuleLabel.tsx`**

```tsx
import { Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ruleInfo, ruleTitle } from './ruleCatalog';

export function RuleLabel({ code }: { code: string }) {
  const { t } = useTranslation('monitoring');
  const info = ruleInfo(code);
  return (
    <Tooltip label={t(info.descriptionKey)} withinPortal>
      <Text size="sm" component="span" data-testid={`rule-label-${code}`}>
        {ruleTitle(code, t)}
      </Text>
    </Tooltip>
  );
}
```

- [ ] **Step 3: Write `FindingsSummary.tsx`**

```tsx
import { Badge, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { SEVERITIES } from './severity';

type Props = {
  counts: { critical: number; warning: number; info: number };
  delta: { fixed: number; new: number; remaining: number };
  hasPrevious: boolean;
  productCount: number;
};

export function FindingsSummary({ counts, delta, hasPrevious, productCount }: Props) {
  const { t } = useTranslation('monitoring');
  return (
    <SimpleGrid cols={{ base: 1, sm: 3 }}>
      {SEVERITIES.map((severity) => (
        <Paper key={severity} p="md" radius="md" withBorder data-testid={`card-${severity}`}>
          <Stack gap={4}>
            <Text size="sm" c="dimmed">
              {t(`severity.${severity}`)}
            </Text>
            <Text size="xl" fw={700}>
              {counts[severity]}
            </Text>
            {hasPrevious && (
              <Group gap="xs">
                <Badge color="green" data-testid="delta-fixed">↓ {delta.fixed}</Badge>
                <Badge color="red" data-testid="delta-new">↑ {delta.new}</Badge>
              </Group>
            )}
          </Stack>
        </Paper>
      ))}
      <Text size="sm" c="dimmed" data-testid="of-products">
        {t('quality.ofProducts', { count: productCount })}
      </Text>
    </SimpleGrid>
  );
}
```

- [ ] **Step 4: Update `FindingsTable.tsx` to use the shared primitives**

Replace the whole file with:

```tsx
import { Table } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { QualityFinding as ApiQualityFinding } from '../../api/types';
import { RuleLabel } from './findings/RuleLabel';
import { SeverityBadge } from './findings/SeverityBadge';

export type QualityFinding = ApiQualityFinding;

type Props = {
  findings: QualityFinding[];
};

export function FindingsTable({ findings }: Props) {
  const { t } = useTranslation('monitoring');
  return (
    <Table data-testid="findings-table" striped>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('columns.severity')}</Table.Th>
          <Table.Th>{t('columns.code')}</Table.Th>
          <Table.Th>{t('columns.field')}</Table.Th>
          <Table.Th>{t('columns.message')}</Table.Th>
          <Table.Th>{t('columns.productId')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {findings.map((finding, idx) => (
          <Table.Tr key={`${finding.code}-${finding.product_id}-${idx}`} data-testid={`finding-row-${idx}`}>
            <Table.Td>
              <SeverityBadge severity={finding.severity} />
            </Table.Td>
            <Table.Td>
              <RuleLabel code={finding.code} />
            </Table.Td>
            <Table.Td>{finding.field}</Table.Td>
            <Table.Td>{finding.message}</Table.Td>
            <Table.Td>{finding.product_id}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
```

- [ ] **Step 5: Update `MonitoringFindingsPage.tsx` to import `FindingsSummary`**

Change the import line `import { QualitySummaryCards } from './QualitySummaryCards';` to
`import { FindingsSummary } from './findings/FindingsSummary';` and rename the JSX element
`<QualitySummaryCards` to `<FindingsSummary`. Delete `frontend/src/features/monitoring/QualitySummaryCards.tsx`.

- [ ] **Step 6: Write `SeverityBadge.test.tsx` and `RuleLabel.test.tsx`**

`SeverityBadge.test.tsx`:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { SeverityBadge } from './SeverityBadge';

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

describe('SeverityBadge', () => {
  it('renders the localized severity', () => {
    render(<SeverityBadge severity="critical" />);
    expect(screen.getByText('Critical')).toBeInTheDocument();
  });

  it('falls back to the raw value for unknown severities', () => {
    render(<SeverityBadge severity="weird" />);
    expect(screen.getByText('weird')).toBeInTheDocument();
  });
});
```

`RuleLabel.test.tsx`:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { RuleLabel } from './RuleLabel';

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

describe('RuleLabel', () => {
  it('renders the friendly title for a known rule', () => {
    render(<RuleLabel code="gtin_mpn" />);
    expect(screen.getByText('Identifier problem')).toBeInTheDocument();
  });

  it('renders the raw code for an unknown rule', () => {
    render(<RuleLabel code="totally_unknown" />);
    expect(screen.getByText('Unrecognized rule: totally_unknown')).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Run the affected tests**

Run: `npm run test -- src/features/monitoring`
Expected: PASS. `FindingsTable.test.tsx` still passes (severity text unchanged). In
`MonitoringFindingsPage.test.tsx`, two assertions in `filters rows by code via the code Select` now
see rule titles instead of raw codes — the `Select` options still use raw codes, so
`getByRole('option', { name: 'missing_title' })` is unchanged, but replace the final
`table.getByText('missing_title')` and `table.queryByText('low_image_quality')` with
`table.getByText('Unrecognized rule: missing_title')` and
`table.queryByText('Unrecognized rule: low_image_quality')` respectively.

- [ ] **Step 8: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/features/monitoring
git commit -m "feat(findings): shared severity badge, rule label and summary card"
```

---

### Task 4: FindingsExplorer and sortable/paginated FindingsTable

**Files:**
- Modify: `frontend/src/features/monitoring/FindingsTable.tsx` (add `onOpenProduct`, client-side sorting + pagination)
- Create: `frontend/src/features/monitoring/findings/FindingsExplorer.tsx`
- Create: `frontend/src/features/monitoring/findings/FindingsExplorer.test.tsx`
- Modify: `frontend/src/features/monitoring/FindingsTable.test.tsx`

**Interfaces:**
- Consumes: `FindingsTable`, `RuleLabel`, `SeverityBadge`, `groupByRule`, `groupByAttribute`, `filterFindings`, `FEED_LEVEL_KEY`, `SEVERITIES`, `severityColor`, `ruleTitle`.
- Produces: `FindingsExplorer({ findings, onOpenProduct })`; `FindingsTable` gains optional `onOpenProduct?: (productId: string) => void`.

- [ ] **Step 1: Add `onOpenProduct` + client-side sorting/pagination to `FindingsTable.tsx`**

Replace the whole file with:

```tsx
import { Group, Pagination, Select, Table, Text, UnstyledButton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useTable } from '@tanstack/react-table';
import {
  createPaginatedRowModel,
  createSortedRowModel,
  rowPaginationFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  tableFeatures,
} from '@tanstack/table-core';
import type { QualityFinding as ApiQualityFinding } from '../../api/types';
import { RuleLabel } from './findings/RuleLabel';
import { SeverityBadge } from './findings/SeverityBadge';

export type QualityFinding = ApiQualityFinding;

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric },
  rowPaginationFeature,
  paginatedRowModel: createPaginatedRowModel(),
});

type Props = {
  findings: QualityFinding[];
  onOpenProduct?: (productId: string) => void;
};

export function FindingsTable({ findings, onOpenProduct }: Props) {
  const { t } = useTranslation('monitoring');
  const table = useTable({
    features,
    columns: [
      { id: 'severity', header: t('columns.severity'), accessorFn: (row: QualityFinding) => row.severity },
      { id: 'code', header: t('columns.code'), accessorFn: (row: QualityFinding) => row.code },
      { id: 'field', header: t('columns.field'), accessorFn: (row: QualityFinding) => row.field ?? '' },
      { id: 'message', header: t('columns.message'), accessorFn: (row: QualityFinding) => row.message },
      { id: 'product_id', header: t('columns.productId'), accessorFn: (row: QualityFinding) => row.product_id },
    ],
    data: findings,
    getRowId: (row: QualityFinding, index: number) =>
      `${row.code}-${row.product_id}-${row.field ?? ''}-${index}`,
    initialState: { pagination: { pageIndex: 0, pageSize: 25 } },
    autoResetPageIndex: false,
    enableSortingRemoval: false,
  });

  const rows = table.getRowModel().rows;
  const { pageIndex, pageSize } = table.getState().pagination;
  const pageCount = Math.max(1, table.getPageCount());

  return (
    <div data-testid="findings-table">
      <Table striped>
        <Table.Thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <Table.Tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <Table.Th key={header.id}>
                  {header.column.getCanSort() ? (
                    <UnstyledButton
                      onClick={header.column.getToggleSortingHandler()}
                      style={{ cursor: 'pointer' }}
                    >
                      <Group gap={4} wrap="nowrap">
                        {header.column.columnDef.header as string}
                        {header.column.getIsSorted() === 'asc' && ' ▲'}
                        {header.column.getIsSorted() === 'desc' && ' ▼'}
                      </Group>
                    </UnstyledButton>
                  ) : (
                    (header.column.columnDef.header as string)
                  )}
                </Table.Th>
              ))}
            </Table.Tr>
          ))}
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => {
            const finding = row.original;
            return (
              <Table.Tr key={row.id} data-testid="finding-row">
                <Table.Td>
                  <SeverityBadge severity={finding.severity} />
                </Table.Td>
                <Table.Td>
                  <RuleLabel code={finding.code} />
                </Table.Td>
                <Table.Td>{finding.field}</Table.Td>
                <Table.Td>{finding.message}</Table.Td>
                <Table.Td>
                  {onOpenProduct && finding.product_id ? (
                    <UnstyledButton
                      onClick={() => onOpenProduct(finding.product_id)}
                      aria-label={t('findings.openProduct', { id: finding.product_id })}
                    >
                      <Text size="sm" c="blue">
                        {finding.product_id}
                      </Text>
                    </UnstyledButton>
                  ) : (
                    finding.product_id
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      <Group justify="space-between" mt="md" px="sm">
        <Text size="sm" c="dimmed">
          {t('findings.total', { count: findings.length })}
        </Text>
        <Group gap="xs">
          <Select
            value={String(pageSize)}
            onChange={(value) => {
              if (value) table.setPageSize(Number(value));
            }}
            data={['25', '50', '100'].map((value) => ({ value, label: value }))}
            size="xs"
            w={80}
            aria-label={t('findings.pageSize')}
          />
          <Pagination
            total={pageCount}
            value={pageIndex + 1}
            onChange={(page) => table.setPageIndex(page - 1)}
          />
        </Group>
      </Group>
    </div>
  );
}
```

Add the new i18n keys to both monitoring locales inside the existing `"findings"` object:

```json
"groupBy": "Group by",
"groupRule": "Rule",
"groupAttribute": "Attribute",
"groupFlat": "Flat",
"search": "Search",
"searchPlaceholder": "Message, product or field",
"ruleFilter": "Rule",
"rulePlaceholder": "All rules",
"feedLevel": "Feed level",
"showMore": "Show {{count}} more",
"openProduct": "Open product {{id}}",
"pageSize": "Rows per page"
```

German:

```json
"groupBy": "Gruppieren nach",
"groupRule": "Regel",
"groupAttribute": "Attribut",
"groupFlat": "Flach",
"search": "Suche",
"searchPlaceholder": "Meldung, Produkt oder Feld",
"ruleFilter": "Regel",
"rulePlaceholder": "Alle Regeln",
"feedLevel": "Feed-Ebene",
"showMore": "{{count}} weitere anzeigen",
"openProduct": "Produkt {{id}} öffnen",
"pageSize": "Zeilen pro Seite"
```

- [ ] **Step 2: Update `FindingsTable.test.tsx`**

Replace the whole file with:

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications } from '@mantine/notifications';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { FindingsTable, type QualityFinding } from './FindingsTable';

const findings: QualityFinding[] = [
  { severity: 'critical', code: 'gtin_mpn', field: 'gtin', message: 'Bad GTIN', product_id: 'p1', details: {} },
  { severity: 'warning', code: 'brand_required', field: 'brand', message: 'Missing brand', product_id: 'p2', details: {} },
];

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

beforeEach(() => {
  notifications.clean();
});

describe('FindingsTable', () => {
  it('renders one row per finding', () => {
    render(<FindingsTable findings={findings} />);
    expect(screen.getAllByTestId('finding-row')).toHaveLength(2);
  });

  it('renders localized severity and rule titles', () => {
    render(<FindingsTable findings={findings} />);
    expect(screen.getByText('Critical')).toBeInTheDocument();
    expect(screen.getByText('Identifier problem')).toBeInTheDocument();
    expect(screen.getByText('Missing brand')).toBeInTheDocument();
  });

  it('calls onOpenProduct when a product is clicked', async () => {
    const user = userEvent.setup();
    const onOpenProduct = vi.fn();
    render(<FindingsTable findings={findings} onOpenProduct={onOpenProduct} />);
    await user.click(screen.getByRole('button', { name: 'Open product p1' }));
    expect(onOpenProduct).toHaveBeenCalledWith('p1');
  });
});
```

- [ ] **Step 3: Run the FindingsTable test**

Run: `npm run test -- src/features/monitoring/FindingsTable.test.tsx`
Expected: PASS. If the table fails to render because `getRowModel` is not paginated, switch
`table.getRowModel().rows` to `table.getPaginationRowModel?.().rows ?? table.getRowModel().rows`
and re-run; the final code must use whichever compiles and passes.

- [ ] **Step 4: Write `FindingsExplorer.tsx`**

```tsx
import {
  Accordion,
  Badge,
  Button,
  Group,
  MultiSelect,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { QualityFinding } from '../../../api/types';
import { FindingsTable } from '../FindingsTable';
import {
  FEED_LEVEL_KEY,
  filterFindings,
  groupByAttribute,
  groupByRule,
  type FindingGroup,
} from './groupFindings';
import { RuleLabel } from './RuleLabel';
import { SeverityBadge } from './SeverityBadge';
import { ruleTitle } from './ruleCatalog';
import { SEVERITIES, severityColor } from './severity';

const GROUP_PREVIEW_SIZE = 20;

type GroupMode = 'rule' | 'attribute' | 'flat';

type Props = {
  findings: QualityFinding[];
  onOpenProduct: (productId: string) => void;
};

function groupLabel(key: string, mode: GroupMode, t: TFunction): string {
  if (mode === 'rule') return ruleTitle(key, t);
  return key === FEED_LEVEL_KEY ? t('findings.feedLevel') : key;
}

function GroupCounts({ group }: { group: FindingGroup }) {
  const { t } = useTranslation('monitoring');
  return (
    <Group gap="xs">
      {SEVERITIES.filter((severity) => group.counts[severity] > 0).map((severity) => (
        <Badge key={severity} size="sm" variant="light" color={severityColor(severity)}>
          {t(`severity.${severity}`)}: {group.counts[severity]}
        </Badge>
      ))}
    </Group>
  );
}

function GroupRows({ group, onOpenProduct }: { group: FindingGroup; onOpenProduct: (id: string) => void }) {
  const { t } = useTranslation('monitoring');
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? group.findings : group.findings.slice(0, GROUP_PREVIEW_SIZE);
  const hidden = group.findings.length - visible.length;

  return (
    <Stack gap="xs">
      <Table striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('columns.severity')}</Table.Th>
            <Table.Th>{t('columns.field')}</Table.Th>
            <Table.Th>{t('columns.message')}</Table.Th>
            <Table.Th>{t('columns.productId')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {visible.map((finding, index) => (
            <Table.Tr key={`${finding.product_id}-${finding.field ?? ''}-${index}`} data-testid="finding-row">
              <Table.Td>
                <SeverityBadge severity={finding.severity} />
              </Table.Td>
              <Table.Td>{finding.field ?? t('findings.feedLevel')}</Table.Td>
              <Table.Td>{finding.message}</Table.Td>
              <Table.Td>
                {finding.product_id ? (
                  <Button
                    variant="subtle"
                    size="xs"
                    onClick={() => onOpenProduct(finding.product_id)}
                    aria-label={t('findings.openProduct', { id: finding.product_id })}
                  >
                    {finding.product_id}
                  </Button>
                ) : (
                  <Text size="sm" c="dimmed">
                    —
                  </Text>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {hidden > 0 ? (
        <Button variant="subtle" size="xs" onClick={() => setExpanded(true)}>
          {t('findings.showMore', { count: hidden })}
        </Button>
      ) : null}
    </Stack>
  );
}

export function FindingsExplorer({ findings, onOpenProduct }: Props) {
  const { t } = useTranslation('monitoring');
  const [mode, setMode] = useState<GroupMode>('rule');
  const [search, setSearch] = useState('');
  const [severities, setSeverities] = useState<string[]>([]);
  const [rules, setRules] = useState<string[]>([]);

  const codes = [...new Set(findings.map((finding) => finding.code))];
  const filtered = filterFindings(findings, { severities, rules, search });
  const groups = mode === 'attribute' ? groupByAttribute(filtered) : groupByRule(filtered);

  return (
    <Stack gap="md">
      <Group align="flex-end">
        <SegmentedControl
          value={mode}
          onChange={(value) => setMode(value as GroupMode)}
          data={[
            { value: 'rule', label: t('findings.groupRule') },
            { value: 'attribute', label: t('findings.groupAttribute') },
            { value: 'flat', label: t('findings.groupFlat') },
          ]}
          aria-label={t('findings.groupBy')}
        />
        <TextInput
          label={t('findings.search')}
          placeholder={t('findings.searchPlaceholder')}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
        <MultiSelect
          label={t('findings.severityFilter')}
          data={SEVERITIES.map((severity) => ({
            value: severity,
            label: t(`severity.${severity}`),
          }))}
          value={severities}
          onChange={setSeverities}
          placeholder={t('findings.severityPlaceholder')}
          clearable
        />
        {mode !== 'rule' ? (
          <MultiSelect
            label={t('findings.ruleFilter')}
            data={codes.map((code) => ({ value: code, label: ruleTitle(code, t) }))}
            value={rules}
            onChange={setRules}
            placeholder={t('findings.rulePlaceholder')}
            clearable
          />
        ) : null}
      </Group>

      {filtered.length === 0 ? (
        <Text c="dimmed" data-testid="findings-empty">
          {t('findings.empty')}
        </Text>
      ) : mode === 'flat' ? (
        <FindingsTable findings={filtered} onOpenProduct={onOpenProduct} />
      ) : (
        <Accordion multiple variant="separated" data-testid="findings-groups">
          {groups.map((group) => (
            <Accordion.Item key={group.key} value={group.key}>
              <Accordion.Control>
                <Group justify="space-between" wrap="nowrap">
                  <Text fw={500}>
                    {mode === 'rule' ? <RuleLabel code={group.key} /> : groupLabel(group.key, mode, t)}
                  </Text>
                  <GroupCounts group={group} />
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <GroupRows group={group} onOpenProduct={onOpenProduct} />
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Stack>
  );
}
```

- [ ] **Step 5: Write `FindingsExplorer.test.tsx`**

```tsx
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import type { QualityFinding } from '../../../api/types';
import { FindingsExplorer } from './FindingsExplorer';

const findings: QualityFinding[] = [
  { severity: 'critical', code: 'gtin_mpn', field: 'gtin', message: 'Bad GTIN', product_id: 'p1', details: {} },
  { severity: 'warning', code: 'gtin_mpn', field: 'gtin', message: 'No GTIN', product_id: 'p2', details: {} },
  { severity: 'warning', code: 'volume_drop', field: null, message: 'Catalog dropped', product_id: '', details: {} },
];

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

describe('FindingsExplorer', () => {
  it('groups by rule and shows per-group counts', async () => {
    render(<FindingsExplorer findings={findings} onOpenProduct={() => undefined} />);
    const groups = await screen.findByTestId('findings-groups');
    expect(within(groups).getByText('Identifier problem')).toBeInTheDocument();
    expect(within(groups).getByText('Catalog volume drop')).toBeInTheDocument();
    expect(within(groups).getByText('Critical: 1')).toBeInTheDocument();
  });

  it('groups by attribute and buckets feed-level findings', async () => {
    const user = userEvent.setup();
    render(<FindingsExplorer findings={findings} onOpenProduct={() => undefined} />);
    await user.click(screen.getByRole('radio', { name: 'Attribute' }));
    expect(await screen.findByText('Feed level')).toBeInTheDocument();
  });

  it('filters by free text search', async () => {
    const user = userEvent.setup();
    render(<FindingsExplorer findings={findings} onOpenProduct={() => undefined} />);
    await user.type(screen.getByLabelText('Search'), 'dropped');
    const groups = await screen.findByTestId('findings-groups');
    expect(within(groups).queryByText('Identifier problem')).not.toBeInTheDocument();
    expect(within(groups).getByText('Catalog volume drop')).toBeInTheDocument();
  });

  it('shows the flat sortable table and opens a product', async () => {
    const user = userEvent.setup();
    const onOpenProduct = vi.fn();
    render(<FindingsExplorer findings={findings} onOpenProduct={onOpenProduct} />);
    await user.click(screen.getByRole('radio', { name: 'Flat' }));
    const table = await screen.findByTestId('findings-table');
    await user.click(within(table).getByRole('button', { name: 'Open product p1' }));
    expect(onOpenProduct).toHaveBeenCalledWith('p1');
  });

  it('shows an empty state when filters match nothing', async () => {
    const user = userEvent.setup();
    render(<FindingsExplorer findings={findings} onOpenProduct={() => undefined} />);
    await user.type(screen.getByLabelText('Search'), 'zzzz-no-match');
    expect(await screen.findByTestId('findings-empty')).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run the explorer tests**

Run: `npm run test -- src/features/monitoring`
Expected: PASS.

- [ ] **Step 7: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/features/monitoring
git commit -m "feat(findings): findings explorer with grouping, search, sort and pagination"
```

---

### Task 5: MonitoringFindingsPage rewrite, charts module move, product drill-down

**Files:**
- Modify: `frontend/src/features/monitoring/MonitoringFindingsPage.tsx`
- Move: `frontend/src/features/monitoring/QualityTrendChart.tsx` → `frontend/src/features/monitoring/findings/QualityTrendChart.tsx`
- Move: `frontend/src/features/monitoring/RuleDistributionChart.tsx` → `frontend/src/features/monitoring/findings/RuleDistributionChart.tsx`
- Modify: `frontend/src/features/monitoring/MonitoringFindingsPage.test.tsx`

**Interfaces:**
- Consumes: `useQualityFindings`, `useQualityHistory`, `FindingsSummary`, `FindingsExplorer`, `QualityTrendChart`, `RuleDistributionChart`, `ProductDrawer`.

- [ ] **Step 1: Move and update the charts**

Run: `git mv frontend/src/features/monitoring/QualityTrendChart.tsx frontend/src/features/monitoring/findings/QualityTrendChart.tsx`
and `git mv frontend/src/features/monitoring/RuleDistributionChart.tsx frontend/src/features/monitoring/findings/RuleDistributionChart.tsx`.

Replace `findings/QualityTrendChart.tsx` with:

```tsx
import { LineChart } from '@mantine/charts';
import dayjs from 'dayjs';
import type { QualityHistoryRow } from '../../../api/types';
import { chartColors } from '../../../components/dashboard/dashboardColors';

type Props = {
  rows: QualityHistoryRow[];
};

export function QualityTrendChart({ rows }: Props) {
  if (rows.length === 0) return null;
  return (
    <LineChart
      h={280}
      data={rows.map((r) => ({
        date: dayjs(r.started_at).format('MM-DD HH:mm'),
        critical: r.critical,
        warning: r.warning,
        info: r.info,
      }))}
      dataKey="date"
      series={[
        { name: 'critical', color: chartColors.error },
        { name: 'warning', color: chartColors.warning },
        { name: 'info', color: chartColors.info },
      ]}
      withLegend
    />
  );
}
```

Replace `findings/RuleDistributionChart.tsx` with:

```tsx
import { BarChart } from '@mantine/charts';
import { useTranslation } from 'react-i18next';
import type { QualityFinding } from '../../../api/types';
import { chartColors } from '../../../components/dashboard/dashboardColors';
import { ruleTitle } from './ruleCatalog';

type Props = {
  findings: QualityFinding[];
};

export function RuleDistributionChart({ findings }: Props) {
  const { t } = useTranslation('monitoring');
  const byCode = new Map<string, number>();
  for (const finding of findings) byCode.set(finding.code, (byCode.get(finding.code) ?? 0) + 1);
  const data = [...byCode.entries()]
    .map(([code, count]) => ({ name: ruleTitle(code, t), count }))
    .sort((a, b) => b.count - a.count);
  if (data.length === 0) return null;
  return (
    <BarChart
      orientation="horizontal"
      h={Math.max(160, data.length * 28)}
      data={data}
      dataKey="name"
      series={[{ name: 'count', color: chartColors.passed }]}
      tickLine="y"
    />
  );
}
```

- [ ] **Step 2: Rewrite `MonitoringFindingsPage.tsx`**

```tsx
import { Stack } from '@mantine/core';
import { useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { useQualityFindings, useQualityHistory } from '../../api/hooks';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { ProductDrawer } from '../products/ProductDrawer';
import { FindingsExplorer } from './findings/FindingsExplorer';
import { FindingsSummary } from './findings/FindingsSummary';
import { QualityTrendChart } from './findings/QualityTrendChart';
import { RuleDistributionChart } from './findings/RuleDistributionChart';

export function MonitoringFindingsPage() {
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const { data, isPending, isError, refetch } = useQualityFindings(id, true);
  const { data: historyData } = useQualityHistory(id);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);

  const findings = useMemo(() => data?.findings ?? [], [data]);

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={() => void refetch()} />;

  return (
    <Stack gap="md" pt="md">
      <FindingsSummary
        counts={data?.counts ?? { critical: 0, warning: 0, info: 0 }}
        delta={data?.delta ?? { fixed: 0, new: 0, remaining: 0 }}
        hasPrevious={Boolean(data?.has_previous)}
        productCount={data?.product_count ?? 0}
      />
      <QualityTrendChart rows={historyData?.rows ?? []} />
      <RuleDistributionChart findings={findings} />
      <FindingsExplorer findings={findings} onOpenProduct={setSelectedProductId} />
      <ProductDrawer
        feedSourceId={id}
        productId={selectedProductId}
        onClose={() => setSelectedProductId(null)}
      />
    </Stack>
  );
}
```

- [ ] **Step 3: Rewrite `MonitoringFindingsPage.test.tsx`**

```tsx
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { notifications, Notifications } from '@mantine/notifications';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { MonitoringFindingsPage } from './MonitoringFindingsPage';
import { queryClient } from '../../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const findings = {
  ingestion_run_id: 1,
  counts: { critical: 1, warning: 1, info: 0 },
  product_count: 2,
  delta: { fixed: 0, new: 0, remaining: 0 },
  has_previous: false,
  prev_counts: null,
  findings: [
    { severity: 'critical', code: 'gtin_mpn', field: 'gtin', message: 'Bad GTIN', product_id: 'p1', details: {} },
    { severity: 'warning', code: 'brand_required', field: 'brand', message: 'Missing brand', product_id: 'p2', details: {} },
  ],
};

const historyRows = [
  {
    id: 1,
    started_at: '2026-09-01T10:00:00',
    product_count: 2,
    critical: 1,
    warning: 1,
    info: 0,
    fixed: 0,
    new: 0,
    remaining: 0,
  },
];

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
});

function renderAt() {
  return render(
    <MemoryRouter initialEntries={['/clients/1/feeds/1/monitoring/findings']}>
      <Notifications position="top-right" limit={1} />
      <Routes>
        <Route path="/clients/:clientId/feeds/:feedSourceId/monitoring/findings" element={<MonitoringFindingsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function stubEndpoints(payload: unknown) {
  stubFetch((url) => {
    if (url === '/feed-sources/1/quality-findings') return jsonResponse(payload);
    if (url.startsWith('/feed-sources/1/quality-history')) return jsonResponse({ rows: historyRows });
    if (url.startsWith('/feed-sources/1/products/')) {
      return jsonResponse({
        product_id: 'p1',
        status: 'active',
        content_hash: 'h',
        config_hash: 'c',
        last_seen_at: '2026-09-01T10:00:00',
        removed_at: null,
        raw_data: { title: 'Product 1' },
        processed_data: null,
        excluded: false,
      });
    }
    return jsonResponse({});
  });
}

describe('MonitoringFindingsPage', () => {
  it('renders summary cards, of-products line, trend and grouped findings', async () => {
    stubEndpoints(findings);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-groups')).toBeInTheDocument());
    expect(screen.getByTestId('card-critical')).toHaveTextContent('1');
    expect(screen.getByText(/of 2 products/i)).toBeInTheDocument();
    const groups = screen.getByTestId('findings-groups');
    expect(within(groups).getByText('Identifier problem')).toBeInTheDocument();
    expect(within(groups).getByText('Missing brand')).toBeInTheDocument();
  });

  it('renders delta badges only when a previous run exists', async () => {
    stubEndpoints({
      ...findings,
      has_previous: true,
      delta: { fixed: 2, new: 1, remaining: 3 },
      prev_counts: { critical: 3, warning: 0, info: 0 },
    });
    renderAt();
    await waitFor(() => expect(screen.getAllByTestId('delta-fixed').length).toBeGreaterThan(0));
    expect(screen.getAllByTestId('delta-fixed')[0]).toHaveTextContent('2');
    expect(screen.getAllByTestId('delta-new')[0]).toHaveTextContent('1');
  });

  it('filters findings by severity', async () => {
    const user = userEvent.setup();
    stubEndpoints(findings);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-groups')).toBeInTheDocument());
    expect(screen.getAllByTestId('finding-row')).toHaveLength(2);
    await user.click(screen.getByRole('combobox', { name: /severity/i }));
    await user.click(screen.getByRole('option', { name: 'Critical' }));
    expect(screen.getAllByTestId('finding-row')).toHaveLength(1);
  });

  it('opens the product drawer from a finding', async () => {
    const user = userEvent.setup();
    stubEndpoints(findings);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-groups')).toBeInTheDocument());
    await user.click(screen.getAllByRole('button', { name: /open product/i })[0]);
    expect(await screen.findByText('Product Details')).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the page tests**

Run: `npm run test -- src/features/monitoring/MonitoringFindingsPage.test.tsx`
Expected: PASS. (`Product Details` is the `drawerTitle` in `frontend/public/locales/en/products.json`.)

- [ ] **Step 5: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/features/monitoring
git commit -m "feat(findings): page composes explorer, module charts, product drill-down"
```

---

### Task 6: Backend — per-feed quality counts in /dashboard/summary

**Files:**
- Modify: `backend/app/routes/dashboard.py:100-110`
- Modify: `backend/tests/test_dashboard_api.py`
- Modify: `backend/docs/api.md` (the `GET /dashboard/summary` bullet)

**Interfaces:**
- Produces: each feed dict in `clients[].feed_sources[]` additionally carries
  `quality: {critical: int, warning: int, info: int}` from the latest `ExportRun` (zeros when none).

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_dashboard_api.py`, update `_add_export_run` to accept counts:

```python
async def _add_export_run(
    factory, feed_id, status, product_count=1, critical=0, warning=0, info=0
):
    async with factory() as session, session.begin():
        session.add(
            ExportRun(
                feed_source_id=feed_id,
                status=status,
                product_count=product_count,
                critical_finding_count=critical,
                warning_finding_count=warning,
                info_finding_count=info,
                started_at=datetime.now(timezone.utc),
            )
        )
```

Append a new test:

```python
async def test_summary_includes_per_feed_quality_counts(app_factory):
    _app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_a = await _make_feed(factory, client, "Acme")
    _client_id_b, feed_b = await _make_feed(factory, client, "Zeta")

    await _add_export_run(factory, feed_a, "completed", critical=3, warning=2, info=1)
    await _add_export_run(factory, feed_b, "completed")

    body = (await client.get("/dashboard/summary")).json()
    by_name = {c["name"]: c for c in body["clients"]}
    assert by_name["Acme"]["feed_sources"][0]["quality"] == {"critical": 3, "warning": 2, "info": 1}
    assert by_name["Zeta"]["feed_sources"][0]["quality"] == {"critical": 0, "warning": 0, "info": 0}
```

Also extend `test_summary_feed_without_runs_has_null_last_fields` with:

```python
    assert feed["quality"] == {"critical": 0, "warning": 0, "info": 0}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_dashboard_api.py -k quality_counts -v`
Expected: FAIL with `KeyError: 'quality'`.

- [ ] **Step 3: Implement**

In `backend/app/routes/dashboard.py`, extend the feed dict inside the `for feed in feeds:` loop:

```python
        feeds_by_client.setdefault(feed.client_id, []).append({
            "id": feed.id,
            "client_id": feed.client_id,
            "name": feed.name,
            "source_format": feed.source_format,
            "item_count": item_counts.get(feed.id, 0),
            "last_export_at": last_export.started_at.isoformat() if last_export else None,
            "last_export_status": last_export.status if last_export else None,
            "last_run_at": last_run.started_at.isoformat() if last_run else None,
            "last_run_status": last_run.status if last_run else None,
            "quality": {
                "critical": last_export.critical_finding_count if last_export else 0,
                "warning": last_export.warning_finding_count if last_export else 0,
                "info": last_export.info_finding_count if last_export else 0,
            },
        })
```

- [ ] **Step 4: Run the dashboard tests**

Run: `cd backend && uv run pytest tests/test_dashboard_api.py -v`
Expected: PASS.

- [ ] **Step 5: Update `backend/docs/api.md`**

Find the `GET /dashboard/summary` bullet (line ~138) and add to the `feed_sources` description:
`recent_runs` is unchanged; each `feed_sources[]` entry additionally carries `quality: {critical, warning, info}` read from that feed's latest export run (zeros when the feed has no export run).

- [ ] **Step 6: Gates and commit**

```bash
cd backend
uv run ruff check . ../plugins
uv run mypy .
uv run pytest tests/test_dashboard_api.py
cd ..
git add backend/app/routes/dashboard.py backend/tests/test_dashboard_api.py backend/docs/api.md
git commit -m "feat(dashboard): per-feed quality counts in summary"
```

---

### Task 7: Frontend unification — feed-card badge and feed-dashboard cross-link

**Files:**
- Modify: `frontend/src/api/types.ts` (`FeedSourceSummary`)
- Modify: `frontend/src/features/dashboard/FeedSourceCard.tsx`
- Modify: `frontend/src/features/feedDashboard/FeedDashboardPage.tsx`
- Modify: `frontend/public/locales/en/dashboard.json`, `de/dashboard.json`
- Modify: `frontend/public/locales/en/feedDashboard.json`, `de/feedDashboard.json`
- Modify: `frontend/src/features/dashboard/DashboardPage.test.tsx`

**Interfaces:**
- Consumes: `SeverityBadge` is not used here; the card uses a plain Mantine `Badge` driven by `feed.quality`.

- [ ] **Step 1: Add `quality` to `FeedSourceSummary`**

In `frontend/src/api/types.ts`:

```ts
export type FeedSourceSummary = {
  id: number;
  client_id: number;
  name: string;
  source_format: string;
  item_count: number;
  last_export_at: string | null;
  last_export_status: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
  quality: { critical: number; warning: number; info: number };
};
```

- [ ] **Step 2: Add the quality badge to `FeedSourceCard.tsx`**

Add after `const numberFormat = ...`:

```tsx
  const qualityBadge =
    feed.quality.critical > 0
      ? { color: 'red', count: feed.quality.critical }
      : feed.quality.warning > 0
        ? { color: 'yellow', count: feed.quality.warning }
        : null;
```

Inside the header `Group gap="xs" wrap="nowrap"` (before the settings `ActionIcon`), insert:

```tsx
          {qualityBadge ? (
            <Badge
              color={qualityBadge.color}
              variant="light"
              data-testid={`feed-quality-badge-${feed.id}`}
              style={{ cursor: 'pointer' }}
              aria-label={t('qualityBadge', { count: qualityBadge.count })}
              onClick={(event) => {
                event.stopPropagation();
                navigate(`/clients/${clientId}/feeds/${feed.id}/monitoring/findings`);
              }}
            >
              {t('qualityBadge', { count: qualityBadge.count })}
            </Badge>
          ) : null}
```

- [ ] **Step 3: Add the badge label to both dashboard locales**

Add a top-level key (after `"deleteFeed"`):

English: `"qualityBadge": "{{count}} findings",`
German: `"qualityBadge": "{{count}} Befunde",`

- [ ] **Step 4: Add the feed-dashboard cross-link**

In `FeedDashboardPage.tsx`, inside the quality `ChartCard` after the `DonutChart`, add:

```tsx
        <Group justify="center" mt="sm">
          <Anchor component={Link} to={`/clients/${clientId}/feeds/${id}/monitoring/findings`} size="sm">
            {t('viewFindings')}
          </Anchor>
        </Group>
```

`Group`, `Anchor` and `Link` are already imported. Add the key to both `feedDashboard` locales (after `"copyExportUrl"`):
English `"viewFindings": "View findings",` German `"viewFindings": "Befunde anzeigen",`

- [ ] **Step 5: Update `DashboardPage.test.tsx` fixtures**

Add `quality` to each of the three feed objects in the `summary` fixture:
- feed `id: 2`: `quality: { critical: 3, warning: 1, info: 0 },`
- feed `id: 5`: `quality: { critical: 0, warning: 0, info: 0 },`
- feed `id: 4`: `quality: { critical: 0, warning: 0, info: 0 },`

Add a test inside the existing describe block:

```tsx
  it('shows a quality badge on feeds with findings', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(summary);
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.getByTestId('feed-quality-badge-2')).toHaveTextContent('3 findings');
    expect(screen.queryByTestId('feed-quality-badge-5')).not.toBeInTheDocument();
  });
```

`DashboardPage.test.tsx` already imports `App`, `render`, `stubFetch` and renders `<App />` inside
`describe('DashboardPage')`, so place this test inside that describe block.

- [ ] **Step 6: Run the dashboard and feed-dashboard tests**

Run: `npm run test -- src/features/dashboard src/features/feedDashboard`
Expected: PASS.

- [ ] **Step 7: Typecheck and commit**

```bash
npm run typecheck
git add frontend/src/api/types.ts frontend/src/features/dashboard frontend/src/features/feedDashboard frontend/public/locales
git commit -m "feat(dashboard): quality badge on feed cards and findings cross-link"
```

---

### Task 8: Docs and full gates

**Files:**
- Modify: `frontend/docs/architecture.md` (Quality Dashboard section)
- Modify: `docs/decisions.md` (dated cycle entry)

- [ ] **Step 1: Update `frontend/docs/architecture.md`**

Replace the "Quality Dashboard (`src/features/monitoring/`)" section body with a description of the
new module and surfaces, e.g.:

```markdown
### Quality Findings (`src/features/monitoring/` + `src/features/monitoring/findings/`)
- `findings/` — the shared findings domain module: `severity.ts` (order, colors, labels), `ruleCatalog.ts`
  (rule-code → title/description/remediation), `groupFindings.ts` (group/count/filter helpers),
  `SeverityBadge`/`RuleLabel`/`FindingsSummary`, `FindingsExplorer` and the `QualityTrendChart`/
  `RuleDistributionChart` charts.
- `MonitoringFindingsPage` — composes `FindingsSummary`, both charts, `FindingsExplorer` (group by rule
  or GMC attribute, collapsible groups, free-text search, severity/rule filters, flat sortable +
  paginated table) and a `ProductDrawer` for finding → product drill-down.
- `FindingsTable` — shared flat findings table (sortable, paginated, optional product drill-down);
  also used by the dry-run results.
- `MonitoringDryRunPage` — trigger dry run, show `DryRunResults` (reuses `FindingsTable`).
- The fleet dashboard feed cards show a `quality` badge (critical, else warning) from
  `/dashboard/summary` and link into the feed's findings page; the feed dashboard's quality chart
  links there too.
```

- [ ] **Step 2: Add the decisions entry**

Append to `docs/decisions.md`:

```markdown
### 2026-09-16 — Findings & quality surfaces UX

**Topic:** Making the quality findings actionable (grouping, rule guidance, product drill-down, table
ergonomics) and unifying the quality surfaces behind one module.

**Decision:**
- New shared module `frontend/src/features/monitoring/findings/` owns severity constants, the rule
  catalog (13 rule codes + unknown fallback, i18n-backed), grouping/filtering helpers, the shared
  badges/summary, the explorer and both charts. `QualitySummaryCards` is deleted; `FindingsTable`
  consumes the shared severity badge and rule label so the dry-run results inherit them.
- Grouping, counting, search, sorting and pagination are client-side over the existing
  `quality-findings` response (which already returns every finding). Server-side grouped/paginated
  endpoints are deferred until a feed produces findings in the thousands.
- `FindingsExplorer` groups by rule or GMC attribute (findings without a field bucket into a
  "feed level" group); the flat mode is a sortable, paginated table.
- Product drill-down reuses the existing `useProductDetail` hook and `ProductDrawer`; no new route.
- `GET /dashboard/summary` feed entries gain `quality: {critical, warning, info}` from the feed's
  latest export run (zeros when none). No migration, no new endpoint, no extra query. Dashboard feed
  cards show a critical-else-warning badge linking to the findings page; the feed dashboard's quality
  chart links there as well.
- Guest rule guidance lives in i18n (`rules.*` in `monitoring.json`), since the rule set is fixed and
  owned by the backend QC rules. A frontend test reads `backend/app/qc/{rules,ai_rules}.py` and fails
  if a backend `rule_id` has no catalog entry.

**Rationale:** The findings page showed raw rule codes with no guidance and no way to reach the
product behind a finding, and severity styling was duplicated across four surfaces. A single module
removes the drift and delivers the ergonomics without new dependencies or schema changes. The
per-feed quality counts reuse the export runs the summary already loads, so the badge is free.
```

- [ ] **Step 3: Run the full frontend gates**

```bash
cd frontend
npm run typecheck
npm run test
npm run build
```

Expected: typecheck clean, all tests pass, production build succeeds.

- [ ] **Step 4: Run the full backend gates**

```bash
cd backend
uv run ruff check . ../plugins
uv run mypy .
uv run alembic check
uv run pytest --report-log=.report.jsonl tests/test_dashboard_api.py
```

Expected: ruff exit 0, mypy exit 0, alembic check reports no pending changes, dashboard tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/docs/architecture.md docs/decisions.md
git commit -m "docs: findings & quality surfaces cycle notes"
```

---

## Self-Review

- **Spec coverage:** shared severity + rule catalog (Task 1); grouping/filtering (Task 2); remediation/description guidance (Tasks 1, 3, 4); product drill-down (Tasks 4, 5); table ergonomics (Task 4); feed-dashboard cross-link and feed-card badge (Task 7); backend summary addition (Task 6); i18n en+de (Tasks 1, 4, 7); docs (Tasks 6, 8); client-side ceiling recorded in the spec and decisions entry. Dry-run inherits shared badges via `FindingsTable` (Task 3). All covered.
- **Placeholder scan:** no TBD/TODO; every step carries runnable code or an exact command.
- **Type consistency:** `QualityFinding` (api + FindingsTable re-export), `FindingGroup`/`SeverityCounts`/`FEED_LEVEL_KEY`, `ruleInfo`/`ruleTitle`, `severityColor`/`severityRank`, `FindingsSummary`/`FindingsExplorer`/`SeverityBadge`/`RuleLabel`/`FindingsTable` signatures are used consistently across tasks 1–7.
- **Known verification seam:** Task 4 Step 3 calls out the one v9 API detail (`getRowModel` vs `getPaginationRowModel`) to confirm at runtime.
