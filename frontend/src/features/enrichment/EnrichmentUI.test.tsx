import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import EnrichmentUI from './EnrichmentUI';

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

type Route = {
  match: string;
  body: unknown;
  status?: number;
  exact?: boolean;
  method?: string;
  headers?: Record<string, string>;
};

function routeHandler(routes: Route[]) {
  return (url: string, init?: RequestInit) => {
    for (const route of routes) {
      if (route.method && (init?.method ?? 'GET') !== route.method) continue;
      if (route.exact ? url === route.match : url.startsWith(route.match)) {
        return jsonResponse(route.body, route.status, route.headers);
      }
    }
    return jsonResponse({});
  };
}

function renderEnrichmentUI(
  scope: { clientId?: number; feedSourceId?: number },
  routes: Route[],
) {
  const fetchMock = stubFetch(routeHandler(routes));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: <EnrichmentUI pluginId="enrichment" scope={scope} />,
      },
    ],
    { initialEntries: ['/'] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

const DATA_ROUTE: Route = {
  match: '/plugins/enrichment/data',
  body: {
    suggestions: { p1: { color: 'blue' } },
    pinned: { p2: { size: '42' } },
  },
  headers: { 'X-Plugin-Data-Version': '3' },
};

beforeAll(async () => {
  await i18n.loadNamespaces(['enrichment', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('EnrichmentUI', () => {
  it('renders suggestion and pinned rows', async () => {
    renderEnrichmentUI({ feedSourceId: 7 }, [DATA_ROUTE]);
    expect(await screen.findByText('color: blue')).toBeInTheDocument();
    expect(screen.getByText('size: 42')).toBeInTheDocument();
  });

  it('accept posts selected fields with expected_version', async () => {
    const fetchMock = renderEnrichmentUI({ feedSourceId: 7 }, [DATA_ROUTE]);
    const user = userEvent.setup();
    await screen.findByText('color: blue');
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: /accept selected/i }));
    await waitFor(() => {
      const post = fetchMock.mock.calls
        .map((call) => ({ url: String(call[0]), method: call[1]?.method, body: call[1]?.body }))
        .find((c) => c.method === 'POST' && c.url.includes('/plugins/enrichment/accept'));
      expect(post).toBeDefined();
      expect(post!.url).toContain('feed_source_id=7');
      expect(JSON.parse(post!.body as string)).toEqual({
        feed_source_id: 7,
        expected_version: '3',
        items: [{ product_id: 'p1', fields: ['color'] }],
      });
    });
  });

  it('unpin posts pinned field removal', async () => {
    const fetchMock = renderEnrichmentUI({ feedSourceId: 7 }, [DATA_ROUTE]);
    const user = userEvent.setup();
    await screen.findByText('size: 42');
    await user.click(screen.getByRole('button', { name: /unpin/i }));
    await waitFor(() => {
      const post = fetchMock.mock.calls
        .map((call) => ({ url: String(call[0]), method: call[1]?.method, body: call[1]?.body }))
        .find((c) => c.method === 'POST' && c.url.includes('/plugins/enrichment/unpin'));
      expect(post).toBeDefined();
      expect(JSON.parse(post!.body as string).items).toEqual([
        { product_id: 'p2', fields: ['size'] },
      ]);
    });
  });

  it('scan button posts limit and shows counts', async () => {
    const fetchMock = renderEnrichmentUI({ feedSourceId: 7 }, [
      DATA_ROUTE,
      {
        match: '/plugins/enrichment/scan',
        method: 'POST',
        body: { scanned: 5, with_suggestions: 3, failed: 2 },
      },
    ]);
    const user = userEvent.setup();
    await screen.findByText('color: blue');
    await user.click(screen.getByRole('button', { name: /scan/i }));
    await waitFor(() => {
      const post = fetchMock.mock.calls
        .map((call) => ({ url: String(call[0]), method: call[1]?.method, body: call[1]?.body }))
        .find((c) => c.method === 'POST' && c.url.includes('/plugins/enrichment/scan'));
      expect(post).toBeDefined();
      expect(JSON.parse(post!.body as string).feed_source_id).toBe(7);
    });
  });

  it('enrichment locale files have en/de parity', () => {
    const read = (lang: string) =>
      JSON.parse(
        readFileSync(
          resolve(process.cwd(), `public/locales/${lang}/enrichment.json`),
          'utf-8',
        ),
      );
    const en = read('en');
    const de = read('de');
    const keys = (obj: Record<string, unknown>, prefix = ''): string[] =>
      Object.entries(obj).flatMap(([k, v]) =>
        typeof v === 'object' && v !== null
          ? keys(v as Record<string, unknown>, `${prefix}${k}.`)
          : [`${prefix}${k}`]);
    expect(keys(de).sort()).toEqual(keys(en).sort());
  });
});
