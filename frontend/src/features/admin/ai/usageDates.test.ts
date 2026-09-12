import { describe, expect, it } from 'vitest';
import { usageDateParams } from './usageDates';

describe('usageDateParams', () => {
  it('builds from at midnight and to at end of day', () => {
    const from = new Date(2026, 8, 1);   // Sep 1 2026, local
    const to = new Date(2026, 8, 12);
    const params = usageDateParams(from, to);
    expect(params.from).toBe(new Date(2026, 8, 1).toISOString());
    expect(params.to).toBe(new Date(2026, 8, 12, 23, 59, 59).toISOString());
  });
  it('omits unset dates', () => {
    expect(usageDateParams(null, null)).toEqual({});
  });
});
