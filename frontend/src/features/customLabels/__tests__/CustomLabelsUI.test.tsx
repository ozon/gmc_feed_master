import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications, Notifications } from '@mantine/notifications';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import CustomLabelsUI from '../../../../../plugins/core/custom_labels/frontend/component';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces(['customLabels', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
  notifications.clean();
});

const GLOBAL_CONFIG = {
  slotRules: [
    {
      id: 'r1', name: 'Mid Funnel', isActive: true, targetSlot: 'custom_label_1',
      matchField: 'id', valueTemplate: '{brand} - Mid Funnel', fallbackTemplate: '',
    },
    {
      id: 'r2', name: 'Off', isActive: false, targetSlot: 'custom_label_0',
      matchField: 'item_group_id', valueTemplate: 'Rising', fallbackTemplate: '',
    },
  ],
};
const CLIENT_CONFIG = {
  slotRules: [
    {
      id: 'r3', name: 'Client Only', isActive: true, targetSlot: 'custom_label_2',
      matchField: 'id', valueTemplate: '{brand} - ClientOnly', fallbackTemplate: '',
    },
  ],
};
const DATA = { slotIds: { r1: 'a,b,c', r3: 'z' } };

function jsonResponseFor(url: string) {
  if (url.startsWith('/plugins/custom_labels/config') && url.includes('client_id=')) {
    return jsonResponse(CLIENT_CONFIG);
  }
  if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(GLOBAL_CONFIG);
  if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
  if (url.startsWith('/registry/attributes')) return jsonResponse([
    { name: 'id', kind: 'scalar', sub_fields: [] },
    { name: 'brand', kind: 'scalar', sub_fields: [] },
    { name: 'item_group_id', kind: 'scalar', sub_fields: [] },
  ]);
  return jsonResponse({});
}

