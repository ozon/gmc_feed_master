import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { ManualTab } from './ManualTab';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

type Route = {
  match: string;
  body: unknown;
  status?: number;
  exact?: boolean;
  method?: string;
};

function routeHandler(routes: Route[]) {
  return (url: string, init?: RequestInit) => {
    for (const route of routes) {
      if (route.method && (init?.method ?? 'GET') !== route.method) continue;
      if (route.exact ? url === route.match : url.startsWith(route.match)) {
        return jsonResponse(route.body, route.status);
      }
    }
    return jsonResponse({});
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderManualTab(
  scope: { clientId?: number; feedSourceId?: number },
  routes: Route[],
) {
  const fetchMock = stubFetch(routeHandler(routes));
  renderManualTabWithHandler(scope, fetchMock);
  return fetchMock;
}

function renderManualTabWithHandler(
  scope: { clientId?: number; feedSourceId?: number },
  fetchHandler: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  stubFetch(fetchHandler);
  const client = makeClient();
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: (
          <ManualTab
            pluginId="category"
            scope={scope}
            language="en-US"
            feedSourceId={scope.feedSourceId}
          />
        ),
      },
    ],
    { initialEntries: ['/'] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const DATA_OK: Route = {
  match: '/plugins/category/data?client_id=1',
  body: { assignments: {} },
  exact: true,
  method: 'GET',
};

const PRODUCT_OK: Route = {
  match: '/plugins/category/product?feed_source_id=7&product_id=p1',
  body: {
    product_id: 'p1',
    title: 'Zapatillas running',
    provenance: 'auto',
    rule_id: 'r-auto',
    google_product_category: 'Apparel & Accessories > Shoes',
    status: 'active',
  },
  exact: true,
};

const TAXONOMY_SEARCH: Route = {
  match: '/plugins/category/taxonomy/search?language=en-US',
  body: { items: [{ id: '166', path: 'Apparel & Accessories > Clothing' }] },
};

async function lookupP1() {
  await userEvent.type(await screen.findByLabelText('Product ID'), 'p1');
  await userEvent.click(screen.getByRole('button', { name: 'Look up' }));
  await screen.findByText('Zapatillas running');
}

beforeAll(async () => {
  await i18n.loadNamespaces(['category', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
  notifications.clean();
});

describe('ManualTab', () => {
  it('global scope: needs-client hint and no data request', async () => {
    const fetchMock = renderManualTab({ feedSourceId: 7 }, []);
    expect(
      await screen.findByText('Manual categorization needs a client context.'),
    ).toBeInTheDocument();
    const urls = fetchMock.mock.calls.map((call) => String(call[0])).join(' ');
    expect(urls.includes('/plugins/category/data')).toBe(false);
  });

  it('lookup renders title, provenance badge and current category', async () => {
    renderManualTab({ clientId: 1, feedSourceId: 7 }, [DATA_OK, PRODUCT_OK]);
    await lookupP1();
    expect(screen.getByText('Auto (rule r-auto)')).toBeInTheDocument();
    expect(screen.getByText('Apparel & Accessories > Shoes')).toBeInTheDocument();
  });

  it('assign: taxonomy pick + Assign PUTs merged map and shows success toast', async () => {
    const fetchMock = renderManualTab({ clientId: 1, feedSourceId: 7 }, [
      DATA_OK,
      PRODUCT_OK,
      TAXONOMY_SEARCH,
    ]);    await lookupP1();
    const combo = screen.getByRole('combobox');
    await userEvent.click(combo);
    await userEvent.type(combo, 'cloud');
    const option = await screen.findByText('166 — Apparel & Accessories > Clothing');
    await userEvent.click(option);
    const showSpy = vi.spyOn(notifications, 'show');
    await userEvent.click(screen.getByRole('button', { name: 'Assign category' }));
    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Assignments saved.' }),
      ),
    );
    const put = fetchMock.mock.calls
      .map((call) => ({ url: String(call[0]), method: call[1]?.method, body: call[1]?.body }))
      .find((c) => c.method === 'PUT');
    expect(put).toBeDefined();
    expect(put!.url).toContain('/plugins/category/data?client_id=1');
    expect(JSON.parse(put!.body as string).assignments).toEqual({ p1: '166' });
  });

  it('unassign: existing assignment shows badge + Remove, PUT drops the product key', async () => {
    const fetchMock = renderManualTab({ clientId: 1, feedSourceId: 7 }, [
      {
        match: '/plugins/category/data?client_id=1',
        body: { assignments: { p1: '166' } },
        exact: true,
        method: 'GET',
      },
      PRODUCT_OK,
    ]);
    await lookupP1();
    expect(screen.getByText('166')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Remove assignment' }));
    await waitFor(() => {
      const put = fetchMock.mock.calls
        .map((call) => ({ url: String(call[0]), method: call[1]?.method, body: call[1]?.body }))
        .find((c) => c.method === 'PUT');
      expect(put).toBeDefined();
      expect(JSON.parse(put!.body as string).assignments).toEqual({});
    });
  });

  it('no feed source: Look up disabled with select-feed-source hint', async () => {
    renderManualTab({ clientId: 1, feedSourceId: undefined }, [DATA_OK]);
    const lookup = await screen.findByRole('button', { name: 'Look up' });
    expect(lookup).toBeDisabled();
    expect(screen.getByText('Select a feed source first.')).toBeInTheDocument();
  });

  it('save failure (PUT 500): error toast', async () => {
    renderManualTab({ clientId: 1, feedSourceId: 7 }, [
      DATA_OK,
      PRODUCT_OK,
      TAXONOMY_SEARCH,
      { match: '/plugins/category/data?client_id=1', body: {}, status: 500, method: 'PUT' },
    ]);
    await lookupP1();
    const combo = screen.getByRole('combobox');
    await userEvent.click(combo);
    await userEvent.type(combo, 'cloud');
    const option = await screen.findByText('166 — Apparel & Accessories > Clothing');
    await userEvent.click(option);
    const showSpy = vi.spyOn(notifications, 'show');
    await userEvent.click(screen.getByRole('button', { name: 'Assign category' }));
    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Could not save assignments.' }),
      ),
    );
  });

  it('assign under a concurrent edit: 409 retry re-applies onto the fresh map', async () => {
    function versionedJson(body: unknown, version: number | null, status = 200) {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (version !== null) headers['X-Plugin-Data-Version'] = String(version);
      return new Response(JSON.stringify(body), { status, headers });
    }

    let putCount = 0;
    const fetchMock = stubFetch((url: string, init?: RequestInit) => {
      if (url.startsWith('/plugins/category/data?client_id=1')
          && (init?.method ?? 'GET') === 'PUT') {
        putCount += 1;
        if (putCount === 1) {
          return versionedJson(
            { detail: { message: 'plugin data changed since read', current_version: 11 } },
            null,
            409,
          );
        }
        return versionedJson({ status: 'ok' }, 12);
      }
      if (url === '/plugins/category/data?client_id=1') {
        if (putCount === 0) return versionedJson({ assignments: {} }, 10);
        return versionedJson({ assignments: { other: 'editor' } }, 11);
      }
      if (url.startsWith('/plugins/category/product')) return jsonResponse(PRODUCT_OK.body);
      if (url.startsWith('/plugins/category/taxonomy/search')) {
        return jsonResponse(TAXONOMY_SEARCH.body);
      }
      return jsonResponse({});
    });
    renderManualTabWithHandler({ clientId: 1, feedSourceId: 7 }, fetchMock);
    await lookupP1();
    const combo = screen.getByRole('combobox');
    await userEvent.click(combo);
    await userEvent.type(combo, 'cloud');
    const option = await screen.findByText('166 — Apparel & Accessories > Clothing');
    await userEvent.click(option);

    const showSpy = vi.spyOn(notifications, 'show');
    await userEvent.click(screen.getByRole('button', { name: 'Assign category' }));
    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Assignments saved.' }),
      ),
    );

    const putBodies = fetchMock.mock.calls
      .filter(([url, init]) =>
        String(url).startsWith('/plugins/category/data?client_id=1')
        && (init?.method ?? 'GET') === 'PUT')
      .map(([, init]) => JSON.parse(String(init?.body)) as { assignments: Record<string, string> });
    expect(putBodies).toHaveLength(2);
    expect(putBodies[0].assignments).toEqual({ p1: '166' });
    expect(putBodies[1].assignments).toEqual({ other: 'editor', p1: '166' });
  });
});
