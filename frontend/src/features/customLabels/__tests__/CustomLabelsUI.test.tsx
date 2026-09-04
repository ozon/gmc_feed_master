import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
});

const CONFIG = {
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
const DATA = { slotIds: { r1: 'a,b,c' } };

function renderUI(scope: { clientId?: number; feedSourceId?: number }, url = '/clients/1/feeds/1/plugins/custom_labels') {
  stubFetch((url) => {
    if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(CONFIG);
    if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
    if (url.startsWith('/registry/attributes')) return jsonResponse([
      { name: 'id', kind: 'scalar', sub_fields: [] },
      { name: 'brand', kind: 'scalar', sub_fields: [] },
      { name: 'item_group_id', kind: 'scalar', sub_fields: [] },
    ]);
    return jsonResponse({});
  });
  const router = createMemoryRouter(
    [
      {
        path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId',
        element: <CustomLabelsUI pluginId="custom_labels" scope={scope} />,
      },
    ],
    { initialEntries: [url] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(
    <Wrapper>
      <RouterProvider router={router} />
    </Wrapper>,
  );
}

describe('CustomLabelsUI operational page', () => {
  it('renders one column per active rule with header metadata', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText('custom_label_1')).toBeInTheDocument();
    expect(screen.getByText('id')).toBeInTheDocument();
    expect(screen.getByText('Brand - Mid Funnel')).toBeInTheDocument(); // template preview
    expect(screen.queryByText('Off')).not.toBeInTheDocument(); // inactive rule hidden
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

  it('at feed-source tier fetches config at client scope (config_scope lacks feed_source) and keeps data at feed scope', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(CONFIG);
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
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
    expect(await screen.findByText('Mid Funnel'));
    const configUrl = captured.find((u) => u.includes('/config'));
    const dataUrl = captured.find((u) => u.includes('/data'));
    expect(configUrl).toBe('/plugins/custom_labels/config?client_id=1');
    expect(dataUrl).toBe('/plugins/custom_labels/data?feed_source_id=1');
  });

  it('at feed-source tier the slot-rules tab is read-only (config edits belong to client/global tier)', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(CONFIG);
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
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
    // The bulk-IDs tab is disabled; the rules tab (read-write at global tier) is active.
    expect(screen.getByRole('tab', { name: /bulk ids/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /add rule/i })).toBeInTheDocument();
  });

  it('at client tier both config and data are fetched with client_id', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(CONFIG);
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
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
    const configUrl = captured.find((u) => u.includes('/config'));
    const dataUrl = captured.find((u) => u.includes('/data'));
    expect(configUrl).toBe('/plugins/custom_labels/config?client_id=7');
    expect(dataUrl).toBe('/plugins/custom_labels/data?client_id=7');
    // Both tabs are usable at client tier; the bulk-IDs tab is active by default.
    expect(screen.getByRole('tab', { name: /bulk ids/i })).not.toBeDisabled();
    expect(screen.getByText('3 unique IDs')).toBeInTheDocument();
  });

  it('at global tier the bulk-IDs tab is unavailable (data_scope lacks global) and the rules tab opens by default', async () => {
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(CONFIG);
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
      ]);
      return jsonResponse({});
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
    // The bulk-IDs tab is disabled; the rules tab (read-write at global tier) is active.
    expect(screen.getByRole('tab', { name: /bulk ids/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /add rule/i })).toBeInTheDocument();
  });

  it('at feed-source tier the slot-rules tab is read-only (config edits belong to client/global tier)', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/config')) return jsonResponse(CONFIG);
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse(DATA);
      if (url.startsWith('/registry/attributes')) return jsonResponse([
        { name: 'id', kind: 'scalar', sub_fields: [] },
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
    expect(await screen.findByText('Mid Funnel'));
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    // Read-only: no Add rule, no Save for rules; inputs disabled.
    expect(screen.queryByRole('button', { name: /add rule/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('rules-readonly-hint')).toBeInTheDocument();
  });
});
