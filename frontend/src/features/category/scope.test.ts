import { describe, expect, it } from 'vitest';
import { editableTier, mergeRules } from './scope';
import type { CategoryRule } from './types';

const g1: CategoryRule = {
  id: 'g1', source_field: 'product_type', operator: 'eq',
  source_value: 'Shoes', taxonomy_id: '166',
};
const g2: CategoryRule = {
  id: 'g2', source_field: 'product_type', operator: 'eq',
  source_value: 'Boots', taxonomy_id: '53',
};

describe('editableTier', () => {
  it('client scope when clientId present', () => {
    expect(editableTier({ clientId: 1 })).toBe('client');
  });
  it('global scope otherwise', () => {
    expect(editableTier({})).toBe('global');
    expect(editableTier({ feedSourceId: 3 })).toBe('global');
  });
});

describe('mergeRules', () => {
  it('client overrides same id in place, appends unseen', () => {
    const client: CategoryRule[] = [
      { ...g1, taxonomy_id: '999' },
      { id: 'c1', source_field: 'product_type', operator: 'ne', source_value: 'Socks', taxonomy_id: '166' },
    ];
    const merged = mergeRules([g1, g2], client);
    expect(merged.map((r) => [r.id, r.origin])).toEqual([
      ['g1', 'client'],
      ['g2', 'global'],
      ['c1', 'client'],
    ]);
    expect(merged[0].taxonomy_id).toBe('999');
  });
  it('empty tiers', () => {
    expect(mergeRules([], [])).toEqual([]);
    expect(mergeRules([g1], []).map((r) => r.origin)).toEqual(['global']);
  });
});
