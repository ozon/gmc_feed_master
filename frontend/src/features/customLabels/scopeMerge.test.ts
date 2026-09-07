import { describe, expect, it } from 'vitest';
import type { PluginScope } from '../../api/hooks';
import {
  configTierChain, currentDataTier, dataTierChain, editableConfigTier,
  groupBySlot, mergeSlotIds, mergeSlotRules, type SlotRule,
} from './scopeMerge';

// Shared equivalence fixture — keep in lockstep with
// backend/tests/test_config_merge.py (TestUnionByKey) and
// backend/tests/test_config_bundle.py (spec §1.2 gate).
const GLOBAL_RULES: SlotRule[] = [
  { id: 'g1', name: 'Global Mid', isActive: true, targetSlot: 'custom_label_1',
    matchField: 'id', valueTemplate: '{brand} - Mid', fallbackTemplate: '' },
  { id: 'g2', name: 'Global Top', isActive: true, targetSlot: 'custom_label_0',
    matchField: 'id', valueTemplate: '{brand} - Top', fallbackTemplate: '' },
];
const CLIENT_RULES: SlotRule[] = [
  { id: 'g1', name: 'Client Mid', isActive: true, targetSlot: 'custom_label_1',
    matchField: 'brand', valueTemplate: '{brand} - Client', fallbackTemplate: '' },
  { id: 'c2', name: 'Client Only', isActive: true, targetSlot: 'custom_label_0',
    matchField: 'id', valueTemplate: '{brand} - ClientOnly', fallbackTemplate: '' },
  { id: 'c3', name: 'Same Slot As G1', isActive: true, targetSlot: 'custom_label_1',
    matchField: 'id', valueTemplate: '{brand} - C3', fallbackTemplate: '' },
];

describe('mergeSlotRules (spec §1.2 gate)', () => {
  it('unions by id: client content wins, global positions first, client-only appended', () => {
    const merged = mergeSlotRules([
      { tier: 'global', rules: GLOBAL_RULES },
      { tier: 'client', rules: CLIENT_RULES },
    ]);
    expect(merged.map((r) => r.id)).toEqual(['g1', 'g2', 'c2', 'c3']);
    expect(merged.map((r) => r.name)).toEqual([
      'Client Mid', 'Global Top', 'Client Only', 'Same Slot As G1',
    ]);
    expect(merged.map((r) => r.origin)).toEqual([
      'client', 'global', 'client', 'client',
    ]);
  });

  it('per-slot winning order matches the backend (first match wins)', () => {
    const merged = mergeSlotRules([
      { tier: 'global', rules: GLOBAL_RULES },
      { tier: 'client', rules: CLIENT_RULES },
    ]);
    expect(groupBySlot(merged)).toEqual({
      custom_label_1: ['g1', 'c3'],
      custom_label_0: ['g2', 'c2'],
    });
  });

  it('client-only chain extends global without overrides', () => {
    const merged = mergeSlotRules([
      { tier: 'global', rules: GLOBAL_RULES },
      { tier: 'client', rules: [CLIENT_RULES[1]] },
    ]);
    expect(merged.map((r) => r.id)).toEqual(['g1', 'g2', 'c2']);
  });
});

describe('mergeSlotIds', () => {
  it('client-only values are inherited, current-tier values are not', () => {
    const merged = mergeSlotIds([
      { tier: 'client', ids: { r1: 'a', r2: 'x' } },
      { tier: 'feed_source', ids: { r2: 'y' } },
    ]);
    expect(merged).toEqual({
      r1: { value: 'a', inherited: true, sourceTier: 'client' },
      r2: { value: 'y', inherited: false, sourceTier: 'feed_source' },
    });
  });

  it('single-tier chain has no inherited values', () => {
    const merged = mergeSlotIds([{ tier: 'client', ids: { r1: 'a' } }]);
    expect(merged).toEqual({
      r1: { value: 'a', inherited: false, sourceTier: 'client' },
    });
  });
});

describe('tier chains', () => {
  it('config chain: global page -> global only', () => {
    const scope: PluginScope = {};
    expect(configTierChain(scope, {})).toEqual([
      { tier: 'global', scope: {} },
    ]);
    expect(editableConfigTier(scope)).toBe('global');
  });

  it('config chain: client page -> global + client, editable client', () => {
    const scope: PluginScope = { clientId: 7 };
    expect(configTierChain(scope, { clientId: '7' })).toEqual([
      { tier: 'global', scope: {} },
      { tier: 'client', scope: { clientId: 7 } },
    ]);
    expect(editableConfigTier(scope)).toBe('client');
  });

  it('config chain: feed page -> global + client ancestor, read-only', () => {
    const scope: PluginScope = { feedSourceId: 3 };
    expect(configTierChain(scope, { clientId: '7' })).toEqual([
      { tier: 'global', scope: {} },
      { tier: 'client', scope: { clientId: 7 } },
    ]);
    expect(editableConfigTier(scope)).toBe(null);
  });

  it('data chain: global page -> empty (global not declared)', () => {
    expect(dataTierChain({}, {})).toEqual([]);
    expect(currentDataTier({})).toBe(null);
  });

  it('data chain: client page -> client only', () => {
    expect(dataTierChain({ clientId: 7 }, { clientId: '7' })).toEqual([
      { tier: 'client', scope: { clientId: 7 } },
    ]);
    expect(currentDataTier({ clientId: 7 })).toBe('client');
  });

  it('data chain: feed page -> client ancestor + feed current', () => {
    expect(dataTierChain({ feedSourceId: 3 }, { clientId: '7' })).toEqual([
      { tier: 'client', scope: { clientId: 7 } },
      { tier: 'feed_source', scope: { feedSourceId: 3 } },
    ]);
    expect(currentDataTier({ feedSourceId: 3 })).toBe('feed_source');
  });
});
