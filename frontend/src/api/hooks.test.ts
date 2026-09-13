import { describe, expect, it } from 'vitest';
import { fillChartDates, fillDates } from './hooks';

describe('fillDates', () => {
  it('zero-fills missing days with factory default', () => {
    type Row = { date: string; raw: number; exportable: number };
    const rows: Row[] = [
      { date: '2026-09-01', raw: 5, exportable: 3 },
      { date: '2026-09-04', raw: 8, exportable: 6 },
    ];
    const filled = fillDates(rows, 4, (date) => ({ date, raw: 0, exportable: 0 }));
    expect(filled.map((r) => r.date)).toEqual([
      '2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04',
    ]);
    expect(filled[1]).toEqual({ date: '2026-09-02', raw: 0, exportable: 0 });
  });

  it('returns empty array for empty input', () => {
    expect(fillDates([], 14, (date) => ({ date }))).toEqual([]);
  });
});

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
