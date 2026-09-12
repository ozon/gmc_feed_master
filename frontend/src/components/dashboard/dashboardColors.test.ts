import { describe, expect, it } from 'vitest';
import { chartColors, donutPalette } from './dashboardColors';

describe('dashboardColors', () => {
  it('maps every semantic series name', () => {
    for (const key of ['success', 'error', 'warning', 'info', 'raw', 'exportable', 'passed', 'dropped', 'other'] as const) {
      expect(typeof chartColors[key]).toBe('string');
      expect(chartColors[key]).toMatch(/^[a-z]+\.?\d*$/);
    }
  });

  it('provides 8 donut palette colors', () => {
    expect(donutPalette).toHaveLength(8);
  });
});
