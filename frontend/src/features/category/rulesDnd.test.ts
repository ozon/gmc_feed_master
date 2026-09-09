import { describe, expect, it } from 'vitest';
import { applyRulesDragEnd } from './rulesDnd';
import type { ScopedCategoryRule } from './types';

const rule = (id: string): ScopedCategoryRule => ({
  id, source_field: 'product_type', operator: 'eq', source_value: 'x',
  taxonomy_id: '1', origin: 'client',
});

describe('applyRulesDragEnd', () => {
  it('reorders within the list', () => {
    const rules = [rule('a'), rule('b'), rule('c')];
    expect(applyRulesDragEnd(rules, 'c', 0).map((r) => r.id)).toEqual(['c', 'a', 'b']);
  });
  it('returns the same array when active or over is missing', () => {
    const rules = [rule('a'), rule('b')];
    expect(applyRulesDragEnd(rules, null, 0)).toBe(rules);
    expect(applyRulesDragEnd(rules, 'a', null)).toBe(rules);
    expect(applyRulesDragEnd(rules, 'zzz', 0)).toBe(rules);
  });
  it('does not mutate the input', () => {
    const rules = [rule('a'), rule('b')];
    applyRulesDragEnd(rules, 'b', 0);
    expect(rules.map((r) => r.id)).toEqual(['a', 'b']);
  });
});
