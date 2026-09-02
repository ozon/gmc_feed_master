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

export function isInstancesEqual(
  a: LocalInstance[] | PipelineInstance[],
  b: LocalInstance[] | PipelineInstance[],
): boolean {
  return JSON.stringify(stripClientIds(a)) === JSON.stringify(stripClientIds(b));
}

function stripClientIds(items: Array<PipelineInstance & { clientId?: string }>): PipelineInstance[] {
  return items.map(({ clientId: _clientId, ...rest }) => rest);
}
