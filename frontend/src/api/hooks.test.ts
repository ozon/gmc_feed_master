import { describe, expect, it } from 'vitest';
import { fillChartDates } from './hooks';

describe('fillChartDates', () => {
  it('zero-fills missing days between first and last row', () => {
    const rows = [
      { date: '2026-09-01', success: 1, error: 0 },
      { date: '2026-09-04', success: 2, error: 1 },
    ];
    const filled = fillChartDates(rows, 4);
    expect(filled.map((r) => r.date)).toEqual([
      '2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04',
    ]);
    expect(filled[1]).toEqual({ date: '2026-09-02', success: 0, error: 0 });
  });

  it('returns empty array for empty input', () => {
    expect(fillChartDates([], 14)).toEqual([]);
  });
});
