import { describe, expect, it } from 'vitest';
import { computeShadowing } from './shadowing';
import type { ScopedSlotRule } from './scopeMerge';

function rule(
  over: Partial<ScopedSlotRule> & { id: string; name: string; targetSlot: string },
): ScopedSlotRule {
  return {
    origin: 'global',
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

  it('same-named rules still shadow: claims are keyed by id, not name', () => {
    const rules = [
      rule({ id: 'a', name: 'X', targetSlot: 'custom_label_0' }),
      rule({ id: 'b', name: 'X', targetSlot: 'custom_label_0' }),
    ];
    const result = computeShadowing(rules, { a: '1', b: '1,2' });
    expect([...result.b.shadowed]).toEqual(['1']);
    expect(result.b.shadowedBy.get('1')).toBe('X');
    expect(result.a.shadowed.size).toBe(0);
  });

  it('a second all-mode rule is shadowed by the first all-mode rule', () => {
    const rules = [
      rule({ id: 'm1', name: 'Catch', targetSlot: 'custom_label_0', matchMode: 'all' }),
      rule({ id: 'm2', name: 'Catch', targetSlot: 'custom_label_0', matchMode: 'all' }),
      rule({ id: 'b', name: 'Later', targetSlot: 'custom_label_0' }),
    ];
    const result = computeShadowing(rules, { m2: '9', b: '9' });
    expect(result.m2.shadowedBy.get('9')).toBe('Catch');
    expect(result.b.shadowedBy.get('9')).toBe('Catch');
  });
});
