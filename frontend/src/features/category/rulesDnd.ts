import type { ScopedCategoryRule } from './types';

export function applyRulesDragEnd(
  rules: ScopedCategoryRule[],
  activeId: string | null,
  overIndex: number | null,
): ScopedCategoryRule[] {
  if (activeId === null || overIndex === null) return rules;
  const from = rules.findIndex((rule) => rule.id === activeId);
  if (from === -1 || from === overIndex) return rules;
  const next = [...rules];
  const [moved] = next.splice(from, 1);
  next.splice(overIndex, 0, moved);
  return next;
}
