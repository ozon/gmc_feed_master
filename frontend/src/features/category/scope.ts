import type { PluginScope } from '../../api/hooks';
import type { CategoryRule, ScopedCategoryRule, Tier } from './types';

export function editableTier(scope: PluginScope): Tier {
  return scope.clientId !== undefined ? 'client' : 'global';
}

export function mergeRules(
  globalRules: CategoryRule[],
  clientRules: CategoryRule[],
): ScopedCategoryRule[] {
  const merged: ScopedCategoryRule[] = globalRules.map((rule) => ({ ...rule, origin: 'global' }));
  const byId = new Map(merged.map((rule, index) => [rule.id, index]));
  for (const rule of clientRules) {
    const index = byId.get(rule.id);
    if (index === undefined) {
      merged.push({ ...rule, origin: 'client' });
      byId.set(rule.id, merged.length - 1);
    } else {
      merged[index] = { ...rule, origin: 'client' };
    }
  }
  return merged;
}
