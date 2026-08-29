import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { notifications, Notifications } from '@mantine/notifications';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { MonitoringDryRunPage } from './MonitoringDryRunPage';
import { queryClient } from '../../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

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
    <MemoryRouter initialEntries={['/clients/1/feeds/1/monitoring/dry-run']}>
      <Notifications position="top-right" limit={1} />
      <Routes>
        <Route path="/clients/:clientId/feeds/:feedSourceId/monitoring/dry-run" element={<MonitoringDryRunPage />} />
      </Routes>
    </MemoryRouter>,
    { wrapper: withQueryClient() },
  );
}

describe('MonitoringDryRunPage', () => {
  it('renders the form with default limit 100', async () => {
    stubFetch(() => jsonResponse({}));
    renderAt();
    const input = await screen.findByTestId('dry-run-limit');
    expect(input).toHaveValue('100');
  });

  it('calls POST /dry-run and renders results', async () => {
    const user = userEvent.setup();
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url === '/feed-sources/1/dry-run' && init?.method === 'POST') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ processed: 50, dropped: 1, findings: [] });
      }
      return jsonResponse({});
    });
    renderAt();
    await user.click(screen.getByTestId('dry-run-submit'));
    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured!.body).toEqual({ limit: 100 });
    expect(await screen.findByTestId('dry-run-results')).toBeInTheDocument();
  });
});