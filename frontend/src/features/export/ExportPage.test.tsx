import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { ExportPage } from './ExportPage';
import { queryClient as globalQueryClient } from '../../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const feed = {
  id: 1,
  client_id: 1,
  name: 'Feed',
  source_format: 'xml',
  cron_expression: '0 * * * *',
  target_country: 'DE',
  target_language: 'de',
  currency: 'EUR',
  source_url: 'https://example.com/feed.xml',
  feed_type: 'full',
  history_retention_count: 30,
  volume_drop_threshold_pct: 20,
  configuration: {},
  export_url: 'http://localhost/export/1/abc',
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
};

const versions = [
  { id: 3, version_number: 3, product_count: 100, file_hash: 'h3', source: 'run', source_version_id: null, created_at: '2026-08-29T10:00:00Z', findings: { critical: 2, warning: 0, info: 5 } },
  { id: 2, version_number: 2, product_count: 98, file_hash: 'h2', source: 'rollback', source_version_id: 3, created_at: '2026-08-28T10:00:00Z', findings: null },
  { id: 1, version_number: 1, product_count: 90, file_hash: 'h1', source: 'run', source_version_id: null, created_at: '2026-08-27T10:00:00Z', findings: { critical: 0, warning: 0, info: 0 } },
];

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

beforeEach(() => {
  globalQueryClient.clear();
  notifications.clean();
});

function renderAt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/clients/1/feeds/1/export']}>
        <Notifications position="top-right" limit={1} />
        <Routes>
          <Route path="/clients/:clientId/feeds/:feedSourceId/export" element={<ExportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ExportPage', () => {
  it('renders rollback-source row with not-QCd badge and default diff selection', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/export-history') return jsonResponse(versions);
      if (url.startsWith('/feed-sources/1/export-history/')) return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('version-row-2')).toBeInTheDocument());
    expect(screen.getByTestId('not-qcd-badge')).toBeInTheDocument();
  });

  it('opens rollback confirm modal with typeToConfirm and calls POST', async () => {
    const user = userEvent.setup();
    let captured: string | null = null;
    stubFetch((url, init) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/export-history') return jsonResponse(versions);
      if (url === '/feed-sources/1/export-history/1/rollback' && init?.method === 'POST') {
        captured = url;
        return new Response(null, { status: 204 });
      }
      if (url.startsWith('/feed-sources/1/export-history/')) return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
      return jsonResponse({});
    });
    renderAt();
    await screen.findByTestId('version-row-1');
    await user.click(screen.getByTestId('rollback-1'));
    const input = await screen.findByLabelText(/type/i);
    await user.type(input, '1');
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /rollback/i }));
    await waitFor(() => expect(captured).toBe('/feed-sources/1/export-history/1/rollback'));
  });

  it('renders per-severity findings badges for run versions', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/export-history') return jsonResponse(versions);
      if (url.startsWith('/feed-sources/1/export-history/')) return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('version-row-3')).toBeInTheDocument());
    expect(screen.getByTestId('findings-critical-3')).toHaveTextContent('2');
    expect(screen.getByTestId('findings-warning-3')).toHaveTextContent('0');
    expect(screen.getByTestId('findings-info-3')).toHaveTextContent('5');
  });

  it('renders no findings badges for rollback versions but keeps the not-QC badge', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/export-history') return jsonResponse(versions);
      if (url.startsWith('/feed-sources/1/export-history/')) return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('version-row-2')).toBeInTheDocument());
    expect(screen.queryByTestId('findings-critical-2')).not.toBeInTheDocument();
    expect(screen.getByTestId('not-qcd-badge')).toBeInTheDocument();
  });

  it('renders zero-count findings as dimmed gray badges for clean run versions', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/export-history') return jsonResponse(versions);
      if (url.startsWith('/feed-sources/1/export-history/')) return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('version-row-1')).toBeInTheDocument());
    const badge = screen.getByTestId('findings-critical-1');
    expect(badge).toHaveTextContent('0');
    expect(badge).toHaveAttribute('title', '0 critical');
  });
});
