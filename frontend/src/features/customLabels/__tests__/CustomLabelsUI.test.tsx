import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
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

function renderUI() {
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
        element: <CustomLabelsUI pluginId="custom_labels" scope={{ feedSourceId: 1 }} />,
      },
    ],
    { initialEntries: ['/clients/1/feeds/1/plugins/custom_labels'] },
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
    renderUI();
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText('custom_label_1')).toBeInTheDocument();
    expect(screen.getByText('id')).toBeInTheDocument();
    expect(screen.getByText('Brand - Mid Funnel')).toBeInTheDocument(); // template preview
    expect(screen.queryByText('Off')).not.toBeInTheDocument(); // inactive rule hidden
  });

  it('shows the parsed/deduped ID count from prefilled data', async () => {
    renderUI();
    await screen.findByText('Mid Funnel');
    expect(screen.getByText('3 unique IDs')).toBeInTheDocument();
  });

  it('wraps the slot grid in a horizontally scrollable container', async () => {
    renderUI();
    expect(await screen.findByText('Mid Funnel'));
    const grid = document.querySelector('[data-testid="slot-grid"]') as HTMLElement;
    expect(grid.style.overflowX).toBe('auto');
  });
});