function renderUI(
  scope: { clientId?: number; feedSourceId?: number },
  url = '/clients/1/feeds/1/plugins/custom_labels',
  fetchHandler?: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  stubFetch(fetchHandler ?? jsonResponseFor);
  const element = <CustomLabelsUI pluginId="custom_labels" scope={scope} />;
  const router = createMemoryRouter(
    [
      { path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId', element },
      { path: '/clients/:clientId/plugins/:pluginId', element },
      { path: '/plugins/:pluginId', element },
    ],
    { initialEntries: [url] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <Notifications position="top-right" limit={5} />
      {children}
    </QueryClientProvider>
  );
  render(
    <Wrapper>
      <RouterProvider router={router} />
    </Wrapper>,
  );
}

describe('CustomLabelsUI operational page', () => {
  it('renders one column per active merged rule (global + client)', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument(); // global rule
    expect(screen.getByText('Client Only')).toBeInTheDocument(); // client rule
    expect(screen.getByText('custom_label_1')).toBeInTheDocument();
    expect(screen.getByText('custom_label_2')).toBeInTheDocument();
    expect(screen.getByText('Brand - ClientOnly')).toBeInTheDocument();
    expect(screen.queryByText('Off')).not.toBeInTheDocument(); // inactive hidden
  });

  it('shows the parsed/deduped ID count from prefilled data', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    expect(screen.getByText('3 unique IDs')).toBeInTheDocument();
  });

  it('groups the bulk tab by target slot in registry order', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    const grid = document.querySelector('[data-testid="slot-grid"]') as HTMLElement;
    const groups = grid.querySelectorAll('[data-testid^="slot-group-"]');
    expect(Array.from(groups).map((g) => g.getAttribute('data-testid'))).toEqual([
      'slot-group-custom_label_1', 'slot-group-custom_label_2',
    ]);
    expect(screen.getByTestId('slot-empty-custom_label_0')).toBeInTheDocument();
  });

  it('info boxes show slot explanation and active rule count', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(
      screen.getByText(/mid-funnel segmentation/i),
    ).toBeInTheDocument();
    // both groups have exactly one active rule
    expect(screen.getAllByText('1 active rules').length).toBe(2);
  });

  it('at feed tier fetches config at global AND client scope, data at feed scope', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      return jsonResponseFor(url);
    });
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ feedSourceId: 1 }} />,
        },
      ],
      { initialEntries: ['/clients/1/feeds/1/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Mid Funnel'));
    const configUrls = captured.filter((u) => u.includes('/config'));
    expect(configUrls).toEqual([
      '/plugins/custom_labels/config',
      '/plugins/custom_labels/config?client_id=1',
    ]);
    const dataUrls = captured.filter((u) => u.includes('/data'));
    expect(dataUrls).toContain('/plugins/custom_labels/data?feed_source_id=1');
  });

  it('at global tier the bulk-IDs tab is unavailable (data_scope lacks global) and the rules tab opens by default (near-duplicate: one config URL)', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      return jsonResponseFor(url);
    });
    const router = createMemoryRouter(
      [
        {
          path: '/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{}} />,
        },
      ],
      { initialEntries: ['/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Mid Funnel'));
    // No data request was sent at all.
    expect(captured.some((u) => u.includes('/data'))).toBe(false);
    // Exactly one config request: the global tier only.
    expect(captured.filter((u) => u.includes('/config'))).toEqual([
      '/plugins/custom_labels/config',
    ]);
    // The bulk-IDs tab is disabled; the rules tab (read-write at global tier) is active.
    expect(screen.getByRole('tab', { name: /bulk ids/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /add rule/i })).toBeInTheDocument();
  });

  it('at client tier both config and data are fetched with client_id', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      return jsonResponseFor(url);
    });
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ clientId: 7 }} />,
        },
      ],
      { initialEntries: ['/clients/7/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Mid Funnel'));
    const configUrls = captured.filter((u) => u.includes('/config'));
    expect(configUrls).toEqual([
      '/plugins/custom_labels/config',
      '/plugins/custom_labels/config?client_id=7',
    ]);
    const dataUrl = captured.find((u) => u.includes('/data'));
    expect(dataUrl).toBe('/plugins/custom_labels/data?client_id=7');
    // Both tabs are usable at client tier; the bulk-IDs tab is active by default.
    expect(screen.getByRole('tab', { name: /bulk ids/i })).not.toBeDisabled();
    expect(screen.getByText('3 unique IDs')).toBeInTheDocument();
  });

  it('at global tier the bulk-IDs tab is unavailable (data_scope lacks global) and the rules tab opens by default', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      return jsonResponseFor(url);
    });
    const router = createMemoryRouter(
      [
        {
          path: '/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{}} />,
        },
      ],
      { initialEntries: ['/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Mid Funnel'));
    // No data request was sent at all.
    expect(captured.some((u) => u.includes('/data'))).toBe(false);
    // Exactly one config request: the global tier only.
    expect(captured.filter((u) => u.includes('/config'))).toEqual([
      '/plugins/custom_labels/config',
    ]);
    // The bulk-IDs tab is disabled; the rules tab (read-write at global tier) is active.
    expect(screen.getByRole('tab', { name: /bulk ids/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /add rule/i })).toBeInTheDocument();
  });

  it('at feed-source tier the slot-rules tab is read-only (config edits belong to client/global tier)', async () => {
    stubFetch((url) => jsonResponseFor(url));
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ feedSourceId: 1 }} />,
        },
      ],
      { initialEntries: ['/clients/1/feeds/1/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Mid Funnel'));
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    // Read-only: no Add rule, no Save for rules; inputs disabled.
    expect(screen.queryByRole('button', { name: /add rule/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('rules-readonly-hint')).toBeInTheDocument();
  });

  it('at client tier shows global rules with a Global badge and keeps them read-only', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getAllByTestId('scope-badge-global').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(screen.getByLabelText(/name/i, { selector: 'input' })).toBeDisabled();
    // Client rule stays editable.
    await userEvent.click(screen.getByText('Client Only'));
    expect(screen.getByLabelText(/name/i, { selector: 'input' })).toBeEnabled();
  });

  it('at client tier save writes only client-origin rules', async () => {
    const puts: { url: string; body: unknown }[] = [];
    stubFetch((url, init) => {
      if (url.includes('/config?client_id=1') && init?.method === 'PUT') {
        puts.push({ url, body: JSON.parse(String(init.body)) });
        return jsonResponse(CLIENT_CONFIG);
      }
      return jsonResponseFor(url);
    });
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ clientId: 1 }} />,
        },
      ],
      { initialEntries: ['/clients/1/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <Notifications position="top-right" limit={5} />
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await screen.findByText('Client Only');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    await userEvent.type(screen.getByLabelText(/name/i, { selector: 'input' }), '!');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/saved/i);
    const payload = puts[0].body as { slotRules: { id: string }[] };
    expect(payload.slotRules.map((r) => r.id)).toEqual(['r3']);
  });

  it('at feed tier the read-only hint links to the client-level page', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    const link = screen.getByRole('link', { name: /manage slot rules at client level/i });
    expect(link).toHaveAttribute('href', '/clients/1/plugins/custom_labels');
  });

  it('match field is a searchable combobox offering registry fields and custom entry', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    const input = screen.getByLabelText(/match field/i);
    await userEvent.clear(input);
    await userEvent.type(input, 'brand');
    await userEvent.click(screen.getByRole('option', { name: 'brand' }));
    expect(screen.getByLabelText(/match field/i)).toHaveValue('brand');
  });

  it('rule editor offers the two match modes', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    expect(screen.getByRole('radio', { name: /match value list/i })).toBeChecked();
    await userEvent.click(screen.getByRole('radio', { name: /match all products/i }));
    expect(screen.getByRole('radio', { name: /match all products/i })).toBeChecked();
  });

  it('inactive rows are dimmed and badged', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    expect(screen.getByText('inactive')).toBeInTheDocument();
  });

  it('shows the description and opens the guide drawer with the how-it-works sections', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByTestId('labelizer-description')).toHaveTextContent(/labelizer/i);
    // No inline accordion on the page itself.
    expect(screen.queryByText(/what are slot rules\?/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /open user guide/i }));
    expect(await screen.findByText(/labelizer user guide/i)).toBeInTheDocument();
    expect(screen.getByText(/what are slot rules\?/i)).toBeInTheDocument();
    expect(screen.getByText(/getting started/i)).toBeInTheDocument();
  });
});

