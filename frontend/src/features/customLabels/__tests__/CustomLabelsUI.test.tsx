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
  onlyTab?: 'ids' | 'rules',
) {
  stubFetch(fetchHandler ?? jsonResponseFor);
  const element = <CustomLabelsUI pluginId="custom_labels" scope={scope} onlyTab={onlyTab} />;
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
  it('selects the first populated slot by default; switching slots swaps the ruleset', async () => {
    renderUI({ feedSourceId: 1 });
    const selector = await screen.findByTestId('slot-selector');
    // default = first slot with active rules (custom_label_1: Mid Funnel)
    expect(within(selector).getByText('#2 CUSTOM_LABEL_1')).toBeInTheDocument();
    expect(screen.getByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.queryByText('Client Only')).not.toBeInTheDocument();
    // switch to custom_label_2 (Client Only)
    await userEvent.click(within(selector).getByText('#3 CUSTOM_LABEL_2'));
    expect(screen.getByText('Client Only')).toBeInTheDocument();
    expect(screen.queryByText('Mid Funnel')).not.toBeInTheDocument();
  });

  it('shows the parsed/deduped ID count inside the expanded card', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand the accordion
    expect(await screen.findByText('3 unique IDs')).toBeInTheDocument();
  });

  it('marks client-tier bulk values as inherited at feed tier with a Client badge', async () => {
    const handler = (url: string) => {
      if (url.includes('/plugins/custom_labels/data?feed_source_id=')) return jsonResponse({});
      return jsonResponseFor(url);
    };
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', handler);
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    // only the selected slot's rules are rendered
    expect(screen.getAllByText('Inherited from Client').length).toBe(1);
    const selector = screen.getByTestId('slot-selector');
    await userEvent.click(within(selector).getByText('#3 CUSTOM_LABEL_2'));
    expect(screen.getAllByText('Inherited from Client').length).toBe(1);
  });

  it('slots without active rules show the empty notice when selected', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    const selector = screen.getByTestId('slot-selector');
    await userEvent.click(within(selector).getByText('#1 CUSTOM_LABEL_0'));
    expect(screen.getByTestId('empty-slot-notice')).toBeInTheDocument();
    expect(screen.queryByText('Mid Funnel')).not.toBeInTheDocument();
  });

  it('shows unsaved dots on the rule card and slot selector while values differ', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    expect(document.querySelectorAll('.mantine-Indicator-indicator').length).toBe(0);
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    await userEvent.type(
      await screen.findByLabelText('Product IDs — Mid Funnel'),
      ',d',
    );
    // one dot on the rule card, one on the slot selector
    expect(document.querySelectorAll('.mantine-Indicator-indicator').length).toBe(2);
  });

  it('shows the selected slot explanation and active rule count', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText(/mid-funnel segmentation/i)).toBeInTheDocument();
    expect(screen.getAllByText('1 active rule').length).toBe(1);
  });

  it('active rule count pluralizes for more than one rule', async () => {
    const twoInOneSlot = {
      slotRules: [
        GLOBAL_CONFIG.slotRules[0],
        { id: 'r4', name: 'Second', isActive: true, targetSlot: 'custom_label_1',
          matchField: 'id', valueTemplate: 'X', fallbackTemplate: '' },
      ],
    };
    const handler = (url: string) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(twoInOneSlot);
      return jsonResponseFor(url);
    };
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', handler);
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText('Second')).toBeInTheDocument();
    expect(screen.getByText('2 active rules')).toBeInTheDocument();
  });

  it('values textarea accessible name matches the localized label plus rule name', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(
      await screen.findByRole('textbox', { name: 'Product IDs — Mid Funnel' }),
    ).toBeInTheDocument();
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
    expect(dataUrls).toEqual([
      '/plugins/custom_labels/data?client_id=1',
      '/plugins/custom_labels/data?feed_source_id=1',
    ]);
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
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(await screen.findByText('3 unique IDs')).toBeInTheDocument();
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

  it('onlyTab="ids" renders the bulk grid without any rules tab or rules UI', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', undefined, 'ids');
    expect(await screen.findByTestId('slot-selector')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /slot rules/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /bulk ids/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId('rules-readonly-hint')).not.toBeInTheDocument();
  });

  it('onlyTab="rules" renders the rules list without the bulk grid', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels', undefined, 'rules');
    expect(await screen.findByText('Client Only')).toBeInTheDocument();
    expect(screen.queryByTestId('slot-grid')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /slot rules/i })).not.toBeInTheDocument();
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
  });

  it('at client tier shows global rules with a Global badge and keeps them read-only', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    expect(
      screen.getByText('Mid Funnel').closest('div')
        ?.querySelector('[data-testid="scope-badge-global"]'),
    ).not.toBeNull();
    expect(
      screen.getByText('Off').closest('div')
        ?.querySelector('[data-testid="scope-badge-global"]'),
    ).not.toBeNull();
    expect(
      screen.getByText('Client Only').closest('div')
        ?.querySelector('[data-testid="scope-badge-global"]'),
    ).toBeNull();
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
    await screen.findByText('Mid Funnel'); // load sentinel (ids tab, default slot)
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await screen.findByText('Client Only'); // rules list shows every merged rule
    await userEvent.click(screen.getByText('Client Only'));
    await userEvent.type(screen.getByLabelText(/name/i, { selector: 'input' }), '!');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/saved/i);
    const payload = puts[0].body as { slotRules: { id: string }[] };
    expect(payload.slotRules.map((r) => r.id)).toEqual(['r3']);
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
    expect(await screen.findByText('All Products')).toBeInTheDocument();
    await userEvent.click(screen.getByText('All Products')); // expand the accordion
    expect(await screen.findByText(/every product gets: brand - all/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/product ids — all products/i)).not.toBeInTheDocument();
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
    await userEvent.click(await screen.findByText('By Brand')); // expand
    expect(await screen.findByLabelText(/values for brand/i)).toBeInTheDocument();
  });

  it("clear button empties that rule's value list and zeroes the counter", async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    const textarea = await screen.findByLabelText('Product IDs — Mid Funnel');
    await userEvent.click(
      await screen.findByRole('button', { name: 'Clear value list — Mid Funnel' }),
    );
    expect(textarea).toHaveValue('');
    expect(screen.getByText('0 unique IDs')).toBeInTheDocument();
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
    await userEvent.click(await screen.findByText('All Products')); // expand
    const override = await screen.findByRole('button', { name: /switch to value list/i });
    await userEvent.click(override);
    expect(await screen.findByLabelText(/product ids — all products/i)).toBeInTheDocument();
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
    labeledAny: 2,
    rules: {
      r1: { matched: 2, labeled: 2, sample: ['a1', 'a2'] },
      r3: { matched: 1, labeled: 0, sample: ['z1'] },
    },
    slots: {
      custom_label_1: { labeled: 2, coverage: 66.7, rules: ['r1'] },
      custom_label_2: { labeled: 0, coverage: 0, rules: ['r3'] },
    },
  };

  it('renders the overall coverage dashboard and per-rule match badges', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) return jsonResponse(PREVIEW);
      return jsonResponseFor(url);
    });
    expect(await waitFor(() =>
      expect(screen.getByText(/2 \/ 3 staged products labeled/i)).toBeInTheDocument(),
      { timeout: 2500 })).toBeTruthy();
    expect(document.querySelectorAll('.mantine-Progress-root').length).toBe(1);
    expect(screen.getByTestId('coverage-stat-total')).toHaveTextContent('3');
    expect(screen.getByTestId('coverage-stat-labeled')).toHaveTextContent('2');
    expect(screen.getByTestId('coverage-stat-unlabeled')).toHaveTextContent('1');
    expect(screen.getByTestId('coverage-stat-active-rules')).toHaveTextContent('2');
    // per-rule net-hit badges beneath the progress bar (default slot custom_label_1)
    expect(screen.getByTestId('coverage-rule-hit-r1')).toHaveTextContent('#1 Mid Funnel: 2x');
    expect(screen.getByTestId('coverage-rule-hits')).toBeInTheDocument();
    // default slot custom_label_1: r1 badge visible in the collapsed header
    expect(screen.getByText('2 matched')).toBeInTheDocument();
    // sample product deep-links are gone
    expect(screen.queryByRole('link', { name: 'a1' })).not.toBeInTheDocument();
    // switch to custom_label_2: r3 is matched-but-never-labeled
    const selector = screen.getByTestId('slot-selector');
    await userEvent.click(within(selector).getByText('#3 CUSTOM_LABEL_2'));
    expect(screen.getByText('1 matched')).toBeInTheDocument();
    expect(screen.getByTestId('coverage-rule-hit-r3')).toHaveTextContent('#1 Client Only: 0x');
    expect(screen.queryByRole('link', { name: 'z1' })).not.toBeInTheDocument();
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

  it('client page sends no preview request and shows no stats header', async () => {
    const calls: string[] = [];
    renderUI(
      { clientId: 1 },
      '/clients/1/plugins/custom_labels',
      (url) => {
        calls.push(url);
        return jsonResponseFor(url);
      },
    );
    await screen.findByText('Mid Funnel');
    expect(calls.some((u) => u.includes('/preview'))).toBe(false);
    expect(screen.queryByTestId('coverage-dashboard')).not.toBeInTheDocument();
  });

  it('at feed tier renders the split editor with preview rows from the lookup endpoint', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.includes('/products/lookup')) return jsonResponse({
        matches: {
          a: { count: 1, sample: { product_id: 'a', status: 'active', excluded: false, title: 'Alpha', brand: 'Acme', availability: 'in_stock' } },
          b: { count: 1, sample: { product_id: 'b', status: 'active', excluded: false, title: 'Bravo', brand: 'Beta', availability: 'out_of_stock' } },
        },
      });
      if (url.startsWith('/plugins/custom_labels/data')) {
        return jsonResponse({ slotIds: { r1: 'a\nb', r3: 'z' } });
      }
      return jsonResponseFor(url);
    });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(await screen.findByText('Bravo')).toBeInTheDocument();
  });

  it('at client tier the preview column is absent (no feed context)', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(
      await screen.findByRole('textbox', { name: 'Product IDs — Mid Funnel' }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('product-preview-viewport')).not.toBeInTheDocument();
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
    await screen.findByText('Mid Funnel'); // load sentinel (ids tab, default slot)
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await screen.findByText('Client Only'); // rules list shows every merged rule
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
    await screen.findByText('Mid Funnel'); // load sentinel (ids tab, default slot)
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await screen.findByText('Client Only'); // rules list shows every merged rule
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
    await screen.findByText('Mid Funnel');
    expect(screen.getByTestId('scope-link-global')).toHaveAttribute(
      'href', '/plugins/custom_labels',
    );
    expect(screen.queryByTestId('scope-link-client')).not.toBeInTheDocument();
  });
});

describe('CustomLabelsUI shadowing', () => {
  it('flags values claimed by a higher-priority rule of the same slot', async () => {
    const config = {
      slotRules: [
        { id: 'r1', name: 'Bleeder', isActive: true, targetSlot: 'custom_label_0',
          matchField: 'id', valueTemplate: 'x', fallbackTemplate: '' },
        { id: 'r2', name: 'Later', isActive: true, targetSlot: 'custom_label_0',
          matchField: 'id', valueTemplate: 'y', fallbackTemplate: '' },
      ],
    };
    const handler = (url: string) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(config);
      if (url.startsWith('/plugins/custom_labels/data')) {
        return jsonResponse({ slotIds: { r1: '1,2', r2: '2,3' } });
      }
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
    };
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', handler);
    expect(await screen.findByText('Later')).toBeInTheDocument();
    expect(screen.getByText('1 overridden')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Later')); // expand
    // footer overridden list is gone; the header badge carries the summary
    expect(screen.queryByText(/overridden IDs/i)).not.toBeInTheDocument();
    // inline badge in the preview: line "2,3"'s first ID (2) is claimed by #1
    expect(await screen.findByText('Overridden by #1')).toBeInTheDocument();
  });
});
