import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications, Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { ReactNode } from 'react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import FilterUI from '../../../../../plugins/core/filter/frontend/component';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces(['filter', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  notifications.clean();
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const savedConfig = {
  isActive: true,
  conditions: [{ field: 'brand', op: 'equals', arg: 'Acme', caseSensitive: true }],
};

const route = (
  <FilterUI pluginId="filter" scope={{ feedSourceId: 1 }} />
);

function renderWithStub(stub: (url: string, init?: RequestInit) => Response) {
  stubFetch(stub);
  const router = createMemoryRouter(
    [
      {
        path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId',
        element: route,
      },
    ],
    { initialEntries: ['/clients/1/feeds/1/plugins/filter'] },
  );
  return render(
    <>
      <Notifications position="top-right" limit={1} />
      <RouterProvider router={router} />
    </>,
    { wrapper: withQueryClient() },
  );
}

function renderUI() {
  renderWithStub((url, init) => {
    if (url.startsWith('/plugins/filter/config')) {
      if (init?.method === 'PUT') return jsonResponse({ isActive: true, conditions: [] });
      return jsonResponse(savedConfig);
    }
    if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['brand', 'title', 'price'] });
    if (url.startsWith('/plugins/filter/preview')) return jsonResponse({ total: 308, pass: 137, fail: 171 });
    return jsonResponse({});
  });
}

describe('FilterUI', () => {
  it('loads config and renders the condition row', async () => {
    renderUI();
    expect(await screen.findByTestId('filter-editor')).toBeInTheDocument();
    expect(await screen.findByTestId('condition-row-0')).toBeInTheDocument();
  });

  it('adds and deletes condition rows', async () => {
    const user = userEvent.setup();
    renderUI();
    await screen.findByTestId('condition-row-0');
    await user.click(screen.getByTestId('condition-add'));
    expect(await screen.findByTestId('condition-row-1')).toBeInTheDocument();
    await user.click(screen.getByTestId('condition-delete-1'));
    expect(screen.queryByTestId('condition-row-1')).not.toBeInTheDocument();
  });

  it('renders the preview count from the preview endpoint with a single request on load', async () => {
    let previewCalls = 0;
    renderWithStub((url, init) => {
      if (url.startsWith('/plugins/filter/config')) {
        if (init?.method === 'PUT') return jsonResponse({ isActive: true, conditions: [] });
        return jsonResponse(savedConfig);
      }
      if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['brand', 'title', 'price'] });
      if (url.startsWith('/plugins/filter/preview')) {
        previewCalls += 1;
        return jsonResponse({ total: 308, pass: 137, fail: 171 });
      }
      return jsonResponse({});
    });
    expect(await screen.findByText(/137 of 308/)).toBeInTheDocument();
    await waitFor(() => expect(previewCalls).toBe(1));
  });

  it('save button posts the config and re-syncs to a clean state', async () => {
    const user = userEvent.setup();
    const puts: Array<{ url: string; body: unknown }> = [];
    // Model a real server: GET returns the stored config, PUT persists and returns it.
    let serverConfig: unknown = savedConfig;
    renderWithStub((url, init) => {
      if (url.startsWith('/plugins/filter/config')) {
        if (init?.method === 'PUT') {
          const body = JSON.parse(String(init.body));
          puts.push({ url, body });
          serverConfig = body;
          return jsonResponse(serverConfig);
        }
        return jsonResponse(serverConfig);
      }
      if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['brand'] });
      if (url.startsWith('/plugins/filter/preview')) return jsonResponse({ total: 1, pass: 1, fail: 0 });
      return jsonResponse({});
    });
    await screen.findByTestId('condition-row-0');
    // Pristine config -> Save disabled; toggle isActive to make the draft dirty.
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
    await user.click(screen.getByLabelText(/filter active/i));
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    await screen.findByText(/filter saved/i);
    expect(puts).toHaveLength(1);
    expect(puts[0].body).toEqual({ ...savedConfig, isActive: false });
    // Save invalidates the config query; the refetched config rehydrates the draft -> dirty resolves false.
    await waitFor(() => expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled());
  });
});