describe('CustomLabelsUI bulk tab mode-awareness', () => {
  function renderFeedWithConfig(config: unknown) {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(config);
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse({ slotIds: {} });
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
        { name: 'brand', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
    });
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ feedSourceId: 1 }} />,
        },
      ],
      { initialEntries: ['/clients/1/feeds/1/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  }

  it('all-mode rules show a controlled-by summary instead of the value textarea', async () => {
    renderFeedWithConfig({
      slotRules: [
        { id: 'a1', name: 'All Products', isActive: true, targetSlot: 'custom_label_0',
          matchField: 'id', matchMode: 'all', valueTemplate: '{brand} - All',
          fallbackTemplate: '' },
      ],
    });
    expect(await screen.findByText(/every product gets: brand - all/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/all products ids/i)).not.toBeInTheDocument();
    // feed tier: config is read-only -> no override button
    expect(
      screen.queryByRole('button', { name: /switch to value list/i }),
    ).not.toBeInTheDocument();
  });

  it('values-mode rules relabel the textarea to the match field', async () => {
    renderFeedWithConfig({
      slotRules: [
        { id: 'v1', name: 'By Brand', isActive: true, targetSlot: 'custom_label_1',
          matchField: 'brand', matchMode: 'values', valueTemplate: '{brand} - Mid',
          fallbackTemplate: '' },
      ],
    });
    expect(await screen.findByLabelText(/values for brand/i)).toBeInTheDocument();
  });

  it('at client tier an all-mode rule offers the switch-to-value-list override', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse({
        slotRules: [
          { id: 'a1', name: 'All Products', isActive: true, targetSlot: 'custom_label_0',
            matchField: 'id', matchMode: 'all', valueTemplate: '{brand} - All',
            fallbackTemplate: '' },
        ],
      });
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse({ slotIds: {} });
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
    });
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ clientId: 1 }} />,
        },
      ],
      { initialEntries: ['/clients/1/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    const override = await screen.findByRole('button', { name: /switch to value list/i });
    await userEvent.click(override);
    expect(await screen.findByLabelText(/all products ids/i)).toBeInTheDocument();
  });

  it('at client tier a GLOBAL-origin all-mode rule does NOT offer the switch-to-value-list override (save would silently drop it)', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/config') && url.includes('client_id=')) {
        return jsonResponse({ slotRules: [] });
      }
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse({
        slotRules: [
          { id: 'g1', name: 'Global All', isActive: true, targetSlot: 'custom_label_0',
            matchField: 'id', matchMode: 'all', valueTemplate: '{brand} - Global All',
            fallbackTemplate: '' },
        ],
      });
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse({ slotIds: {} });
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
    });
    const router = createMemoryRouter(
      [
        {
          path: '/clients/:clientId/plugins/:pluginId',
          element: <CustomLabelsUI pluginId="custom_labels" scope={{ clientId: 1 }} />,
        },
      ],
      { initialEntries: ['/clients/1/plugins/custom_labels'] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/every product gets/i)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /switch to value list/i }),
    ).not.toBeInTheDocument();
  });
});

