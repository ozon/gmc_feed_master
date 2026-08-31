import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  vi.spyOn(notifications, 'show').mockClear();
  vi.spyOn(notifications, 'update').mockClear();
  queryClient.clear();
  notifications.clean();
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function postCalls(url: string): number {
  const fm = vi.mocked(globalThis.fetch);
  return fm.mock.calls.filter(
    ([input, init]) => String(input) === url && init?.method === 'POST',
  ).length;
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

  it('shows a Run pipeline button and triggers a run', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url.startsWith('/feed-sources/1/ingestion-runs')) return jsonResponse([]);
      if (url === '/feed-sources/1/run') return jsonResponse({ run_id: 5 }, 202);
      return jsonResponse({});
    });
    renderAt();
    await screen.findByText(/no runs/i);

    const btn = screen.getByRole('button', { name: /run pipeline/i });
    expect(btn).toBeEnabled();

    await user.click(btn);

    await waitFor(() => expect(postCalls('/feed-sources/1/run')).toBe(1));
  });

  it('shows exactly one failure notification when the run trigger fails', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url.startsWith('/feed-sources/1/ingestion-runs')) return jsonResponse([]);
      if (url === '/feed-sources/1/run') return jsonResponse({ detail: 'boom' }, 500);
      return jsonResponse({});
    });
    renderAt();
    await screen.findByText(/no runs/i);

    await user.click(screen.getByRole('button', { name: /run pipeline/i }));

    await waitFor(() => {
      expect(notifications.show).toHaveBeenCalledTimes(1);
    });
    expect(notifications.show).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Pipeline is running...' }),
    );
    expect(notifications.update).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Could not start pipeline.', color: 'red' }),
    );
  });
});
