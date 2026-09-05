import type { PipelineInstance } from '../../api/types';

export type LocalInstance = PipelineInstance & { clientId: string };

export function addInstance(
  instances: LocalInstance[],
  plugin: { id: string; name: string },
): LocalInstance[] {
  const taken = new Set(instances.map((i) => i.clientId));
  let index = instances.length;
  while (taken.has(`${plugin.id}-${index}`)) index += 1;
  const clientId = `${plugin.id}-${index}`;
  return [
    ...instances,
    {
      id: null,
      enabled: true,
      clientId,
      position: instances.length,
      plugin_id: plugin.id,
      name: plugin.name,
      configuration: {},
    },
  ];
}

export function reorderInstances(
  instances: LocalInstance[],
  fromIdx: number,
  toIdx: number,
): LocalInstance[] {
  if (fromIdx === toIdx) return instances;
  const next = instances.slice();
  const [moved] = next.splice(fromIdx, 1);
  next.splice(toIdx, 0, moved);
  return next;
}

export function removeInstance(instances: LocalInstance[], clientId: string): LocalInstance[] {
  return instances.filter((i) => i.clientId !== clientId);
}

export function applyDragEnd(
  instances: LocalInstance[],
  event: {
    active: { id: string | number; data?: { current?: unknown } };
    over: { id: string | number } | null;
  },
): LocalInstance[] | null {
  const activeData = event.active.data?.current as { source?: string } | undefined;
  if (activeData?.source === 'workspace' && event.over) {
    const fromIdx = instances.findIndex((i) => i.clientId === event.active.id);
    const toIdx = instances.findIndex((i) => i.clientId === event.over!.id);
    if (fromIdx >= 0 && toIdx >= 0) return reorderInstances(instances, fromIdx, toIdx);
  }
  return null;
}

export function isInstancesEqual(
  a: LocalInstance[] | PipelineInstance[],
  b: LocalInstance[] | PipelineInstance[],
): boolean {
  return JSON.stringify(stripClientIds(a)) === JSON.stringify(stripClientIds(b));
}

function stripClientIds(items: Array<PipelineInstance & { clientId?: string }>): PipelineInstance[] {
  return items.map(({ clientId: _clientId, ...rest }) => rest);
}
