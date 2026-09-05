import type { PluginScope } from '../../api/hooks';
import type { Tier } from '../../types/scope';

export type { Tier } from '../../types/scope';

export type SlotRule = {
  id: string;
  name: string;
  isActive: boolean;
  targetSlot: string;
  matchField: string;
  matchMode?: 'values' | 'all';
  valueTemplate: string;
  fallbackTemplate: string;
};

export type ScopedSlotRule = SlotRule & { origin: Tier };

/**
 * Union-by-id merge mirroring the runtime's manifest-declared
 * `config_merge` strategy (backend config_resolver._merge_list):
 * ancestor rules keep their positions, more-specific content wins by id,
 * unseen ids are appended in overlay order.
 */
export function mergeSlotRules(
  tiers: ReadonlyArray<{ tier: Tier; rules: ReadonlyArray<SlotRule> }>,
): ScopedSlotRule[] {
  const byId = new Map<string, ScopedSlotRule>();
  const order: string[] = [];
  for (const { tier, rules } of tiers) {
    for (const rule of rules) {
      if (!byId.has(rule.id)) order.push(rule.id);
      byId.set(rule.id, { ...rule, origin: tier });
    }
  }
  return order.map((id) => byId.get(id)!);
}

/** Per-slot id sequences — the runtime's per-slot winning order. */
export function groupBySlot(rules: ReadonlyArray<ScopedSlotRule>): Record<string, string[]> {
  const bySlot: Record<string, string[]> = {};
  for (const rule of rules) {
    (bySlot[rule.targetSlot] ??= []).push(rule.id);
  }
  return bySlot;
}

/**
 * Merge bulk-value dicts (ancestors first). `inherited` marks values that
 * come from an ancestor tier and are absent at the current tier.
 */
export function mergeSlotIds(
  tiers: ReadonlyArray<{ tier: Tier; ids: Readonly<Record<string, string>> }>,
): Record<string, { value: string; inherited: boolean }> {
  const current = tiers[tiers.length - 1]?.ids ?? {};
  const merged: Record<string, { value: string; inherited: boolean }> = {};
  for (const { ids } of tiers) {
    for (const [id, value] of Object.entries(ids)) {
      merged[id] = { value, inherited: !(id in current) };
    }
  }
  for (const [id, value] of Object.entries(current)) {
    merged[id] = { value, inherited: false };
  }
  return merged;
}

/** Manifest config_scope = ["global", "client"]: the feed tier is read-only. */
export function editableConfigTier(scope: PluginScope): Tier | null {
  if (scope.feedSourceId !== undefined) return null;
  if (scope.clientId !== undefined) return 'client';
  return 'global';
}

/** Manifest data_scope = ["client", "feed_source"]: no global data tier. */
export function currentDataTier(scope: PluginScope): Tier | null {
  if (scope.feedSourceId !== undefined) return 'feed_source';
  if (scope.clientId !== undefined) return 'client';
  return null;
}

/** Declared config tiers from global down to the URL tier, ancestors first. */
export function configTierChain(
  scope: PluginScope,
  routeContext: { clientId?: string },
): Array<{ tier: Tier; scope: PluginScope }> {
  const chain: Array<{ tier: Tier; scope: PluginScope }> = [
    { tier: 'global', scope: {} },
  ];
  const editable = editableConfigTier(scope);
  if (editable === 'client') {
    chain.push({ tier: 'client', scope: { clientId: scope.clientId! } });
  } else if (editable === null && routeContext.clientId) {
    chain.push({ tier: 'client', scope: { clientId: Number(routeContext.clientId) } });
  }
  return chain;
}

/** Declared data tiers from ancestors down to the URL tier, ancestors first. */
export function dataTierChain(
  scope: PluginScope,
  routeContext: { clientId?: string },
): Array<{ tier: Tier; scope: PluginScope }> {
  const current = currentDataTier(scope);
  if (current === null) return [];
  if (current === 'client') {
    return [{ tier: 'client', scope: { clientId: scope.clientId! } }];
  }
  const chain: Array<{ tier: Tier; scope: PluginScope }> = [];
  if (routeContext.clientId) {
    chain.push({ tier: 'client', scope: { clientId: Number(routeContext.clientId) } });
  }
  chain.push({ tier: 'feed_source', scope });
  return chain;
}
