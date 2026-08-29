import { describe, expect, it } from 'vitest';
import { addInstance, isInstancesEqual, removeInstance, reorderInstances, type LocalInstance } from './dndUtils';

const a: LocalInstance = { clientId: 'a', position: 0, plugin_id: 'p1', name: 'A', configuration: { x: 1 } };
const b: LocalInstance = { clientId: 'b', position: 1, plugin_id: 'p2', name: 'B', configuration: {} };
const c: LocalInstance = { clientId: 'c', position: 2, plugin_id: 'p3', name: 'C', configuration: {} };

describe('dndUtils', () => {
  it('addInstance appends a new instance with empty configuration', () => {
    const result = addInstance([a], { id: 'p2', name: 'B' });
    expect(result).toHaveLength(2);
    expect(result[1].plugin_id).toBe('p2');
    expect(result[1].name).toBe('B');
    expect(result[1].clientId).not.toBe('');
    expect(result[1].configuration).toEqual({});
  });

  it('reorderInstances moves an item from one index to another', () => {
    expect(reorderInstances([a, b, c], 0, 2)).toEqual([b, c, a]);
    expect(reorderInstances([a, b, c], 2, 0)).toEqual([c, a, b]);
  });

  it('removeInstance removes by clientId', () => {
    expect(removeInstance([a, b, c], 'b')).toEqual([a, c]);
  });

  it('isInstancesEqual compares deep equality ignoring clientId', () => {
    const a1: LocalInstance = { clientId: 'x', position: 0, plugin_id: 'p1', name: 'A', configuration: { x: 1 } };
    const a2: LocalInstance = { clientId: 'y', position: 0, plugin_id: 'p1', name: 'A', configuration: { x: 1 } };
    expect(isInstancesEqual([a1], [a2])).toBe(true);
    expect(isInstancesEqual([a1], [a])).toBe(true);
    expect(isInstancesEqual([a, b], [a])).toBe(false);
  });
});