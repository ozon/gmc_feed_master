import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
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

const summary = (runs: DashboardSummary['runs_by_day']): DashboardSummary => ({
  counts: { clients: 1, feed_sources: 2, active_products: 30, failed_last_exports: 0 },
  clients: [
    {
      id: 1,
      name: 'Acme',
      status: 'active',
      feed_sources: [
        {
          id: 2,
          client_id: 1,
          name: 'Feed A',
          source_format: 'xml',
          item_count: 20,
          last_export_at: null,
          last_export_status: null,
          last_run_at: null,
          last_run_status: null,
          quality: { critical: 0, warning: 0, info: 0 },
        },
        {
          id: 3,
          client_id: 1,
          name: 'Feed B',
          source_format: 'tsv',
          item_count: 10,
          last_export_at: null,
          last_export_status: null,
          last_run_at: null,
          last_run_status: null,
          quality: { critical: 0, warning: 0, info: 0 },
        },
      ],
    },
  ],
  runs_by_day: runs,
});

describe('FleetCharts', () => {
  beforeAll(async () => {
    await i18n.loadNamespaces(['dashboard']);
  });

  beforeEach(() => {
    charts.donut.length = 0;
    charts.area.length = 0;
  });

  it('renders both chart titles and feed names in donut data', () => {
    render(<FleetCharts summary={summary([{ date: '2026-09-01', success: 3, error: 1 }])} />);
    expect(screen.getByText('Catalog volume by feed')).toBeInTheDocument();
    expect(screen.getByText('Pipeline health (14 days)')).toBeInTheDocument();
  });

  it('renders empty states when no data', () => {
    const empty = summary([]);
    empty.clients[0].feed_sources.forEach((feed) => {
      feed.item_count = 0;
    });
    render(<FleetCharts summary={empty} />);
    expect(screen.getByText('No staged products yet.')).toBeInTheDocument();
    expect(screen.getByText('No runs in the last 14 days.')).toBeInTheDocument();
  });

  it('maps feeds to donut slices and trend series by name', () => {
    render(<FleetCharts summary={summary([{ date: '2026-09-01', success: 3, error: 1 }])} />);
    expect(charts.donut[0].data.map((d) => [d.name, d.value, d.color])).toEqual([
      ['Acme / Feed A', 20, 'blue.6'],
      ['Acme / Feed B', 10, 'indigo.6'],
    ]);
    expect(charts.area[0].dataKey).toBe('date');
    expect(charts.area[0].series.map((s) => s.name)).toEqual(['success', 'error']);
  });

  it('aggregates slices beyond the 8-feed cap into an Other row', () => {
    const many = summary([{ date: '2026-09-01', success: 1, error: 0 }]);
    many.clients[0].feed_sources = Array.from({ length: 9 }, (_, i) => ({
      ...many.clients[0].feed_sources[0],
      id: i + 2,
      name: `Feed ${i + 1}`,
      item_count: (9 - i) * 10,
    }));
    render(<FleetCharts summary={many} />);
    const data = charts.donut[0].data;
    expect(data).toHaveLength(9);
    expect(data[8]).toEqual({
      name: i18n.t('charts.other', { ns: 'dashboard' }),
      value: 10,
      color: 'gray.6',
    });
  });
});
