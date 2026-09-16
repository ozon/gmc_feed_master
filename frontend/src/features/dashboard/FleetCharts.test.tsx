import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { FleetCharts } from './FleetCharts';
import type { DashboardSummary } from '../../api/types';

const summary = (runs: DashboardSummary['runs_by_day']): DashboardSummary => ({
  counts: { clients: 1, feed_sources: 2, active_products: 30, failed_last_exports: 0 },
  clients: [
    {
      id: 1, name: 'Acme', status: 'active',
      feed_sources: [
        { id: 2, client_id: 1, name: 'Feed A', source_format: 'xml', item_count: 20,
          last_export_at: null, last_export_status: null, last_run_at: null, last_run_status: null,
          quality: { critical: 0, warning: 0, info: 0 } },
        { id: 3, client_id: 1, name: 'Feed B', source_format: 'tsv', item_count: 10,
          last_export_at: null, last_export_status: null, last_run_at: null, last_run_status: null,
          quality: { critical: 0, warning: 0, info: 0 } },
      ],
    },
  ],
  runs_by_day: runs,
});

describe('FleetCharts', () => {
  beforeAll(async () => {
    await i18n.loadNamespaces(['dashboard']);
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
});