describe('CustomLabelsUI live preview stats', () => {
  const PREVIEW = {
    total: 3,
    rules: {
      r1: { matched: 2, labeled: 2, sample: ['a1', 'a2'] },
      r3: { matched: 1, labeled: 0, sample: ['z1'] },
    },
    slots: {
      custom_label_1: { labeled: 2, coverage: 66.7, rules: ['r1'] },
      custom_label_2: { labeled: 0, coverage: 0, rules: ['r3'] },
    },
  };

  it('renders live stats, sample links, and the shadowed marker on the feed page', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) return jsonResponse(PREVIEW);
      return jsonResponseFor(url);
    });
    expect(await waitFor(() =>
      expect(screen.getByText(/2 products get this label/i)).toBeInTheDocument(),
      { timeout: 2500 })).toBeTruthy();
    expect(screen.getByText(/66\.7% coverage/i)).toBeInTheDocument();
    expect(screen.getAllByText(/based on the last run's 3 staged products/i).length).toBeGreaterThan(0);
    const sample = screen.getByRole('link', { name: 'a1' });
    expect(sample).toHaveAttribute(
      'href', '/clients/1/feeds/1/products?q=a1',
    );
    // r3 matched but never labeled -> shadowed marker
    expect(screen.getByText(/never applied/i)).toBeInTheDocument();
  });

  it('total=0 shows the never-run hint instead of zero stats', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return jsonResponse({ total: 0, rules: {}, slots: {} });
      }
      return jsonResponseFor(url);
    });
    expect(await waitFor(() =>
      expect(screen.getAllByText(/no staged products yet/i).length).toBeGreaterThan(0),
      { timeout: 2500 })).toBeTruthy();
  });

  it('client page sends no preview request and shows the open-from-feed hint', async () => {
    const calls: string[] = [];
    renderUI(
      { clientId: 1 },
      '/clients/1/plugins/custom_labels',
      (url) => {
        calls.push(url);
        return jsonResponseFor(url);
      },
    );
    await screen.findByText('Client Only');
    expect(screen.getAllByText(/open this plugin from a feed/i).length).toBeGreaterThan(0);
    expect(calls.some((u) => u.includes('/preview'))).toBe(false);
  });
});

