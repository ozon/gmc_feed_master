import { beforeAll, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { SetupPage } from './SetupPage';
import type { FeedSourceRow } from '../../api/types';

beforeAll(async () => {
  await i18n.loadNamespaces(['setup', 'common']);
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const feed: FeedSourceRow = {
  id: 1,
  client_id: 1,
  name: 'Acme Feed',
  source_format: 'xml',
  cron_expression: '0 9 * * *',
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

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/clients/:clientId/feeds/:feedSourceId?/setup" element={<SetupPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function SearchProbe({ onSearch }: { onSearch: (search: string) => void }) {
  const { search } = useLocation();
  onSearch(search);
  return null;
}

describe('SetupPage', () => {
  it('renders the error state without fetching when the route param is missing', () => {
    const spy = stubFetch(() => jsonResponse({}));
    renderAt('/clients/1/feeds/setup');
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it('fetches the feed source when the route param is present', async () => {
    const spy = stubFetch((url) => {
      if (url === '/feed-sources/1') {
        return jsonResponse({
          id: 1, client_id: 1, name: 'Feed', source_format: 'xml',
          cron_expression: '0 * * * *', target_country: 'DE', target_language: 'de',
          currency: 'EUR', source_url: null, feed_type: 'full',
          history_retention_count: 30, volume_drop_threshold_pct: 20,
          configuration: {}, export_url: null,
          created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00',
        });
      }
      return jsonResponse({});
    });
    renderAt('/clients/1/feeds/1/setup');
    await waitFor(() => expect(spy).toHaveBeenCalledWith('/feed-sources/1', expect.anything()));
  });

  it('renders settings tab by default', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      return jsonResponse({});
    });

    renderAt('/clients/1/feeds/1/setup');

    expect(await screen.findByRole('tab', { name: /settings/i }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /mapping/i })).toBeInTheDocument();
    expect(screen.getByDisplayValue('Acme Feed')).toBeInTheDocument();
  });

  it('switches to mapping tab and updates search param', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/field-mapping') return jsonResponse({ version: 1, auto_mapped: false, source_fields: [], mappings: {} });
      if (url === '/registry/attributes') return jsonResponse([]);
      return jsonResponse({});
    });

    let currentSearch = '';
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/clients/1/feeds/1/setup']}>
          <Routes>
            <Route
              path="/clients/:clientId/feeds/:feedSourceId?/setup"
              element={(
                <>
                  <SetupPage />
                  <SearchProbe onSearch={(s) => { currentSearch = s; }} />
                </>
              )}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByRole('tab', { name: /settings/i });

    await user.click(screen.getByRole('tab', { name: /mapping/i }));

    await waitFor(() => {
      expect(currentSearch).toContain('tab=mapping');
    });

    expect(await screen.findByText(/field mapping/i)).toBeInTheDocument();

    view.unmount();
    renderAt('/clients/1/feeds/1/setup?tab=mapping');
    expect(await screen.findByText(/field mapping/i)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /mapping/i })).toHaveAttribute('aria-selected', 'true');
  });
});
