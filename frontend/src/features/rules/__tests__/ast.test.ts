import { describe, expect, it } from 'vitest';
import {
  enforcePinning,
  newRule,
  normalizeConfig,
  rulesEqual,
  sortRulesPinned,
  type Rule,
} from '../../../../../plugins/core/rules/frontend/ast';

describe('newRule', () => {
  it('creates a rule with defaults', () => {
    expect(newRule('My rule')).toEqual({
      id: expect.any(String),
      name: 'My rule',
      isMasterRule: false,
      isActive: true,
      when: { op: 'all' },
      then: [],
    });
  });

  it('generates unique ids', () => {
    expect(newRule('a').id).not.toEqual(newRule('b').id);
  });
});

describe('normalizeConfig', () => {
  it('defaults empty values', () => {
    expect(normalizeConfig(undefined)).toEqual({ rules: [] });
    expect(normalizeConfig({})).toEqual({ rules: [] });
    expect(normalizeConfig({ rules: null })).toEqual({ rules: [] });
  });

  it('keeps valid rules and drops invalid entries', () => {
    const valid = {
      id: 'r1',
      name: 'ok',
      isMasterRule: true,
      isActive: false,
      when: { op: 'equals', field: 'title', arg: 'x' },
      then: [{ op: 'set', field: 'condition', value: 'new' }],
    };
    const out = normalizeConfig({ rules: [valid, { id: 'bad' }, 'junk'] });
    expect(out.rules).toHaveLength(1);
    expect(out.rules[0]).toEqual(valid);
  });

  it('coerces unknown op codes to safe defaults', () => {
    const out = normalizeConfig({
      rules: [{
        id: 'r1', name: 'n', when: { op: 'nope' }, then: [{ op: 'zap', field: 'f' }],
      }],
    });
    expect(out.rules[0].when.op).toBe('all');
    expect(out.rules[0].then).toEqual([]);
  });

  it('fills defaults for partial rules', () => {
    const out = normalizeConfig({ rules: [{ id: 'r1', name: 'n' }] });
    expect(out.rules[0].isMasterRule).toBe(false);
    expect(out.rules[0].isActive).toBe(true);
    expect(out.rules[0].when).toEqual({ op: 'all' });
    expect(out.rules[0].then).toEqual([]);
  });
});

describe('rulesEqual', () => {
  it('deep-compares config documents', () => {
    const a = normalizeConfig({ rules: [{ id: 'r1', name: 'n' }] });
    expect(rulesEqual(a, a)).toBe(true);
    const b = normalizeConfig({ rules: [{ id: 'r1', name: 'm' }] });
    expect(rulesEqual(a, b)).toBe(false);
  });
});

describe('pinning', () => {
  const master = (id: string): Rule => ({ ...newRule(id), id, isMasterRule: true });
  const normal = (id: string): Rule => ({ ...newRule(id), id });

  it('sortRulesPinned puts masters first preserving relative order', () => {
    const out = sortRulesPinned([normal('a'), master('m1'), normal('b'), master('m2')]);
    expect(out.map((r) => r.id)).toEqual(['m1', 'm2', 'a', 'b']);
  });

  it('enforcePinning repairs a broken order', () => {
    const broken = [normal('a'), master('m1'), normal('b')];
    const out = enforcePinning(broken);
    expect(out.map((r) => r.id)).toEqual(['m1', 'a', 'b']);
  });

  it('enforcePinning is idempotent', () => {
    const fixed = enforcePinning([master('m1'), normal('a'), master('m2'), normal('b')]);
    expect(enforcePinning(fixed)).toEqual(fixed);
  });
});
