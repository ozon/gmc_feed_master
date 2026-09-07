import { parseIdList } from './ids';
import type { ScopedSlotRule } from './scopeMerge';

export type RuleShadowInfo = {
  /** Values present in this rule but ignored — a higher-priority rule claims them. */
  shadowed: Set<string>;
  /** Shadowed value -> name of the first higher-priority rule that claims it. */
  shadowedBy: Map<string, string>;
};

/**
 * Syntactic first-match-wins analysis: per slot, walk ACTIVE rules in
 * evaluation order; a value already claimed by an earlier rule is shadowed.
 * An `all`-mode rule shadows every value of all lower-priority rules in the
 * slot. Inactive rules neither claim nor are shadowed.
 */
export function computeShadowing(
  rules: ReadonlyArray<ScopedSlotRule>,
  values: Readonly<Record<string, string>>,
): Record<string, RuleShadowInfo> {
  const result: Record<string, RuleShadowInfo> = {};
  for (const rule of rules) {
    result[rule.id] = { shadowed: new Set(), shadowedBy: new Map() };
  }
  const bySlot = new Map<string, ScopedSlotRule[]>();
  for (const rule of rules) {
    if (!rule.isActive) continue;
    const list = bySlot.get(rule.targetSlot) ?? [];
    list.push(rule);
    bySlot.set(rule.targetSlot, list);
  }
  for (const slotRules of bySlot.values()) {
    const claimedBy = new Map<string, string>();
    let firstAllName: string | undefined;
    for (const rule of slotRules) {
      const info = result[rule.id];
      const allOwner = firstAllName;
      if (rule.matchMode === 'all') {
        firstAllName ??= rule.name;
      }
      for (const value of parseIdList(values[rule.id] ?? '')) {
        const owner = claimedBy.get(value) ?? allOwner;
        if (owner !== undefined && owner !== rule.name) {
          info.shadowed.add(value);
          info.shadowedBy.set(value, owner);
        } else if (rule.matchMode !== 'all') {
          claimedBy.set(value, rule.name);
        }
      }
    }
  }
  return result;
}
