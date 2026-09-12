import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import App from '../../App';
import { queryClient } from '../../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const dashboardBody = {
  kpi: { raw_items: 1000, valid_items: 900, excluded_items: 50, last_duration_s: 42.5, readiness_rate: 0.94 },
  volume_trend: [{ date: '2026-09-12', raw: 1000, exportable: 900 }],
  stage_funnel: [
    { stage: 'ingest', passed: 1000, dropped: 5 },
    { stage: 'mapping', passed: 1000, dropped: 4 },
  ],
  quality: { critical: 3, warning: 12, info: 40, readiness_rate: 0.94 },
  recent_runs: [
    { id: 9, status: 'success', started_at: '2026-09-12T10:00:00Z', duration_s: 42.5, failed_count: 0 },
  ],
};

const summaryBody = {
  counts: { clients: 1, feed_sources: 1, active_products: 900, failed_last_exports: 0 },
  clients: [{
    id: 1, name: 'Acme', status: 'active',
    feed_sources: [{
      id: 2, client_id: 1, name: 'Main Feed', source_format: 'tsv', item_count: 900,
      last_export_at: null, last_export_status: null, last_run_at: null, last_run_status: null,
    }],
  }],
  runs_by_day: [],
};

const feedBody = {
  id: 2, client_id: 1, name: 'Main Feed', source_format: 'tsv',
  cron_expression: null, target_country: 'DE', target_language: 'de', currency: 'EUR',
  source_url: null, feed_type: 'product', history_retention_count: 10,
  volume_drop_threshold_pct: 30, configuration: {}, export_url: 'https://x/export/tok.xml',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};

beforeAll(async () => {
  await i18n.loadNamespaces(['feedDashboard', 'monitoring']);
});

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/clients/1/feeds/2');
  stubFetch((url) => {
    if (url === '/auth/me') return jsonResponse({ username: 'operator' });
    if (url === '/dashboard/summary') return jsonResponse(summaryBody);
    if (url === '/plugins') return jsonResponse([]);
    if (url === '/feed-sources/2/dashboard') return jsonResponse(dashboardBody);
    if (url === '/feed-sources/2') return jsonResponse(feedBody);
    return jsonResponse({});
  });
});

describe('FeedDashboardPage', () => {
  it('renders header with breadcrumb, badges, actions, KPIs and chart titles', async () => {
    render(<App />);
    expect((await screen.findAllByText('Main Feed')).length).toBeGreaterThan(0);
    expect(screen.getByText('TSV')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /run pipeline/i })).toBeInTheDocument();
    expect(screen.getByText('Raw items')).toBeInTheDocument();
    expect(screen.getByText('900')).toBeInTheDocument();
    expect(screen.getByText('Volume & pass-through (30 days)')).toBeInTheDocument();
    expect(screen.getByText('Pipeline stage funnel')).toBeInTheDocument();
    expect(screen.getByText('Quality distribution')).toBeInTheDocument();
    expect(screen.getByText('Recent runs')).toBeInTheDocument();
  });

  it('renders empty chart states when feed has no data', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(summaryBody);
      if (url === '/plugins') return jsonResponse([]);
      if (url === '/feed-sources/2/dashboard') {
        return jsonResponse({
          kpi: { raw_items: 0, valid_items: 0, excluded_items: 0, last_duration_s: null, readiness_rate: 1.0 },
          volume_trend: [], stage_funnel: [],
          quality: { critical: 0, warning: 0, info: 0, readiness_rate: 1.0 },
          recent_runs: [],
        });
      }
      if (url === '/feed-sources/2') return jsonResponse(feedBody);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByText('Raw items')).toBeInTheDocument();
    expect(screen.getAllByText(/no runs|nothing here|no quality|no run statistics/i).length).toBeGreaterThanOrEqual(3);
  });
});
