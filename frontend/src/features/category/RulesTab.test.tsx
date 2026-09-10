import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider, Link } from 'react-router';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { RulesTab } from './RulesTab';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

type Route = { match: string; body: unknown; status?: number; exact?: boolean };

function routeHandler(routes: Route[]) {
  return (url: string) => {
    for (const route of routes) {
      if (route.exact ? url === route.match : url.startsWith(route.match)) {
        return jsonResponse(route.body, route.status);
      }
    }
    return jsonResponse({});
  };
}

const GLOBAL_RULE = {
  id: 'g1', source_field: 'product_type', operator: 'eq',
  source_value: 'new', taxonomy_id: '531', is_excluded: false,
};

const CLIENT_RULE = {
  id: 'c1', source_field: 'color', operator: 'contains',
  source_value: 'zwart', taxonomy_id: '114', is_excluded: false,
};

const REGISTRY = [
  { name: 'product_type', kind: 'string', required: 'yes', sub_fields: [], enum_values: [] },
  { name: 'color', kind: 'string', required: 'no', sub_fields: [], enum_values: [] },
];

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderRulesTab(
  scope: { clientId?: number; feedSourceId?: number },
  routes: Route[],
) {
  const fetchMock = stubFetch(routeHandler(routes));
  renderRulesTabWithHandler(scope, fetchMock);
  return fetchMock;
}

