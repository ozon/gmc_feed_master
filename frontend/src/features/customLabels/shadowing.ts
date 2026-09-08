import { parseIdList } from './ids';
import type { ScopedSlotRule } from './scopeMerge';

export type ShadowOwnerInfo = { id: string; name: string; priority: number };

export type RuleShadowInfo = {
  /** Values present in this rule but ignored — a higher-priority rule claims them. */
  shadowed: Set<string>;
  /** Shadowed value -> the first higher-priority rule that claims it. */
  shadowedBy: Map<string, ShadowOwnerInfo>;
};

/**
 * Syntactic first-match-wins analysis: per slot, walk ACTIVE rules in
 * evaluation order; a value already claimed by an earlier rule is shadowed.
 * An `all`-mode rule shadows every value of all lower-priority rules in the
 * slot. Inactive rules neither claim nor are shadowed. Claims are keyed by
 * rule id (names may duplicate across rules); `priority` is the owner's
 * 1-based position among its slot's active rules — the same #N the UI shows.
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
    const claimedBy = new Map<string, ShadowOwnerInfo>();
    let firstAll: ShadowOwnerInfo | undefined;
    for (const [index, rule] of slotRules.entries()) {
      const info = result[rule.id];
      const allOwner = firstAll;
      if (rule.matchMode === 'all') {
        firstAll ??= { id: rule.id, name: rule.name, priority: index + 1 };
      }
      for (const value of parseIdList(values[rule.id] ?? '')) {
        const owner = claimedBy.get(value) ?? allOwner;
        if (owner !== undefined && owner.id !== rule.id) {
          info.shadowed.add(value);
          info.shadowedBy.set(value, owner);
        } else if (rule.matchMode !== 'all') {
          claimedBy.set(value, { id: rule.id, name: rule.name, priority: index + 1 });
        }
      }
    }
  }
  return result;
}
