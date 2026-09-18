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
  finding({
    severity: 'critical',
    code: 'gtin_mpn',
    field: 'gtin',
    product_id: 'p1',
    message: 'bad gtin',
  }),
  finding({
    severity: 'warning',
    code: 'gtin_mpn',
    field: 'gtin',
    product_id: 'p2',
    message: 'no gtin',
  }),
  finding({
    severity: 'info',
    code: 'image_requirements',
    field: null,
    product_id: '',
    message: 'image small',
  }),
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
