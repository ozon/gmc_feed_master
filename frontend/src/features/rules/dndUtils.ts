import { enforcePinning, type Rule } from '../../../../plugins/core/rules/frontend/ast';

type DragId = string | number | { id: string | number };

function normalizeId(value: DragId | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'object') return String(value.id);
  return String(value);
}

export function applyDragEnd(rules: Rule[], event: { active: DragId; over: DragId | null }): Rule[] | null {
  const activeId = normalizeId(event.active);
  const overId = normalizeId(event.over);
  if (!activeId || !overId || activeId === overId) return null;
  const fromIdx = rules.findIndex((r) => r.id === activeId);
  const toIdx = rules.findIndex((r) => r.id === overId);
  if (fromIdx < 0 || toIdx < 0) return null;
  const next = rules.slice();
  const [moved] = next.splice(fromIdx, 1);
  next.splice(toIdx, 0, moved);
  return enforcePinning(next);
}