function renderRulesTabWithHandler(
  scope: { clientId?: number; feedSourceId?: number },
  fetchHandler: (url: string) => Response | Promise<Response>,
) {
  const client = makeClient();
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: (
          <RulesTab pluginId="category" scope={scope} language="en-US" feedSourceId={scope.feedSourceId} />
        ),
      },
      { path: '/other', element: <div>Left page</div> },
    ],
    { initialEntries: ['/'] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const BASE_ROUTES: Route[] = [
  { match: '/plugins/category/config?client_id=1', body: { rules: [CLIENT_RULE] }, exact: true },
  { match: '/plugins/category/config', body: { rules: [GLOBAL_RULE] } },
  { match: '/registry/attributes', body: REGISTRY },
];

beforeAll(async () => {
  await i18n.loadNamespaces(['category', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
  notifications.clean();
});

describe('RulesTab', () => {
  it('renders merged view at client tier: global rule read-only with Inherited badge, client rule editable', async () => {
    renderRulesTab({ clientId: 1 }, BASE_ROUTES);
    expect(await screen.findByText('g1')).toBeInTheDocument();
    expect(screen.getByText('c1')).toBeInTheDocument();
    expect(screen.getByText('Inherited')).toBeInTheDocument();
    expect(screen.getByTestId('scope-badge-global')).toBeInTheDocument();
    expect(screen.getByTestId('delete-g1')).toBeDisabled();
    expect(screen.getByTestId('delete-c1')).toBeEnabled();
  });

  it('Add rule appends an editable rule with product_type/eq defaults', async () => {
    renderRulesTab({ clientId: 1 }, BASE_ROUTES);
    await screen.findByText('c1');
    await userEvent.click(screen.getByRole('button', { name: 'Add rule' }));
    const productTypeInputs = await screen.findAllByDisplayValue('product_type');
    expect(productTypeInputs.length).toBeGreaterThanOrEqual(1);
    expect(productTypeInputs.some((input) => !input.hasAttribute('disabled'))).toBe(true);
    const operatorInputs = screen.getAllByDisplayValue('equals');
    expect(operatorInputs.length).toBeGreaterThanOrEqual(1);
    expect(operatorInputs.some((input) => !input.hasAttribute('disabled'))).toBe(true);
  });

  it('Save: POSTs validate first, then PUTs rules to client config on success', async () => {
    const fetchMock = renderRulesTab({ clientId: 1 }, [
      ...BASE_ROUTES,
      { match: '/plugins/category/validate', body: { status: 'ok' } },
    ]);
    await screen.findByText('c1');
    const showSpy = vi.spyOn(notifications, 'show');
    await userEvent.click(screen.getByRole('button', { name: 'Add rule' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith(expect.objectContaining({ message: 'Rules saved.' })),
    );
    const calls = fetchMock.mock.calls.map((call) => ({
      url: String(call[0]),
      method: (call[1]?.method) ?? 'GET',
      body: call[1]?.body,
    }));
    const validateIdx = calls.findIndex((c) => c.url.includes('/plugins/category/validate'));
    const putIdx = calls.findIndex(
      (c) => c.method === 'PUT' && c.url.includes('/plugins/category/config?client_id=1'),
    );
    expect(validateIdx).toBeGreaterThan(-1);
    expect(putIdx).toBeGreaterThan(-1);
    expect(validateIdx).toBeLessThan(putIdx);
    const putBody = JSON.parse(calls[putIdx].body as string);
    expect(putBody.rules).toEqual(
      expect.arrayContaining([expect.objectContaining({ source_field: 'product_type' })]),
    );
  });

  it('Validate 422: surfaces error summary and never PUTs', async () => {
    const fetchMock = renderRulesTab({ clientId: 1 }, [
      ...BASE_ROUTES,
      {
        match: '/plugins/category/validate',
        body: { errors: ['source_value: Value must not be empty'] },
        status: 422,
      },
    ]);
    await screen.findByText('c1');
    const showSpy = vi.spyOn(notifications, 'show');
    await userEvent.click(screen.getByRole('button', { name: 'Add rule' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(showSpy).toHaveBeenCalled());
    expect(showSpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('source_value') }),
    );
    const calls = fetchMock.mock.calls.map((call) => ({
      url: String(call[0]),
      method: (call[1]?.method) ?? 'GET',
    }));
    expect(calls.some((c) => c.url.includes('/plugins/category/validate'))).toBe(true);
    expect(
      calls.some((c) => c.method === 'PUT' && c.url.includes('/plugins/category/config?client_id=1')),
    ).toBe(false);
  });

  it('Dirty guard: navigation is blocked and ConfirmModal opens, proceed navigates', async () => {
    const router = createMemoryRouter(
      [
        {
          path: '/',
          element: (
            <div>
              <Link to="/other">Leave</Link>
              <RulesTab pluginId="category" scope={{ clientId: 1 }} language="en-US" feedSourceId={undefined} />
            </div>
          ),
        },
        { path: '/other', element: <div>Left page</div> },
      ],
      { initialEntries: ['/'] },
    );
    const client = makeClient();
    stubFetch(routeHandler(BASE_ROUTES));
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await screen.findByText('c1');
    await userEvent.click(screen.getByRole('button', { name: 'Add rule' }));
    await userEvent.click(screen.getByText('Leave'));
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(screen.getByText('Left page')).toBeInTheDocument());
  });

  it('Dirty guard: Cancel keeps the draft and stays on the page', async () => {
    const router = createMemoryRouter(
      [
        {
          path: '/',
          element: (
            <div>
              <Link to="/other">Leave</Link>
              <RulesTab pluginId="category" scope={{ clientId: 1 }} language="en-US" feedSourceId={undefined} />
            </div>
          ),
        },
        { path: '/other', element: <div>Left page</div> },
      ],
      { initialEntries: ['/'] },
    );
    const client = makeClient();
    stubFetch(routeHandler(BASE_ROUTES));
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await screen.findByText('c1');
    await userEvent.click(screen.getByRole('button', { name: 'Add rule' }));
    await userEvent.click(screen.getByText('Leave'));
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() =>
      expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('c1')).toBeInTheDocument();
    expect(screen.queryByText('Left page')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Add rule' })).toBeEnabled();
  });

  it('Rapid double-click on Save fires exactly one validate and one PUT', async () => {
    const baseHandler = routeHandler(BASE_ROUTES);
    let releaseValidate: ((response: Response) => void) | undefined;
    const fetchMock = stubFetch((url: string) => {
      if (url.includes('/plugins/category/validate')) {
        return new Promise<Response>((resolve) => {
          releaseValidate = resolve;
        });
      }
      return baseHandler(url);
    });
    renderRulesTabWithHandler({ clientId: 1 }, fetchMock);
    await screen.findByText('c1');
    await userEvent.click(screen.getByRole('button', { name: 'Add rule' }));
    const saveButton = screen.getByRole('button', { name: 'Save' });
    userEvent.click(saveButton);
    userEvent.click(saveButton);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([url]) => String(url).includes('/plugins/category/validate')),
      ).toHaveLength(1),
    );
    releaseValidate!(jsonResponse({ status: 'ok' }));
    const puts = () =>
      fetchMock.mock.calls.filter(
        ([url, init]) =>
          String(url).includes('/plugins/category/config?client_id=1') &&
          (init?.method ?? 'GET') === 'PUT',
      );
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/plugins/category/validate'))).toHaveLength(1);
  });

  it('Per-rule match badge from stats and matches modal with product list', async () => {
    renderRulesTab({ clientId: 1, feedSourceId: 7 }, [
      ...BASE_ROUTES,
      {
        match: '/plugins/category/stats?feed_source_id=7',
        body: {
          total: 10,
          buckets: { manual: 2, auto: 5, excluded: 1, uncategorized: 2 },
          rules: { g1: 2 },
        },
      },
      {
        match: '/plugins/category/matches',
        body: { total: 1, items: [{ product_id: 'P1', title: 'Nike Air Max' }] },
      },
    ]);
    expect(await screen.findByText('2 matches')).toBeInTheDocument();
    expect(screen.getAllByText('2 matches')).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'Show matched products' }));
    expect(await screen.findByText('Products matched by rule g1')).toBeInTheDocument();
    expect(screen.getByText('P1')).toBeInTheDocument();
    expect(screen.getByText('Nike Air Max')).toBeInTheDocument();
  });
});
