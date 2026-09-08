import { beforeAll, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { SetupPage } from './SetupPage';

beforeAll(async () => {
  await i18n.loadNamespaces(['setup', 'common']);
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

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
});
