import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { notifications, Notifications } from '@mantine/notifications';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { MonitoringFindingsPage } from './MonitoringFindingsPage';
import { queryClient } from '../../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const findings = {
  ingestion_run_id: 1,
  counts: { critical: 1, warning: 0, info: 0 },
  product_count: 2,
  delta: { fixed: 0, new: 0, remaining: 0 },
  has_previous: false,
  prev_counts: null,
  findings: [
    { severity: 'critical', code: 'missing_title', field: 'title', message: 'Title is required', product_id: 'p1', details: null },
    { severity: 'info', code: 'low_image_quality', field: 'image_link', message: 'Image quality is low', product_id: 'p2', details: null },
  ],
};

const historyRows = [
  {
    id: 1,
    started_at: '2026-09-01T10:00:00',
    product_count: 2,
    critical: 1,
    warning: 0,
    info: 0,
    fixed: 0,
    new: 0,
    remaining: 0,
  },
];

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function renderAt() {
  return render(
    <MemoryRouter initialEntries={['/clients/1/feeds/1/monitoring/findings']}>
      <Notifications position="top-right" limit={1} />
      <Routes>
        <Route path="/clients/:clientId/feeds/:feedSourceId/monitoring/findings" element={<MonitoringFindingsPage />} />
      </Routes>
    </MemoryRouter>,
    { wrapper: withQueryClient() },
  );
}

describe('MonitoringFindingsPage', () => {
  it('renders findings with severity badges', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1/quality-findings') return jsonResponse(findings);
      if (url.startsWith('/feed-sources/1/quality-history')) return jsonResponse({ rows: historyRows });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-table')).toBeInTheDocument());
    const table = within(screen.getByTestId('findings-table'));
    expect(table.getByText('missing_title')).toBeInTheDocument();
    expect(table.getByText('low_image_quality')).toBeInTheDocument();
  });

  it('filters by severity when MultiSelect is used', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/feed-sources/1/quality-findings') return jsonResponse(findings);
      if (url.startsWith('/feed-sources/1/quality-history')) return jsonResponse({ rows: historyRows });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-table')).toBeInTheDocument());
    expect(screen.getAllByTestId(/finding-row-/)).toHaveLength(2);
    await user.click(screen.getByRole('combobox', { name: /severity/i }));
    await user.click(screen.getByRole('option', { name: 'Critical' }));
    expect(screen.getAllByTestId(/finding-row-/)).toHaveLength(1);
  });

  it('renders severity summary cards with counts and of-products line', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1/quality-findings') return jsonResponse(findings);
      if (url.startsWith('/feed-sources/1/quality-history')) return jsonResponse({ rows: historyRows });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-table')).toBeInTheDocument());
    expect(screen.getByTestId('card-critical')).toHaveTextContent('1');
    expect(screen.getByTestId('card-warning')).toHaveTextContent('0');
    expect(screen.getByTestId('card-info')).toHaveTextContent('0');
    expect(screen.getByText(/of 2 products/i)).toBeInTheDocument();
  });

  it('renders delta badges when has_previous and hides them otherwise', async () => {
    const withDelta = {
      ...findings,
      has_previous: true,
      delta: { fixed: 2, new: 1, remaining: 3 },
      prev_counts: { critical: 3, warning: 0, info: 0 },
    };
    stubFetch((url) => {
      if (url === '/feed-sources/1/quality-findings') return jsonResponse(withDelta);
      if (url.startsWith('/feed-sources/1/quality-history')) return jsonResponse({ rows: historyRows });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getAllByTestId('delta-fixed').length).toBeGreaterThan(0));
    expect(screen.getAllByTestId('delta-fixed')).toHaveLength(3);
    expect(screen.getAllByTestId('delta-fixed')[0]).toHaveTextContent('2');
    expect(screen.getAllByTestId('delta-new')[0]).toHaveTextContent('1');
  });

  it('filters rows by code via the code Select', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/feed-sources/1/quality-findings') return jsonResponse(findings);
      if (url.startsWith('/feed-sources/1/quality-history')) return jsonResponse({ rows: historyRows });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-table')).toBeInTheDocument());
    expect(screen.getAllByTestId(/finding-row-/)).toHaveLength(2);
    await user.click(screen.getByRole('combobox', { name: /code/i }));
    await user.click(screen.getByRole('option', { name: 'missing_title' }));
    expect(screen.getAllByTestId(/finding-row-/)).toHaveLength(1);
    const table = within(screen.getByTestId('findings-table'));
    expect(table.getByText('missing_title')).toBeInTheDocument();
    expect(table.queryByText('low_image_quality')).not.toBeInTheDocument();
  });
});