describe('CustomLabelsUI rule actions', () => {
  it('duplicates the selected rule with a fresh id and localized copy name', async () => {
    const puts: { body: unknown }[] = [];
    const putHandler = (url: string, init?: RequestInit) => {
      if (url.includes('/config?client_id=1') && init?.method === 'PUT') {
        puts.push({ body: JSON.parse(String(init.body)) });
        return jsonResponse(CLIENT_CONFIG);
      }
      return jsonResponseFor(url);
    };
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels', putHandler);
    await screen.findByText('Client Only');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    await userEvent.click(screen.getByRole('button', { name: /duplicate/i }));
    expect(screen.getByText('Client Only (copy)')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/saved/i);
    const payload = puts[0].body as { slotRules: { id: string; name: string }[] };
    const names = payload.slotRules.map((r) => r.name);
    expect(names).toContain('Client Only');
    expect(names).toContain('Client Only (copy)');
    expect(new Set(payload.slotRules.map((r) => r.id)).size).toBe(payload.slotRules.length);
  });

  it('delete asks for confirmation and removes the rule from the editable tier', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Client Only');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(screen.getByText(/delete rule "client only"/i)).toBeInTheDocument();
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /delete/i }));
    // the only remaining rule is the inherited global one — still listed
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.queryByText('Client Only')).not.toBeInTheDocument();
  });

  it('rule actions are hidden for inherited rules', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(screen.queryByRole('button', { name: /duplicate/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
  });

  it('global-origin delete confirm mentions the inheritance blast radius', async () => {
    renderUI({}, '/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel'));
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(screen.getByText(/inherited by every client/i)).toBeInTheDocument();
  });
});

describe('CustomLabelsUI tier override', () => {
  it('feed page shows the short read-only hint with the client-level link', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    const hint = screen.getByTestId('rules-readonly-hint');
    expect(hint).toHaveTextContent(/read-only here — they live at global or client level/i);
    expect(screen.queryByText(/shared templates/i)).not.toBeInTheDocument();
  });

  it('override at client level flips an inherited rule editable and saves it to the client tier', async () => {
    const puts: { body: unknown }[] = [];
    const putHandler = (url: string, init?: RequestInit) => {
      if (url.includes('/config?client_id=1') && init?.method === 'PUT') {
        puts.push({ body: JSON.parse(String(init.body)) });
        return jsonResponse(CLIENT_CONFIG);
      }
      return jsonResponseFor(url);
    };
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels', putHandler);
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Mid Funnel'));
    // inherited rule is read-only, but offers the override
    expect(screen.getByLabelText(/name/i, { selector: 'input' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: /override at client level/i }));
    expect(screen.getByLabelText(/name/i, { selector: 'input' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/saved/i);
    const payload = puts[0].body as { slotRules: { id: string }[] };
    // the overridden global rule (id r1) now saves to the client tier
    expect(payload.slotRules.map((r) => r.id)).toEqual(['r1', 'r3']);
  });

  it('no override action on the feed page (config read-only there)', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(
      screen.queryByRole('button', { name: /override at client level/i }),
    ).not.toBeInTheDocument();
  });
});

describe('CustomLabelsUI tier navigation', () => {
  it('tier badges navigate: feed page links to global and client pages', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    expect(screen.getByTestId('scope-link-global')).toHaveAttribute(
      'href', '/plugins/custom_labels',
    );
    // client appears in both config and data groups — both link to the client page
    const clientLinks = screen.getAllByTestId('scope-link-client');
    expect(clientLinks.length).toBe(2);
    for (const link of clientLinks) {
      expect(link).toHaveAttribute('href', '/clients/1/plugins/custom_labels');
    }
  });

  it('client page links to the global page only', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Client Only');
    expect(screen.getByTestId('scope-link-global')).toHaveAttribute(
      'href', '/plugins/custom_labels',
    );
    expect(screen.queryByTestId('scope-link-client')).not.toBeInTheDocument();
  });
});
