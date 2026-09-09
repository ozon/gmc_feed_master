import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import CategoryUI from './CategoryUI';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

type Route = { match: string; body: unknown; exact?: boolean };

function routeHandler(routes: Route[]) {
  return (url: string) => {
    for (const route of routes) {
      if (route.exact ? url === route.match : url.startsWith(route.match)) {
        return jsonResponse(route.body);
      }
    }
    return jsonResponse({});
  };
}

function renderCategoryUI(
  scope: { clientId?: number; feedSourceId?: number },
  routes: Route[],
) {
  const fetchMock = stubFetch(routeHandler(routes));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(
    <Wrapper>
      <CategoryUI pluginId="category" scope={scope} />
    </Wrapper>,
  );
  return fetchMock;
}

const BASE_ROUTES: Route[] = [
  { match: '/plugins/category/taxonomy/languages', body: { languages: ['en-US'] } },
  { match: '/plugins/category/config', body: { rules: [] } },
  { match: '/plugins/category/data', body: { assignments: {} } },
  { match: '/dashboard/summary', body: { clients: [] } },
];

beforeAll(async () => {
  await i18n.loadNamespaces(['category', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
  notifications.clean();
});

describe('CategoryUI shell', () => {
  it('renders tabs with AI and Uncategorized disabled placeholders and no stats fetch', async () => {
    const fetchMock = renderCategoryUI({ clientId: 1 }, BASE_ROUTES);
    expect(await screen.findByRole('tab', { name: /Dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Rules/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Manual categorization/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^AI$/ })).toBeDisabled();
    expect(screen.getByRole('tab', { name: /Uncategorized/i })).toBeDisabled();
    const urls = fetchMock.mock.calls.map((call) => String(call[0])).join(' ');
    expect(urls.includes('/plugins/category/stats')).toBe(false);
  });

  it('dashboard shows the four buckets for the selected feed source', async () => {
    renderCategoryUI({ clientId: 1 }, [
      ...BASE_ROUTES.slice(0, 3),
      {
        match: '/dashboard/summary',
        body: {
          clients: [
            {
              id: 1,
              name: 'Acme',
              status: 'active',
              feed_sources: [{ id: 7, name: 'DE', last_run_status: 'success' }],
            },
          ],
        },
      },
      {
        match: '/plugins/category/stats?feed_source_id=7',
        body: {
          total: 10,
          buckets: { manual: 2, auto: 5, excluded: 1, uncategorized: 2 },
          rules: {},
        },
      },
    ]);
    await waitFor(() => expect(screen.getByText('10')).toBeInTheDocument());
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getAllByText(/Manual/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Auto \(rules\)/)).toBeInTheDocument();
    expect(screen.getByText(/^Excluded$/)).toBeInTheDocument();
    expect(screen.getAllByText(/^Uncategorized$/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/7 of 10 categorized/)).toBeInTheDocument();
  });
});
