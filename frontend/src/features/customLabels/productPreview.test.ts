import { describe, expect, it } from 'vitest';
import { OVERSCAN, ROW_HEIGHT, VIEWPORT_ROWS, availabilityColor, windowRange } from './productPreview';

describe('windowRange', () => {
  it('starts at 0 and covers the viewport plus overscan', () => {
    expect(windowRange(0, 1000)).toEqual([0, VIEWPORT_ROWS + OVERSCAN]);
  });

  it('shifts with scrollTop in row-height steps', () => {
    const top = 5 * ROW_HEIGHT; // scrolled past 5 rows
    const [start, end] = windowRange(top, 1000);
    expect(start).toBe(5 - OVERSCAN);
    expect(end).toBe(5 + VIEWPORT_ROWS + OVERSCAN);
  });

  it('clamps to the total', () => {
    expect(windowRange(10_000 * ROW_HEIGHT, 12)).toEqual([12, 12]);
  });

  it('handles zero rows without a negative start', () => {
    expect(windowRange(0, 0)).toEqual([0, 0]);
  });
});

describe('availabilityColor', () => {
  it('maps in_stock green, out_of_stock red, everything else gray', () => {
    expect(availabilityColor('in_stock')).toBe('green');
    expect(availabilityColor('out_of_stock')).toBe('red');
    expect(availabilityColor('preorder')).toBe('gray');
    expect(availabilityColor(null)).toBe('gray');
    expect(availabilityColor(undefined)).toBe('gray');
  });
});
