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
  findings: [
    { severity: 'critical', code: 'missing_title', field: 'title', message: 'Title is required', product_id: 'p1', details: null },
    { severity: 'info', code: 'low_image_quality', field: 'image_link', message: 'Image quality is low', product_id: 'p2', details: null },
  ],
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
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-table')).toBeInTheDocument());
    expect(screen.getByText('missing_title')).toBeInTheDocument();
    expect(screen.getByText('low_image_quality')).toBeInTheDocument();
  });

  it('filters by severity when MultiSelect is used', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/feed-sources/1/quality-findings') return jsonResponse(findings);
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('findings-table')).toBeInTheDocument());
    expect(screen.getAllByTestId(/finding-row-/)).toHaveLength(2);
    await user.click(screen.getByRole('combobox', { name: /severity/i }));
    await user.click(screen.getByRole('option', { name: /critical/i }));
    expect(screen.getAllByTestId(/finding-row-/)).toHaveLength(1);
  });
});