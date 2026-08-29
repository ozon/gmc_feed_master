import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { notifications, Notifications } from '@mantine/notifications';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { MonitoringRunsPage } from './MonitoringRunsPage';
import { queryClient } from '../../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const run = {
  id: 1,
  status: 'success',
  started_at: '2026-08-29T10:00:00Z',
  completed_at: '2026-08-29T10:01:00Z',
  processed_count: 100,
  failed_count: 2,
  error_message: null,
  statistics: {},
};

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
    <MemoryRouter initialEntries={['/clients/1/feeds/1/monitoring/runs']}>
      <Notifications position="top-right" limit={1} />
      <Routes>
        <Route path="/clients/:clientId/feeds/:feedSourceId/monitoring/runs" element={<MonitoringRunsPage />} />
      </Routes>
    </MemoryRouter>,
    { wrapper: withQueryClient() },
  );
}

describe('MonitoringRunsPage', () => {
  it('renders the table with status badge', async () => {
    stubFetch((url) => {
      if (url.startsWith('/feed-sources/1/ingestion-runs')) {
        return jsonResponse([run]);
      }
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('run-row-1')).toBeInTheDocument());
    expect(screen.getByText('success')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
  });

  it('renders the empty state when no runs', async () => {
    stubFetch((url) => {
      if (url.startsWith('/feed-sources/1/ingestion-runs')) return jsonResponse([]);
      return jsonResponse({});
    });
    renderAt();
    expect(await screen.findByText(/no runs/i)).toBeInTheDocument();
  });
});