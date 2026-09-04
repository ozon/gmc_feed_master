import { describe, expect, it } from 'vitest';
import type { Rule } from '../../../../../plugins/core/rules/frontend/ast';
import { applyDragEnd } from '../dndUtils';

describe('applyDragEnd (rules)', () => {
  const rules: Rule[] = [
    { id: 'm1', name: 'M1', isMasterRule: true, isActive: true, when: { op: 'all' }, then: [] },
    { id: 'a', name: 'A', isMasterRule: false, isActive: true, when: { op: 'all' }, then: [] },
    { id: 'b', name: 'B', isMasterRule: false, isActive: true, when: { op: 'all' }, then: [] },
  ];

  it('reorders within the same partition', () => {
    const out = applyDragEnd(rules, { active: 'b', over: 'a' });
    expect(out?.map((r) => r.id)).toEqual(['m1', 'b', 'a']);
  });

  it('blocks non-master from crossing above masters', () => {
    const out = applyDragEnd(rules, { active: 'a', over: 'm1' });
    expect(out?.map((r) => r.id)).toEqual(['m1', 'a', 'b']);
  });

  it('returns null when nothing changed', () => {
    expect(applyDragEnd(rules, { active: 'a', over: 'a' })).toBeNull();
  });

  it('returns null for unknown ids', () => {
    expect(applyDragEnd(rules, { active: 'zz', over: 'a' })).toBeNull();
  });
});
