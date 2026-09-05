import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
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
) {
  stubFetch(jsonResponseFor);
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

  it('wraps the slot grid in a horizontally scrollable container', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel'));
    const grid = document.querySelector('[data-testid="slot-grid"]') as HTMLElement;
    expect(grid.style.overflowX).toBe('auto');
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
});
