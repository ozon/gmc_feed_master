import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { notifications, Notifications } from '@mantine/notifications';
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
  counts: { critical: 1, warning: 1, info: 0 },
  product_count: 2,
  delta: { fixed: 0, new: 0, remaining: 0 },
  has_previous: false,
  prev_counts: null,
  findings: [
    {
      severity: 'critical',
      code: 'gtin_mpn',
      field: 'gtin',
      message: 'Bad GTIN',
      product_id: 'p1',
      details: {},
    },
    {
      severity: 'warning',
      code: 'brand_required',
      field: 'brand',
      message: 'Missing brand',
      product_id: 'p2',
      details: {},
    },
  ],
};

const historyRows = [
  {
    id: 1,
    started_at: '2026-09-01T10:00:00',
    product_count: 2,
    critical: 1,
    warning: 1,
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

function renderAt() {
  return render(
    <MemoryRouter initialEntries={['/clients/1/feeds/1/monitoring/findings']}>
      <Notifications position="top-right" limit={1} />
      <Routes>
        <Route
          path="/clients/:clientId/feeds/:feedSourceId/monitoring/findings"
          element={<MonitoringFindingsPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

function stubEndpoints(payload: unknown) {
  stubFetch((url) => {
    if (url === '/feed-sources/1/quality-findings') return jsonResponse(payload);
    if (url.startsWith('/feed-sources/1/quality-history'))
      return jsonResponse({ rows: historyRows });
    if (url.startsWith('/feed-sources/1/products/')) {
      return jsonResponse({
        product_id: 'p1',
        status: 'active',
        content_hash: 'h',
        config_hash: 'c',
        last_seen_at: '2026-09-01T10:00:00',
        removed_at: null,
        raw_data: { title: 'Product 1' },
        processed_data: null,
        excluded: false,
      });
    }
    return jsonResponse({});
  });
}

describe('MonitoringFindingsPage', () => {
  it('renders summary cards, of-products line and grouped findings', async () => {
    stubEndpoints(findings);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-groups')).toBeInTheDocument());
    expect(screen.getByTestId('card-critical')).toHaveTextContent('1');
    expect(screen.getByText(/of 2 products/i)).toBeInTheDocument();
    const groups = screen.getByTestId('findings-groups');
    expect(within(groups).getByText('Identifier problem')).toBeInTheDocument();
    expect(within(groups).getByText('Missing brand')).toBeInTheDocument();
  });

  it('renders delta badges only when a previous run exists', async () => {
    stubEndpoints({
      ...findings,
      has_previous: true,
      delta: { fixed: 2, new: 1, remaining: 3 },
      prev_counts: { critical: 3, warning: 0, info: 0 },
    });
    renderAt();
    await waitFor(() => expect(screen.getAllByTestId('delta-fixed').length).toBeGreaterThan(0));
    expect(screen.getAllByTestId('delta-fixed')[0]).toHaveTextContent('2');
    expect(screen.getAllByTestId('delta-new')[0]).toHaveTextContent('1');
  });

  it('filters findings by severity', async () => {
    const user = userEvent.setup();
    stubEndpoints(findings);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-groups')).toBeInTheDocument());
    await user.click(screen.getByRole('radio', { name: 'Flat' }));
    await waitFor(() => expect(screen.getAllByTestId('finding-row')).toHaveLength(2));
    await user.click(screen.getByRole('combobox', { name: /severity/i }));
    await user.click(screen.getByRole('option', { name: 'Critical' }));
    expect(screen.getAllByTestId('finding-row')).toHaveLength(1);
  });

  it('opens the product drawer from a finding', async () => {
    const user = userEvent.setup();
    stubEndpoints(findings);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-groups')).toBeInTheDocument());
    await user.click(screen.getByRole('radio', { name: 'Flat' }));
    await user.click(await screen.findByRole('button', { name: 'Open product p1' }));
    expect(await screen.findByText('Product Details')).toBeInTheDocument();
  });
});
