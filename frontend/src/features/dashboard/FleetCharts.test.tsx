import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../../i18n';
import { render } from '../../test/render';
import type { DashboardSummary } from '../../api/types';

const charts = vi.hoisted(() => ({
  donut: [] as Array<{ data: Array<{ name: string; value: number; color: string }> }>,
  area: [] as Array<{ dataKey: string; series: Array<{ name: string }> }>,
}));

vi.mock('@mantine/charts', () => ({
  DonutChart: (props: (typeof charts)['donut'][number]) => {
    charts.donut.push(props);
    return null;
  },
  AreaChart: (props: (typeof charts)['area'][number]) => {
    charts.area.push(props);
    return null;
  },
}));

import { FleetCharts } from './FleetCharts';

function summary(feedCount: number): DashboardSummary {
  const feeds = Array.from({ length: feedCount }, (_, i) => ({
    id: i + 1,
    client_id: 1,
    name: `Feed ${i + 1}`,
    source_format: 'tsv',
    item_count: (feedCount - i) * 100,
    last_export_at: null,
    last_export_status: null,
    last_run_at: null,
    last_run_status: null,
    quality: { critical: 0, warning: 0, info: 0 },
  }));
  return {
    counts: { clients: 1, feed_sources: feedCount, active_products: 1, failed_last_exports: 0 },
    clients: [{ id: 1, name: 'Acme', status: 'active', feed_sources: feeds }],
    runs_by_day: [{ date: '2026-09-01', success: 1, error: 0 }],
  };
}

beforeAll(async () => {
  await i18n.loadNamespaces(['dashboard']);
});

beforeEach(() => {
  charts.donut.length = 0;
  charts.area.length = 0;
});

describe('FleetCharts', () => {
  it('maps feeds to donut slices and trend series by name', () => {
    render(<FleetCharts summary={summary(2)} />);
    expect(charts.donut[0].data.map((d) => [d.name, d.value, d.color])).toEqual([
      ['Acme / Feed 1', 200, 'blue.6'],
      ['Acme / Feed 2', 100, 'indigo.6'],
    ]);
    expect(charts.area[0].dataKey).toBe('date');
    expect(charts.area[0].series.map((s) => s.name)).toEqual(['success', 'error']);
  });

  it('aggregates slices beyond the 8-feed cap into an Other row', () => {
    render(<FleetCharts summary={summary(9)} />);
    const data = charts.donut[0].data;
    expect(data).toHaveLength(9);
    expect(data[8]).toEqual({ name: i18n.t('charts.other', { ns: 'dashboard' }), value: 100, color: 'gray.6' });
  });
});
